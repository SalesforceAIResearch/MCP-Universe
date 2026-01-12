"""
MCPWrapperManager for building MCP clients with optional wrapper support.

This module extends MCPManager to support building wrapped clients that can
post-process tool outputs.
"""
# pylint: disable=broad-exception-caught,protected-access,import-outside-toplevel
# pylint: disable=too-few-public-methods
import json
import signal
from dataclasses import dataclass
from typing import Optional, Union, Dict, Any, List, TYPE_CHECKING

from mcp.types import TextContent, CallToolResult

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.mcp.client import MCPClient
from mcpuniverse.common.context import Context
from mcpuniverse.common.logger import get_logger

# Avoid circular import
if TYPE_CHECKING:
    from mcpuniverse.mcpplus.agent.react_postprocess import PostProcessStats


@dataclass
class WrapperConfig:
    """
    Configuration for the MCP wrapper.

    Attributes:
        enabled (bool): Enable/disable wrapper functionality.
        token_threshold (int): Minimum token count to trigger post-processing.
        use_agent_llm (bool): Use the same LLM as the main agent.
        post_process_llm (Dict): Separate LLM config for post-processor.
        enable_memory (bool): Enable session memory for code reuse.
        execution_timeout (int): Max seconds for filter code execution.
        max_iterations (int): Maximum iterations for post-processor to refine code on failures.
        post_processor_type (str): Deprecated. Retained for backward compatibility but ignored.
            MCP+ uses the dual post-processor by default.
        enable_reflection (bool): Enable LLM-based reflection on output quality.
        max_tool_output_chars (Optional[int]): Maximum characters of tool output to show to post-processor LLM.
            If None or 0, shows entire output. Default is None.
        expected_info_prompt_file (Optional[str]): Path to a text file containing the custom expected_info
            parameter description. If not provided, uses the default built-in prompt.
    """
    enabled: bool = False
    token_threshold: int = 500
    use_agent_llm: bool = True
    post_process_llm: Optional[Dict] = None
    enable_memory: bool = True
    execution_timeout: int = 500
    max_iterations: int = 3
    post_processor_type: str = "dual"
    enable_reflection: bool = False
    max_tool_output_chars: Optional[int] = None
    expected_info_prompt_file: Optional[str] = None


