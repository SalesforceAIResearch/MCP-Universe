"""
MCPWrapperManager for building MCP clients with optional wrapper support.

This module extends MCPManager to support building wrapped clients that can
post-process tool outputs.
"""
# pylint: disable=broad-exception-caught,protected-access
import json
from dataclasses import dataclass
from typing import Optional, Union, Dict, Any, List

from mcp.types import TextContent, CallToolResult

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.mcp.client import MCPClient
from mcpuniverse.common.context import Context
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.extensions.mcpplus.agent.react_postprocess_agent import PostProcessAgent  # pylint: disable=no-name-in-module
from mcpuniverse.extensions.mcpplus.utils.stats import PostProcessStats, count_tokens  # pylint: disable=no-name-in-module
from mcpuniverse.extensions.mcpplus.utils.safe_executor import SafeCodeExecutor  # pylint: disable=no-name-in-module


@dataclass
class WrapperConfig:
    """
    Configuration for the MCP wrapper.

    Attributes:
        enabled (bool): Enable/disable wrapper functionality.
        token_threshold (int): Minimum token count to trigger post-processing.
        post_process_llm (Dict): LLM config for post-processor. Defaults to gpt-5-mini for cost optimization.
        llm_timeout (int): Max seconds for LLM API calls during post-processing.
        max_iterations (int): Maximum iterations for post-processor to refine code on failures.
        skip_iteration_on_size_failure (bool): If True, immediately return original
            output when both extraction methods produce outputs that are too large. If False, retry iteration.
            Default is False (retry).
    """
    enabled: bool = False
    token_threshold: int = 2000
    post_process_llm: Dict = None
    llm_timeout: int = 500
    max_iterations: int = 3
    skip_iteration_on_size_failure: bool = False

    def __post_init__(self):
        """Set default post_process_llm if not provided."""
        if self.post_process_llm is None:
            self.post_process_llm = {
                "type": "openai",
                "model_name": "gpt-5-mini"
            }


class WrappedMCPClient(MCPClient):
    """
    MCP Client wrapper that post-processes long structured outputs.

    This class extends MCPClient to intercept tool calls, extract the
    'expected_info' parameter, and post-process long outputs using a
    coding agent.
    """

    def __init__(
        self,
        name: str,
        config: WrapperConfig,
        post_processor=None,
        manager=None
    ):
        """
        Initialize the wrapped MCP client.

        Args:
            name: Client name.
            config: Wrapper configuration.
            post_processor: Post-processing agent instance.
            manager: Reference to parent MCPWrapperManager for reporting stats.
        """
        super().__init__(name)
        self._wrapper_config = config
        self._post_processor = post_processor
        self._manager = manager
        self._wrapper_logger = get_logger(f"Wrapped{self.__class__.__name__}")
        # Track cumulative post-processing statistics
        self._postprocessor_stats = {
            "total_iterations": 0,
            "total_chars_reduced": 0,
            "total_tokens_reduced": 0,
            "tool_calls_processed": 0
        }

    def _get_expected_info_description(self) -> str:
        """
        Get the expected_info parameter description.

        Returns:
            The expected_info description text.
        """
        return (
            'A precise description of what specific information you need from this '
            'tool call to accomplish your immediate goal. '
            'Be explicit about:\n'
            '1. WHAT data/information you need '
            '(e.g., "the adult ticket price", "list of product URLs", "error message text")\n'
            '2. WHY you need it '
            '(e.g., "to answer the user\'s question", "to visit in the next step", "to debug the issue")\n'
            '3. Any CONSTRAINTS '
            '(e.g., "only from the pricing section", "maximum 10 items", "published after 2023")\n'
            'Example good descriptions:\n'
            '  - "The adult ticket price for ABC Theatre from the pricing table, '
            'needed to answer the user\'s question about ticket cost"\n'
            '  - "URLs of all product links on the page, '
            'needed to visit each product page in subsequent steps"\n'
            '  - "All information is needed because I need the complete page structure '
            'to locate the navigation menu"\n'
            'Example bad descriptions:\n'
            '  - "get information" (too vague)\n'
            '  - "price" (unclear which price, why needed, from where)\n'
            '  - "check the page" (not specific about what to extract)'
        )

    async def list_tools(self) -> List[Any]:
        """
        List available tools with expected_info parameter added.

        Returns:
            List of tools with modified schemas.
        """
        tools = await super().list_tools()

        if not self._wrapper_config.enabled:
            return tools

        # Add expected_info parameter to all tool schemas
        for tool in tools:
            if hasattr(tool, 'inputSchema') and isinstance(tool.inputSchema, dict):
                if 'properties' not in tool.inputSchema:
                    tool.inputSchema['properties'] = {}

                # Add expected_info parameter with description
                tool.inputSchema['properties']['expected_info'] = {
                    'type': 'string',
                    'description': self._get_expected_info_description()
                }

        return tools

    async def execute_tool(  # pylint: disable=too-many-return-statements,arguments-renamed
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 5,
        delay: float = 1.0,
        callbacks=None,
        tracer=None,
    ) -> Any:
        """
        Execute a tool with optional post-processing.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments (may include expected_info).
            retries: Number of retry attempts.
            delay: Delay between retries.
            callbacks: Callbacks for status updates.
            tracer: Optional tracer for logging execution.

        Returns:
            Tool result (post-processed if applicable).
        """
        # Extract expected_info if present
        expected_info = arguments.pop('expected_info', None)

        # Debug logging
        self._wrapper_logger.info(
            "Calling upstream tool %s with args: %s (expected_info extracted: %s)",
            tool_name, arguments, bool(expected_info)
        )

        # Call original tool
        result = await super().execute_tool(
            tool_name=tool_name,
            arguments=arguments,
            retries=retries,
            delay=delay,
            callbacks=callbacks
        )
        self._wrapper_logger.info("Tool call succeeded")

        # Debug: log the result type and structure
        self._wrapper_logger.debug(
            "Original result type: %s, is CallToolResult: %s",
            type(result).__name__,
            isinstance(result, CallToolResult)
        )

        # Check if post-processing is needed
        if not self._wrapper_config.enabled:
            return result

        if not expected_info:
            return result

        # Extract text content from result
        result_text = self._extract_text_content(result)

        # Check if output exceeds threshold (using token count)
        # Get model name from post-processor for accurate tokenization
        model_name = "gpt-4"  # Default fallback
        if self._post_processor and hasattr(self._post_processor, '_model_name'):
            model_name = self._post_processor._model_name
        result_tokens = count_tokens(result_text, model=model_name)
        if result_tokens < self._wrapper_config.token_threshold:
            self._wrapper_logger.info(
                "Tool output (%d tokens, %d chars) below threshold (%d tokens), skipping post-processing",
                result_tokens, len(result_text), self._wrapper_config.token_threshold
            )
            return result

        # Get tool description
        tool_description = await self._get_tool_description(tool_name)

        # Post-process the output
        try:
            self._wrapper_logger.info(
                "Post-processing tool output for %s (length: %d)",
                tool_name, len(result_text)
            )

            filtered_text = await self._post_process(
                tool_output=result_text,
                expected_info=expected_info,
                tool_name=tool_name,
                tool_description=tool_description,
                tracer=tracer
            )

            if filtered_text is None:
                # Post-processor failed completely, return original
                self._wrapper_logger.warning("Post-processor returned None, using original result")
                return result

            # Modify the original result to preserve its structure
            if isinstance(result, CallToolResult):
                # Replace the content while preserving the result structure
                result.content = [TextContent(type="text", text=filtered_text)]
                result.isError = False
                return result

            # Fallback: return as-is if not a CallToolResult (shouldn't happen)
            self._wrapper_logger.warning("Result is not CallToolResult, returning filtered text directly")
            return CallToolResult(
                content=[TextContent(type="text", text=filtered_text)],
                isError=False
            )

        except Exception as e:
            self._wrapper_logger.warning(
                "Post-processing failed: %s. Returning original result.", str(e)
            )
            return result

    async def _get_tool_description(self, tool_name: str) -> Optional[str]:
        """
        Get the description of a tool from the available tools.

        Args:
            tool_name: Name of the tool.

        Returns:
            Tool description if found, None otherwise.
        """
        try:
            tools = await self.list_tools()
            for tool in tools:
                if hasattr(tool, 'name') and tool.name == tool_name:
                    if hasattr(tool, 'description'):
                        return tool.description
            return None
        except Exception as e:
            self._wrapper_logger.warning(
                "Failed to get tool description for %s: %s",
                tool_name, str(e)
            )
            return None

    async def _post_process(
        self,
        tool_output: str,
        expected_info: str,
        tool_name: str,
        tool_description: Optional[str] = None,
        tracer=None
    ) -> str:
        """
        Post-process tool output using the extraction and coding agent.

        Args:
            tool_output: Raw tool output.
            expected_info: Expected information description.
            tool_name: Name of the tool.
            tool_description: Optional description of what the tool does.
            tracer: Optional tracer for logging execution.

        Returns:
            Filtered/processed output.
        """
        if self._post_processor is None:
            raise RuntimeError("Post-processor not initialized")

        # Prepare message for PostProcessAgent._execute()
        # Message format: JSON with tool_output, expected_info, tool_name, tool_description
        message = json.dumps({
            "tool_output": tool_output,
            "expected_info": expected_info,
            "tool_name": tool_name,
            "tool_description": tool_description
        })

        # Call execute() which will internally call process() with tracing
        # If tracer is None, use a shared post-processor tracer stored on the manager
        # This ensures all post-processor calls for this task share the same trace_id
        if tracer is None:
            # Create or reuse shared post-processor tracer on the manager
            # IMPORTANT: Use the same collector as stored on the manager (set by benchmark runner)
            if not hasattr(self._manager, '_postprocessor_tracer'):
                # Get collector from manager (set by benchmark runner via set_trace_collector)
                collector = getattr(self._manager, '_trace_collector', None)
                self._manager._postprocessor_tracer = Tracer(collector=collector)
                self._wrapper_logger.warning(
                    "No tracer provided from agent. Using shared post-processor tracer "
                    "(trace_id: %s, collector: %s)",
                    self._manager._postprocessor_tracer.trace_id,
                    collector
                )
            tracer = self._manager._postprocessor_tracer

        # Use tracer.sprout() to create a child tracer that shares the same trace_id
        # but has its own records list (prevents issues with concurrent access)
        with tracer.sprout() as child_tracer:
            agent_response = await self._post_processor.execute(
                message=message,
                tracer=child_tracer
            )

        # Store post-processor trace_id (only the first time - all calls share same trace_id)
        if not hasattr(self._manager, '_postprocessor_trace_id'):
            self._manager._postprocessor_trace_id = agent_response.trace_id

        # Parse response to extract filtered_output and stats
        response_data = json.loads(agent_response.response)
        filtered_output = response_data["filtered_output"]
        stats_dict = response_data["stats"]

        # Reconstruct PostProcessStats from dict
        stats = PostProcessStats(
            postprocessor_iterations=stats_dict["postprocessor_iterations"],
            original_chars=stats_dict["original_chars"],
            filtered_chars=stats_dict["filtered_chars"],
            chars_reduced=stats_dict["chars_reduced"],
            original_tokens=stats_dict["original_tokens"],
            filtered_tokens=stats_dict["filtered_tokens"],
            tokens_reduced=stats_dict["tokens_reduced"],
            success=stats_dict["success"]
        )

        # Update cumulative statistics (local)
        self._postprocessor_stats["total_iterations"] += stats.postprocessor_iterations
        self._postprocessor_stats["total_chars_reduced"] += stats.chars_reduced
        self._postprocessor_stats["total_tokens_reduced"] += stats.tokens_reduced
        self._postprocessor_stats["tool_calls_processed"] += 1

        # Report stats to manager (if available)
        if self._manager and hasattr(self._manager, '_aggregated_stats'):
            self._manager._aggregated_stats["total_iterations"] += stats.postprocessor_iterations
            self._manager._aggregated_stats["total_chars_reduced"] += stats.chars_reduced
            self._manager._aggregated_stats["total_tokens_reduced"] += stats.tokens_reduced
            self._manager._aggregated_stats["original_chars"] += stats.original_chars
            self._manager._aggregated_stats["filtered_chars"] += stats.filtered_chars
            self._manager._aggregated_stats["original_tokens"] += stats.original_tokens
            self._manager._aggregated_stats["filtered_tokens"] += stats.filtered_tokens
            self._manager._aggregated_stats["tool_calls_processed"] += 1
            self._wrapper_logger.debug("Reported stats to manager: %s", self._manager._aggregated_stats)

        # Already logged in detail by postprocessor, so keep this at debug level
        self._wrapper_logger.debug("POST-PROCESSING complete: iterations=%d, chars_reduced=%d, tokens_reduced=%d",
                                   stats.postprocessor_iterations, stats.chars_reduced, stats.tokens_reduced)

        return filtered_output

    def _extract_text_content(self, result: Any) -> str:
        """
        Extract text content from MCP result.

        Args:
            result: MCP tool result.

        Returns:
            Text content as string.
        """
        if isinstance(result, CallToolResult):
            if result.content:
                for content_item in result.content:
                    if isinstance(content_item, TextContent):
                        return content_item.text

        # Fallback: convert to string
        return str(result)