class SafeCodeExecutor:
    """
    Safe Python code executor with blacklist-based restrictions.

    This class executes dynamically generated Python code in a restricted
    environment, blocking dangerous operations via a comprehensive blacklist.
    """

    def __init__(self, timeout: int = 10):
        """
        Initialize the safe code executor.

        Args:
            timeout: Maximum execution time in seconds.
        """
        self.timeout = timeout
        self._logger = get_logger(self.__class__.__name__)

    def execute(self, code: str, data: Any) -> Any:
        """
        Execute filter code with restrictions.

        Args:
            code: Python code to execute.
            data: Input data to be filtered.

        Returns:
            Filtered result from code execution.

        Raises:
            ValueError: If dangerous operations are detected.
            TimeoutError: If execution exceeds timeout.
            Exception: Any exception raised during code execution.
        """
        # Static analysis: Check for dangerous patterns
        self._check_code_safety(code)

        local_vars = {"data": data, "result": None}

        # Execute with timeout
        try:
            result = self._execute_with_timeout(code, local_vars)
            return result
        except Exception as e:
            self._logger.error("Code execution failed: %s", str(e))
            raise

    def _check_code_safety(self, code: str):
        """
        Check code for dangerous patterns using comprehensive blacklist.

        Args:
            code: Python code to check.

        Raises:
            ValueError: If dangerous operations are detected.
        """
        # Comprehensive blacklist of dangerous operations
        dangerous_patterns = [
            # Code execution
            'eval(', 'exec(',

            # Process/system operations
            'os.system', 'os.popen', 'os.spawn', 'os.exec',
            'subprocess', 'popen', 'sys.modules', 'ctypes'

            # Input operations
            'input(', 'raw_input(',

            # Introspection/reflection that can be dangerous
            '__builtins__', '__import__',
            '__class__', '__dict__', '__code__', '__bases__',
            '__subclasses__', '__mro__', '__globals__',

            # Module reloading
            'reload(', 'importlib',

            # Pickle (can execute arbitrary code)
            'pickle', 'cpickle', 'shelve',

            # Other dangerous operations
            'exit(', 'quit(', 'breakpoint('
        ]

        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                raise ValueError(f"Dangerous operation detected: {pattern}")

        self._logger.debug("Code safety check passed")

    def _execute_with_timeout(
        self,
        code: str,
        local_vars: Dict[str, Any]
    ) -> Any:
        """
        Execute code with a timeout.

        Args:
            code: Python code to execute.
            local_vars: Local variables including input data.

        Returns:
            Result of code execution.

        Raises:
            TimeoutError: If execution exceeds timeout.
        """
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Code execution exceeded {self.timeout} seconds")

        # Set up timeout (Unix only)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(self.timeout)
        except (ValueError, AttributeError):
            # Windows or signal not available
            old_handler = None

        try:
            # Execute the code
            exec(code, local_vars)  # pylint: disable=exec-used

            # Return the result variable
            if "result" in local_vars and local_vars["result"] is not None:
                return local_vars["result"]

            # If no result variable, return the data
            return local_vars.get("data")

        except NameError as e:
            # Variable reference error - provide detailed context
            self._logger.error(
                "Variable reference error in generated code: %s\nCode:\n%s",
                str(e), code
            )
            raise ValueError(f"Generated code has variable reference error: {e}") from e
        except Exception as e:
            # Log the error with code context
            self._logger.error(
                "Code execution error: %s\nCode:\n%s",
                str(e), code
            )
            raise
        finally:
            # Cancel timeout
            if old_handler is not None:
                try:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                except (ValueError, AttributeError):
                    pass


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
        # Load custom expected_info prompt if provided
        self._expected_info_description = self._load_expected_info_prompt()

    def _load_expected_info_prompt(self) -> str:
        """
        Load the expected_info parameter description from file or use default.

        Returns:
            The expected_info description text.
        """
        self._wrapper_logger.info(
            "Loading expected_info prompt. Config file path: %s",
            self._wrapper_config.expected_info_prompt_file
        )

        if self._wrapper_config.expected_info_prompt_file:
            try:
                with open(self._wrapper_config.expected_info_prompt_file, 'r', encoding='utf-8') as f:
                    prompt_text = f.read().strip()
                    self._wrapper_logger.info(
                        "Successfully loaded custom expected_info prompt from %s (%d chars)",
                        self._wrapper_config.expected_info_prompt_file,
                        len(prompt_text)
                    )
                    return prompt_text
            except FileNotFoundError:
                self._wrapper_logger.warning(
                    "Custom prompt file not found: %s. Using default prompt.",
                    self._wrapper_config.expected_info_prompt_file
                )
            except Exception as e:
                self._wrapper_logger.warning(
                    "Error loading custom prompt file: %s. Using default prompt.",
                    str(e)
                )
        else:
            self._wrapper_logger.info("No custom prompt file specified. Using default prompt.")

        # Default prompt (existing)
        return (
            'A precise description of what specific information you need from '
            'this tool call to accomplish your immediate goal. Be explicit about:\n'
            '1. WHAT data/information you need (e.g., "the adult ticket price", '
            '"list of product URLs", "error message text")\n'
            '2. WHY you need it (e.g., "to answer the user\'s question", '
            '"to visit in the next step", "to debug the issue")\n'
            '3. Any CONSTRAINTS (e.g., "only from the pricing section", '
            '"maximum 10 items", "published after 2023")\n'
            'Example good descriptions:\n'
            '  - "The adult ticket price for Universal Studios from the pricing '
            'table, needed to answer the user\'s question about ticket cost"\n'
            '  - "URLs of all product links on the page, needed to visit each '
            'product page in subsequent steps"\n'
            '  - "All information is needed because I need the complete page '
            'structure to locate the navigation menu"\n'
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

                # Add expected_info parameter with custom or default description
                tool.inputSchema['properties']['expected_info'] = {
                    'type': 'string',
                    'description': self._expected_info_description
                }

        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 5,
        delay: float = 1.0,
        callbacks=None,
        tracer=None,
        progress_callback=None,
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
            progress_callback: Optional async callback for progress updates.
                Signature: async def callback(progress: float, total: float = None, message: str = None)

        Returns:
            Tool result (post-processed if applicable).
        """
        # Extract expected_info if present
        expected_info = arguments.pop('expected_info', None)

        # Report progress: calling upstream tool
        if progress_callback:
            await progress_callback(0, 100, f"Calling {tool_name}...")

        # Call original tool
        result = await super().execute_tool(
            tool_name=tool_name,
            arguments=arguments,
            retries=retries,
            delay=delay,
            callbacks=callbacks
        )
        self._wrapper_logger.info("Tool call succeeded")

        if progress_callback:
            await progress_callback(20, 100, "Tool call completed")

        # Check if post-processing is needed
        if not self._wrapper_config.enabled:
            return result

        if not expected_info:
            return result

        # Extract text content from result
        result_text = self._extract_text_content(result)

        # Check if output exceeds threshold (using token count)
        from mcpuniverse.mcpplus.agent.react_postprocess import count_tokens
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

        # Report progress: post-processing triggered
        if progress_callback:
            await progress_callback(25, 100, f"Post-processing triggered ({len(result_text)} chars)")

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
                tracer=tracer,
                progress_callback=progress_callback
            )

            # EXISTING: Returned filtered_text directly (string)
            # THIS IMPLEMENTATION: Wrap in CallToolResult to match expected format
            if filtered_text is None:
                # Post-processor failed completely, return original
                self._wrapper_logger.warning("Post-processor returned None, using original result")
                return result

            # Create new CallToolResult with filtered content
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
        tracer=None,
        progress_callback=None
    ) -> str:
        """
        Post-process tool output using the coding agent.

        Args:
            tool_output: Raw tool output.
            expected_info: Expected information description.
            tool_name: Name of the tool.
            tool_description: Optional description of what the tool does.
            tracer: Optional tracer for logging execution.
            progress_callback: Optional async callback for progress updates.

        Returns:
            Filtered/processed output.
        """
        if self._post_processor is None:
            raise RuntimeError("Post-processor not initialized")

        # Set progress callback on post-processor for use during process()
        if progress_callback and hasattr(self._post_processor, 'set_progress_callback'):
            self._post_processor.set_progress_callback(progress_callback)

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
            from mcpuniverse.tracer import Tracer

            # Create or reuse shared post-processor tracer on the manager
            # IMPORTANT: Use the same collector as stored on the manager (set by benchmark runner)
            if not hasattr(self._manager, '_postprocessor_tracer'):
                # Get collector from manager (set by benchmark runner via set_trace_collector)
                collector = getattr(self._manager, '_trace_collector', None)
                self._manager._postprocessor_tracer = Tracer(collector=collector)
                self._wrapper_logger.warning(
                    "No tracer provided from agent. Using shared post-processor tracer "
                    "(trace_id: %s, collector: %s)",
                    self._manager._postprocessor_tracer.trace_id, collector
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
        from mcpuniverse.mcpplus.agent.react_postprocess import PostProcessStats
        stats = PostProcessStats(
            postprocessor_iterations=stats_dict["postprocessor_iterations"],
            original_chars=stats_dict["original_chars"],
            filtered_chars=stats_dict["filtered_chars"],
            chars_reduced=stats_dict["chars_reduced"],
            original_tokens=stats_dict["original_tokens"],
            filtered_tokens=stats_dict["filtered_tokens"],
            tokens_reduced=stats_dict["tokens_reduced"],
            success=stats_dict["success"],
            extraction_method=stats_dict.get("extraction_method", "unknown"),
            direct_attempts=stats_dict.get("direct_attempts", 0),
            code_attempts=stats_dict.get("code_attempts", 0)
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
            self._wrapper_logger.info("Reported stats to manager: %s", self._manager._aggregated_stats)

        self._wrapper_logger.info("POST-PROCESSING complete: iterations=%d, chars_reduced=%d, tokens_reduced=%d",
                                  stats.postprocessor_iterations, stats.chars_reduced, stats.tokens_reduced)

        # Build processing summary for persistence in chat
        summary = self._build_processing_summary(stats)
        filtered_output_with_summary = f"{filtered_output}\n\n{summary}"

        return filtered_output_with_summary

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

    def _build_processing_summary(self, stats: "PostProcessStats") -> str:
        """
        Build a human-readable processing summary for inclusion in output.

        Args:
            stats: PostProcessStats from post-processing.

        Returns:
            Formatted summary string.
        """
        # Determine route description
        if stats.extraction_method == "dual":
            route = "Dual extraction"
        elif stats.extraction_method == "direct":
            route = "Direct extraction"
        elif stats.postprocessor_iterations == 0 and stats.success:
            route = "Code generation (cached)"
        elif stats.extraction_method == "code":
            route = "Code generation (new)"
        else:
            route = f"Unknown ({stats.extraction_method})"

        # Calculate reduction percentage
        if stats.original_chars > 0:
            char_reduction_pct = round((stats.chars_reduced / stats.original_chars) * 100)
        else:
            char_reduction_pct = 0

        if stats.original_tokens > 0:
            token_reduction_pct = round((stats.tokens_reduced / stats.original_tokens) * 100)
        else:
            token_reduction_pct = 0

        # Format numbers with commas
        orig_chars = f"{stats.original_chars:,}"
        filt_chars = f"{stats.filtered_chars:,}"
        orig_tokens = f"{stats.original_tokens:,}"
        filt_tokens = f"{stats.filtered_tokens:,}"

        # Build summary
        summary_lines = [
            "---",
            "[MCP+ Post-Processing Summary]",
            f"Route: {route}",
            f"Iterations: {stats.postprocessor_iterations}/3",
            f"Reduction: {orig_chars} -> {filt_chars} chars ({char_reduction_pct}%) | "
            f"{orig_tokens} -> {filt_tokens} tokens ({token_reduction_pct}%)"
        ]

        return "\n".join(summary_lines)


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
        self._logger.info("Returning aggregated stats: %s", self._aggregated_stats)
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
        self._logger.info("Reset aggregated stats")

    def reset_postprocessor_tracer(self):
        """Reset post-processor tracer for next task."""
        if hasattr(self, '_postprocessor_tracer'):
            delattr(self, '_postprocessor_tracer')
        if hasattr(self, '_postprocessor_trace_id'):
            delattr(self, '_postprocessor_trace_id')
        self._logger.info("Reset post-processor tracer")

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
        agent_llm = None
    ) -> MCPClient:
        """
        Build an MCP client with optional wrapping.

        If wrapper_config is provided and enabled, builds a wrapped client
        using build_wrapped_client. Otherwise, builds a standard client.

        EXISTING: MCPManager.build_client() has permissions parameter
        THIS IMPLEMENTATION: Adds agent_llm parameter to support use_agent_llm=True

        Args:
            server_name: Name of the MCP server to connect to.
            transport: Transport type ("stdio" or "sse").
            timeout: Connection timeout in seconds.
            mcp_gateway_address: MCP gateway server address (for SSE).
            permissions: Optional permissions for the client.
            agent_llm: Optional LLM from agent (for use_agent_llm=True).

        Returns:
            MCPClient or WrappedMCPClient instance.
        """
        # If agent_llm provided and we're using agent's LLM, set it now
        if agent_llm is not None and self._wrapper_config and self._wrapper_config.use_agent_llm:
            if self._llm is None:  # Only set if not already set
                self.set_llm(agent_llm)

        # Check if wrapper is enabled
        if self._is_wrapper_enabled():
            return await self.build_wrapped_client(
                server_name=server_name,
                transport=transport,
                timeout=timeout,
                mcp_gateway_address=mcp_gateway_address,
                permissions=permissions
            )

        # Fall back to standard client
        return await super().build_client(
            server_name=server_name,
            transport=transport,
            timeout=timeout,
            mcp_gateway_address=mcp_gateway_address,
            permissions=permissions
        )

    async def _initialize_post_processor(self):
        """
        Initialize the post-processor agent.

        Raises:
            ValueError: If configuration is invalid.
        """
        config = self._wrapper_config

        # MCP+ uses the dual post-processor by default.
        if config.post_processor_type and config.post_processor_type != "dual":
            self._logger.warning(
                "post_processor_type is deprecated and ignored. Using 'dual' instead of '%s'.",
                config.post_processor_type
            )
        from mcpuniverse.mcpplus.agent.react_dual_postprocess import (
            DualPostProcessAgent as PostProcessAgent
        )
        self._logger.info("Using dual post-processor (direct + code in one call)")

        # Determine which LLM to use
        # EXISTING: Tried to build LLM from config dict when use_agent_llm=False
        # THIS IMPLEMENTATION: Use self._llm which is set by:
        #   - Builder (when use_agent_llm=False): resolves post_process_llm.llm reference
        #   - build_client() (when use_agent_llm=True): accepts agent_llm parameter
        # For use_agent_llm=True: If _llm not set, it means agent didn't pass it - that's okay,
        # we'll just skip post-processing or raise error here
        if self._llm is None:
            if config.use_agent_llm:
                # This is expected if agent uses standard MCPUniverse and doesn't know about wrappers
                # Just skip post-processing gracefully
                self._logger.warning(
                    "use_agent_llm=True but LLM not set. "
                    "Agents need to pass agent_llm to build_client(). "
                    "Disabling post-processing."
                )
                # Temporarily disable to avoid errors
                config.enabled = False
                return  # Don't initialize post-processor
            raise RuntimeError(
                "use_agent_llm=False but LLM not set. "
                "Builder should have resolved post_process_llm.llm reference and called set_llm()."
            )
        post_process_llm = self._llm

        safe_executor = SafeCodeExecutor(
            timeout=config.execution_timeout
        )

        # Create post-processor config
        post_processor_config = {
            "name": "PostProcessAgent",
            "enable_memory": config.enable_memory,
            "max_iterations": config.max_iterations,
            "enable_reflection": config.enable_reflection,
            "max_tool_output_chars": config.max_tool_output_chars,
            "execution_timeout": config.execution_timeout
        }

        # Create and return post-processor with new BaseAgent interface
        self._post_processor = PostProcessAgent(
            llm=post_process_llm,
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
        permissions: Optional[List[Dict[str, str]]] = None  # pylint: disable=unused-argument
    ) -> MCPClient:
        """
        Build a wrapped MCP client with post-processing capabilities.

        Args:
            server_name: Name of the MCP server to connect to.
            transport: Transport type ("stdio" or "sse").
            timeout: Connection timeout in seconds.
            mcp_gateway_address: MCP gateway server address (for SSE).
            permissions: Optional permissions for the client.

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

        # Build standard client first
        client = await super().build_client(
            server_name=server_name,
            transport=transport,
            timeout=timeout,
            mcp_gateway_address=mcp_gateway_address,
        )

        # Wrap the client
        wrapped_client = self._wrap_client(client)

        self._logger.info("Built wrapped client for server: %s", server_name)
        return wrapped_client