class MCPWrapperManager(MCPManager):
    """
    Extended MCP Manager that supports building wrapped clients.

    This class extends MCPManager to support optional wrapper configuration.
    When a wrapper_config is provided, it builds wrapped clients that can
    post-process tool outputs. Otherwise, it falls back to the standard
    MCPManager behavior.

    Attributes:
        _wrapper_config: Configuration for wrapping clients.
        _post_processor: Post-processor agent instance (initialized when needed).
        _llm: Language model for post-processing (set before building wrapped clients).
    """

    def __init__(
        self,
        config: Optional[Union[str, Dict]] = None,
        context: Optional[Context] = None,
        wrapper_config: Optional[Union[Dict, WrapperConfig]] = None
    ):
        """
        Initialize MCPWrapperManager.

        Args:
            config: MCP server configuration file path or dictionary.
            context: Context information (environment variables, metadata).
            wrapper_config: Optional wrapper configuration. If provided and enabled,
                clients will be wrapped with post-processing capabilities.
        """
        super().__init__(config=config, context=context)

        # Parse wrapper config
        if isinstance(wrapper_config, dict):
            self._wrapper_config = WrapperConfig(**wrapper_config)
        else:
            self._wrapper_config = wrapper_config

        self._post_processor = None
        self._llm = None
        self._logger = get_logger(self.__class__.__name__)

        # Track aggregated stats at manager level
        self._aggregated_stats = {
            "total_iterations": 0,
            "total_chars_reduced": 0,
            "total_tokens_reduced": 0,
            "original_chars": 0,
            "filtered_chars": 0,
            "original_tokens": 0,
            "filtered_tokens": 0,
            "tool_calls_processed": 0
        }

    def set_llm(self, llm):
        """
        Set the language model for post-processing.

        This must be called before building wrapped clients if wrapper is enabled.

        Args:
            llm: Language model instance to use for post-processing.
        """
        self._llm = llm

    def get_all_postprocessor_stats(self) -> Dict[str, int]:
        """
        Get aggregated post-processor statistics from all wrapped clients.

        Stats are accumulated directly at the manager level when clients report them.

        Returns:
            Dictionary with aggregated stats including character and token counts.
        """
        self._logger.debug("Returning aggregated stats: %s", self._aggregated_stats)
        return self._aggregated_stats.copy()

    def reset_all_postprocessor_stats(self):
        """Reset post-processor statistics at the manager level."""
        self._aggregated_stats = {
            "total_iterations": 0,
            "total_chars_reduced": 0,
            "total_tokens_reduced": 0,
            "original_chars": 0,
            "filtered_chars": 0,
            "original_tokens": 0,
            "filtered_tokens": 0,
            "tool_calls_processed": 0
        }
        self._logger.debug("Reset aggregated stats")

    def reset_postprocessor_tracer(self):
        """Reset post-processor tracer for next task."""
        if hasattr(self, '_postprocessor_tracer'):
            delattr(self, '_postprocessor_tracer')
        if hasattr(self, '_postprocessor_trace_id'):
            delattr(self, '_postprocessor_trace_id')
        self._logger.debug("Reset post-processor tracer")

    def get_postprocessor_trace_id(self) -> Optional[str]:
        """
        Get the post-processor trace ID for the current task.

        Returns:
            Post-processor trace ID if available, None otherwise.
        """
        return getattr(self, '_postprocessor_trace_id', None)

    def _is_wrapper_enabled(self) -> bool:
        """
        Check if wrapper is enabled.

        Returns:
            True if wrapper is enabled, False otherwise.
        """
        if self._wrapper_config is None:
            return False
        return self._wrapper_config.enabled

    async def build_client(
        self,
        server_name: str,
        transport: str = "stdio",
        timeout: int = 30,
        mcp_gateway_address: str = "",
        permissions: Optional[List[Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> MCPClient:
        """
        Build an MCP client with optional wrapping.

        If wrapper_config is provided and enabled, builds a wrapped client
        using build_wrapped_client. Otherwise, builds a standard client.

        Args:
            server_name: Name of the MCP server to connect to.
            transport: Transport type ("stdio", "sse", or "http").
            timeout: Connection timeout in seconds.
            mcp_gateway_address: MCP gateway server address (for SSE) or HTTP server URL (for HTTP).
            permissions: Optional permissions for the client.
            headers: Optional headers for HTTP/SSE authentication.

        Returns:
            MCPClient or WrappedMCPClient instance.
        """
        # Check if wrapper is enabled
        if self._is_wrapper_enabled():
            return await self.build_wrapped_client(
                server_name=server_name,
                transport=transport,
                timeout=timeout,
                mcp_gateway_address=mcp_gateway_address,
                permissions=permissions,
                headers=headers
            )

        # Fall back to standard client
        return await super().build_client(  # pylint: disable=unexpected-keyword-arg
            server_name=server_name,
            transport=transport,
            timeout=timeout,
            mcp_gateway_address=mcp_gateway_address,
            permissions=permissions,
            headers=headers
        )

    async def _initialize_post_processor(self):
        """
        Initialize the post-processor agent.

        Raises:
            RuntimeError: If LLM is not set.
        """
        config = self._wrapper_config

        self._logger.debug("Initializing post-processor (generates both direct extraction AND code in one call)")

        if self._llm is None:
            raise RuntimeError(
                "LLM must be set via set_llm() before initializing post-processor. "
                "Use wrapper_config with post_process_llm or ensure agent passes its LLM."
            )

        # Create safe code executor with fixed 10 second timeout
        safe_executor = SafeCodeExecutor(timeout=10)

        # Create post-processor config
        post_processor_config = {
            "name": "PostProcessAgent",
            "max_iterations": config.max_iterations,
            "llm_timeout": config.llm_timeout,
            "skip_iteration_on_size_failure": config.skip_iteration_on_size_failure
        }

        # Initialize post-processor
        self._post_processor = PostProcessAgent(
            llm=self._llm,
            safe_executor=safe_executor,
            config=post_processor_config
        )

        # Initialize the post-processor (required by BaseAgent)
        await self._post_processor.initialize()

    def _wrap_client(self, client: MCPClient) -> WrappedMCPClient:
        """
        Wrap an MCP client with post-processing capabilities.

        Args:
            client: The original MCP client.

        Returns:
            WrappedMCPClient that delegates to the original client.
        """
        # Create wrapped client with manager reference
        wrapped = WrappedMCPClient(
            name=client._name,
            config=self._wrapper_config,
            post_processor=self._post_processor,
            manager=self
        )

        # Copy over the session and state from original client
        wrapped._session = client._session
        wrapped._exit_stack = client._exit_stack
        wrapped._cleanup_lock = client._cleanup_lock
        wrapped._project_id = client._project_id
        wrapped._stdio_context = client._stdio_context
        wrapped._server_params = client._server_params

        return wrapped

    async def build_wrapped_client(
        self,
        server_name: str,
        transport: str = "stdio",
        timeout: int = 30,
        mcp_gateway_address: str = "",
        permissions: Optional[List[Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> MCPClient:
        """
        Build a wrapped MCP client with post-processing capabilities.

        Args:
            server_name: Name of the MCP server to connect to.
            transport: Transport type ("stdio", "sse", or "http").
            timeout: Connection timeout in seconds.
            mcp_gateway_address: MCP gateway server address (for SSE) or HTTP server URL (for HTTP).
            permissions: Optional permissions for the client.
            headers: Optional headers for HTTP/SSE authentication.

        Returns:
            WrappedMCPClient instance with post-processing enabled.

        Raises:
            RuntimeError: If wrapper_config is not provided or LLM is not set.
        """
        if self._wrapper_config is None:
            raise RuntimeError("wrapper_config must be provided to build wrapped client")

        if self._llm is None:
            raise RuntimeError("LLM must be set via set_llm() before building wrapped client")

        # Initialize post-processor if not already initialized
        if self._post_processor is None:
            self._logger.info("Initializing post-processor for wrapped client")
            await self._initialize_post_processor()

        # For direct SSE/HTTP URLs, connect directly without server registration
        if transport == "http" and mcp_gateway_address and mcp_gateway_address.startswith("http"):
            # Direct HTTP URL provided - connect directly
            client = MCPClient(name=f"{server_name}_client", permissions=permissions)  # pylint: disable=unexpected-keyword-arg
            await client.connect_to_http_server(mcp_gateway_address, headers=headers, timeout=timeout)
            self._logger.info("Connected directly to HTTP server at %s", mcp_gateway_address)
        elif transport == "sse" and mcp_gateway_address and mcp_gateway_address.startswith("http"):
            # Direct SSE URL provided - connect directly
            client = MCPClient(name=f"{server_name}_client", permissions=permissions)  # pylint: disable=unexpected-keyword-arg
            await client.connect_to_sse_server(mcp_gateway_address, timeout=timeout)
            self._logger.info("Connected directly to SSE server at %s", mcp_gateway_address)
        else:
            # Build standard client (requires server registration)
            client = await super().build_client(  # pylint: disable=unexpected-keyword-arg
                server_name=server_name,
                transport=transport,
                timeout=timeout,
                mcp_gateway_address=mcp_gateway_address,
                permissions=permissions,
                headers=headers
            )

        # Wrap the client
        wrapped_client = self._wrap_client(client)

        self._logger.debug("Built wrapped client for server: %s", server_name)
        return wrapped_client
