"""
OpenAI Agent SDK wrapper for MCP Universe.

This module provides integration between OpenAI's Agent SDK and the MCP Universe framework,
allowing OpenAI agents to use MCP tools and servers.
"""

from typing import List, Dict, Union, Optional
from dataclasses import dataclass
import json
import os
import re

# Third-party imports
import openai
from agents import Agent, Runner, Tool, ModelSettings
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.tool import FunctionTool
from agents.tool_context import ToolContext
from openai.types.shared.reasoning import Reasoning

# Local imports
from mcpuniverse.agent.base import BaseAgent, BaseAgentConfig
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.callbacks.base import (
    send_message_async,
    CallbackMessage,
    MessageType
)
from mcpuniverse.common.logger import get_logger
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.tracer import Tracer
from .utils import build_system_prompt

# Disable tracing to avoid 403 errors with zero data retention organizations
try:
    import agents
    agents.set_tracing_disabled(True)
except ImportError as e:
    raise ImportError(
        "OpenAI Agents SDK is required. Install it with: pip install openai-agents"
    ) from e

# OpenRouter model mapping - same as in openrouter.py
OPENROUTER_MODEL_MAP = {
    "Qwen3Coder_OR": "qwen/qwen3-coder",
    "GrokCoderFast1_OR": "x-ai/grok-code-fast-1",
    "GPTOSS120B_OR": "openai/gpt-oss-120b",
    "DeepSeekV3_1_OR": "deepseek/deepseek-chat-v3.1",
    "GLM4_5_OR": "z-ai/glm-4.5",
    "GLM4_5_AIR_OR": "z-ai/glm-4.5-air",
    "KimiK2_OR": "moonshotai/kimi-k2",
    "Qwen3Max_OR": "qwen/qwen3-max",
    "KimiK2_0905_OR": "moonshotai/kimi-k2-0905"
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")

@dataclass
class OpenAIAgentSDKConfig(BaseAgentConfig):
    """
    Configuration class for OpenAI Agent SDK agents.

    Extends BaseAgentConfig with OpenAI-specific settings.
    """
    # OpenAI Agent specific settings
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "openai_agent_sdk_prompt.j2")
    instructions: str = "You are a helpful AI assistant."
    model: str = "gpt-4.1"
    max_turns: int = 20
    temperature: Optional[float] = None

    # GPT-5/reasoning model specific settings
    reasoning_effort: Optional[str] = None  # "minimal", "low", "medium", "high"
    verbosity: Optional[str] = None  # "low", "medium", "high"

    # Token limit settings
    max_tokens: Optional[int] = None  # Maximum number of output tokens to generate

    # Output format settings
    output_type: str = "str"  # Can be "str", "dict", or a Pydantic model class name


class OpenAIAgentSDK(BaseAgent):
    """
    OpenAI Agent SDK wrapper for MCP Universe.

    This class integrates OpenAI's Agent SDK with the MCP Universe framework,
    allowing OpenAI agents to use MCP tools and servers while maintaining
    compatibility with the existing MCP Universe agent interface.
    """

    config_class = OpenAIAgentSDKConfig
    alias = ["openai_agent_sdk", "oas", "openai-agent-sdk"]

    def __init__(
        self,
        mcp_manager: MCPManager | None,
        llm: BaseLLM | None,
        config: Optional[Union[Dict, str]] = None,
    ):
        """
        Initialize the OpenAI Agent wrapper.

        Args:
            mcp_manager: MCP server manager (can be None for OpenAI-only usage)
            llm: LLM instance (can be None, will use OpenAI's default)
            config: Agent configuration
        """
        super().__init__(mcp_manager, llm, config)
        self._openai_agent_sdk: Optional[Agent] = None
        self._mcp_tools: List[Tool] = []
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

    def _is_reasoning_model(self, model_name: str) -> bool:
        """Check if the model is a reasoning model that uses reasoning.effort instead of temperature."""
        reasoning_models = [
            "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-chat",
            "o3", "o3-mini", "o4-mini"
        ]
        return any(model_name.startswith(prefix) for prefix in reasoning_models)

    def _is_openrouter_model(self, model_name: str) -> bool:
        """Check if the model is an OpenRouter model (ends with _OR or is in the mapping)."""
        return model_name.endswith('_OR') or model_name in OPENROUTER_MODEL_MAP

    def _get_openrouter_model_name(self, model_name: str) -> str:
        """Get the actual OpenRouter model name from the mapping."""
        return OPENROUTER_MODEL_MAP.get(model_name, model_name)

    def _get_openrouter_api_key(self) -> str:
        """Get OpenRouter API key from environment variable."""
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            self._logger.warning("OPENROUTER_API_KEY environment variable not set for OpenRouter model")
        return api_key

    def _count_conversation_turns(self, result) -> int:
        """
        Count conversation turns using the official OpenAI Agent SDK method.

        According to the official documentation:
        Every RunResult contains a list of new_items, which are things the agent
        produced during the run (messages, tool calls, etc.).

        Args:
            result: The result from Runner.run()

        Returns:
            int: Number of conversation turns
        """
        if not hasattr(result, 'new_items'):
            return 1

        # Official method: count message items
        turns = sum(1 for item in result.new_items if hasattr(item, 'type') and item.type == "message")

        # Fallback: if no message items found, use the length of new_items as a rough estimate
        if turns == 0 and result.new_items:
            turns = len(result.new_items)

        # Ensure at least 1 turn for any successful execution
        return max(1, turns)

    def _extract_json_from_text(self, text: str) -> str:
        """
        Extract JSON from text that might contain additional content before or after the JSON.

        Args:
            text (str): Text that may contain JSON

        Returns:
            str: Extracted JSON string

        Raises:
            ValueError: If no valid JSON is found in the text
        """
        # First, try to parse the text as-is (it might already be pure JSON)
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from code blocks first
        code_block_patterns = [
            r'```json\s*(.*?)```',  # ```json ... ```
            r'```\s*(\{.*?\})\s*```',  # ``` { ... } ```
            r'```\s*(\[.*?\])\s*```',  # ``` [ ... ] ```
        ]

        for pattern in code_block_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    json.loads(match.strip())
                    return match.strip()
                except json.JSONDecodeError:
                    continue

        # Try to find JSON objects or arrays in the text
        # Look for patterns that start with { or [ and have matching closing brackets
        json_patterns = [
            r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Simple nested objects
            r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]',  # Simple nested arrays
            r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}',  # More complex nested objects
            r'\[(?:[^\[\]]|(?:\[[^\[\]]*\]))*\]'  # More complex nested arrays
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    # Validate that this is actually valid JSON
                    json.loads(match)
                    return match
                except json.JSONDecodeError:
                    continue

        # If no JSON patterns worked, try to find content between first { and last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            candidate = text[first_brace:last_brace + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # Try the same for arrays
        first_bracket = text.find('[')
        last_bracket = text.rfind(']')
        if first_bracket != -1 and last_bracket != -1 and first_bracket < last_bracket:
            candidate = text[first_bracket:last_bracket + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # If we still haven't found valid JSON, raise an error
        raise ValueError(f"No valid JSON found in text: {text[:100]}...")

    def _parse_response(self, response_text: str, output_format: Optional[Union[str, Dict]] = None) -> str:
        """
        Parse the response from OpenAI Agent SDK.

        Args:
            response_text (str): Raw response text from the agent
            output_format: The output format that was requested

        Returns:
            str: Parsed response
        """
        if not response_text:
            return response_text

        # If output format was specified as a dict (JSON schema), try to parse JSON response
        if isinstance(output_format, dict):
            try:
                # Try to parse as JSON response
                # Handle cases where JSON might be embedded in other text
                clean_text = response_text.strip().strip('`').strip()

                # Remove "json" prefix if present
                if clean_text.startswith("json"):
                    clean_text = clean_text[4:].strip()

                # Try to extract JSON from the text
                json_text = self._extract_json_from_text(clean_text)
                parsed_response = json.loads(json_text)

                # Check if this is a final answer with specific structure
                if "answer" in parsed_response:
                    return parsed_response["answer"]
                if "response" in parsed_response:
                    return parsed_response["response"]
                # Return the entire parsed object as a formatted string
                return json.dumps(parsed_response, indent=2)

            except (json.JSONDecodeError, ValueError) as e:
                # If JSON parsing fails, log the error but return original text
                self._logger.error("Warning: Failed to parse JSON response: %s", str(e))
                return response_text

        # For non-JSON formats or when JSON parsing fails, return as-is
        return response_text

    def _create_model_settings(self) -> Optional[ModelSettings]:
        """Create appropriate ModelSettings based on model type and configuration."""
        settings_dict = {}

        model_name = self._config.model

        # For OpenRouter models, get the actual model name for reasoning model check
        if self._is_openrouter_model(model_name):
            actual_model_name = self._get_openrouter_model_name(model_name)
        else:
            actual_model_name = model_name

        # Check if it's a reasoning model (check the actual model name for OpenRouter models)
        if self._is_reasoning_model(actual_model_name):
            # For reasoning models, use reasoning.effort and verbosity instead of temperature
            if self._config.reasoning_effort is not None:
                settings_dict["reasoning"] = Reasoning(effort=self._config.reasoning_effort)
            else:
                # Use default reasoning settings for reasoning models
                settings_dict["reasoning"] = Reasoning(effort="low")

            if self._config.verbosity is not None:
                settings_dict["verbosity"] = self._config.verbosity
            else:
                # Use default verbosity for reasoning models
                settings_dict["verbosity"] = "low"

            # Don't use temperature for reasoning models
            if self._config.temperature is not None:
                self._logger.warning(
                    "Warning: temperature parameter is ignored for reasoning model %s. "
                    "Use reasoning_effort instead.", model_name
                )
        else:
            # For non-reasoning models (including most OpenRouter models), use temperature
            if self._config.temperature is not None:
                settings_dict["temperature"] = self._config.temperature

            # Ignore reasoning parameters for non-reasoning models
            if self._config.reasoning_effort is not None or self._config.verbosity is not None:
                self._logger.warning(
                    "Warning: reasoning_effort and verbosity parameters are ignored for "
                    "non-reasoning model %s. Use temperature instead.", model_name
                )

        # Add max_tokens if specified (works for both reasoning and non-reasoning models)
        if self._config.max_tokens is not None:
            settings_dict["max_tokens"] = self._config.max_tokens

        # Return ModelSettings only if we have settings to apply
        return ModelSettings(**settings_dict) if settings_dict else None

    async def _initialize(self):
        """Initialize the OpenAI Agent."""
        # Convert MCP tools to OpenAI Agent tools
        await self._convert_mcp_tools_to_openai()

        # Create the OpenAI Agent
        # Create ModelSettings instance based on model type
        model_settings = self._create_model_settings()

        params = {
            "INSTRUCTION": self._config.instruction,
        }
        if self._config.system_prompt is not None:
            system_prompt = build_system_prompt(
                system_prompt_template=self._config.system_prompt,
                tool_prompt_template="",  # No tool prompt needed
                tools=None,  # No tools in text format
                **params
            )
        else:
            system_prompt = self._config.instructions

        # Check if this is an OpenRouter model and prepare accordingly
        model_name = self._config.model
        agent_kwargs = {
            "name": self._config.name,
            "instructions": system_prompt,
            "tools": self._mcp_tools,
        }

        if self._is_openrouter_model(model_name):
            # For OpenRouter models, use the mapped model name and create custom model
            actual_model_name = self._get_openrouter_model_name(model_name)

            # Set up OpenRouter client configuration

            openrouter_api_key = self._get_openrouter_api_key()
            if not openrouter_api_key:
                self._logger.error("OpenRouter API key not found for model: %s", model_name)
                raise ValueError(
                    f"OPENROUTER_API_KEY environment variable is required for "
                    f"OpenRouter model: {model_name}"
                )

            # Create a custom AsyncOpenAI client for OpenRouter
            openrouter_client = openai.AsyncOpenAI(
                api_key=openrouter_api_key,
                base_url=OPENROUTER_BASE_URL
            )

            # Create a custom model with the OpenRouter client
            custom_model = OpenAIChatCompletionsModel(
                model=actual_model_name,
                openai_client=openrouter_client
            )

            agent_kwargs["model"] = custom_model
            self._logger.info("Using OpenRouter model: %s (mapped from %s)", actual_model_name, model_name)
        else:
            # For regular OpenAI models, use the model name as-is
            agent_kwargs["model"] = model_name

        # Add model_settings only if we have settings to apply
        if model_settings is not None:
            agent_kwargs["model_settings"] = model_settings

        # Create the agent
        self._openai_agent_sdk = Agent(**agent_kwargs)


    async def _convert_mcp_tools_to_openai(self):
        """Convert MCP tools to OpenAI Agent SDK tools."""
        self._mcp_tools = []

        for server_name, tools in self._tools.items():
            for tool in tools:
                # Create a wrapper function for each MCP tool
                openai_tool = self._create_openai_tool_wrapper(server_name, tool)
                self._mcp_tools.append(openai_tool)

    def _create_openai_tool_wrapper(self, server_name: str, mcp_tool):
        """Create an OpenAI Agent SDK tool wrapper for an MCP tool."""

        async def tool_wrapper(**kwargs):
            """Wrapper function that calls the MCP tool."""
            try:
                # Call the MCP tool through the client
                result = await self._mcp_clients[server_name].execute_tool(
                    mcp_tool.name, kwargs
                )

                # Convert MCP result to a format suitable for OpenAI Agent SDK
                if hasattr(result, 'content'):
                    if result.content and len(result.content) > 0:
                        content = result.content[0]
                        if hasattr(content, 'text'):
                            return content.text
                        if hasattr(content, 'data'):
                            return content.data
                    return str(result)
                return str(result)

            except Exception as e:  # pylint: disable=broad-exception-caught
                return f"Error executing tool {mcp_tool.name}: {str(e)}"

        # Create the OpenAI Agent SDK function tool
        # Set function metadata
        tool_wrapper.__name__ = f"{server_name}_{mcp_tool.name}"
        tool_wrapper.__doc__ = mcp_tool.description or f"Tool {mcp_tool.name} from server {server_name}"

        # Add parameter annotations based on MCP tool schema
        if hasattr(mcp_tool, 'inputSchema') and mcp_tool.inputSchema:
            # Convert JSON Schema to function annotations
            # This is a simplified implementation
            try:
                # import inspect  # Future use for advanced schema conversion
                # from typing import get_type_hints  # Future use

                # Create a basic signature based on the schema
                if 'properties' in mcp_tool.inputSchema:
                    properties = mcp_tool.inputSchema['properties']
                    required = mcp_tool.inputSchema.get('required', [])

                    # Update function docstring with parameter info
                    param_docs = []
                    for param_name, param_info in properties.items():
                        param_type = param_info.get('type', 'any')
                        param_desc = param_info.get('description', '')
                        required_str = ' (required)' if param_name in required else ' (optional)'
                        param_docs.append(f"    {param_name} ({param_type}){required_str}: {param_desc}")

                    if param_docs:
                        tool_wrapper.__doc__ = f"{tool_wrapper.__doc__}\n\nParameters:\n" + "\n".join(param_docs)
            except Exception:  # pylint: disable=broad-exception-caught
                # Fallback to basic documentation
                pass

        # Create FunctionTool directly with the MCP schema instead of relying on function_tool's introspection

        async def on_invoke_tool(ctx: ToolContext, input_json: str) -> str:  # pylint: disable=unused-argument
            """Handle tool invocation with proper JSON parsing."""
            try:
                # Parse the input JSON to get parameters
                params = json.loads(input_json) if input_json else {}
                # Call our wrapper function with the parsed parameters
                return await tool_wrapper(**params)
            except json.JSONDecodeError as e:
                return f"Error parsing tool parameters: {str(e)}"
            except Exception as e:  # pylint: disable=broad-exception-caught
                return f"Error executing tool: {str(e)}"

        # Use the original MCP tool's inputSchema directly
        params_schema = mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {
            "type": "object",
            "properties": {},
            "additionalProperties": True
        }

        return FunctionTool(
            name=f"{server_name}_{mcp_tool.name}",
            description=mcp_tool.description or f"Tool {mcp_tool.name} from server {server_name}",
            params_json_schema=params_schema,
            on_invoke_tool=on_invoke_tool,
            strict_json_schema=False  # Keep this False to avoid additionalProperties issues
        )

    async def _execute(
        self,
        message: Union[str, List[str]],
        output_format: Optional[Union[str, Dict]] = None,
        **kwargs
    ) -> AgentResponse:
        """
        Execute the OpenAI Agent.

        Args:
            message: Input message(s) to process
            output_format: Optional output format specification (str or dict)
            **kwargs: Additional arguments including tracer and callbacks

        Returns:
            AgentResponse: The agent's response
        """
        if not self._openai_agent_sdk:
            raise RuntimeError("OpenAI Agent is not initialized")

        # Convert message to string if it's a list
        if isinstance(message, list):
            input_text = " ".join(message)
        else:
            input_text = message

        # Add output format requirements if specified
        if output_format is not None:
            output_format_prompt = self._get_output_format_prompt(output_format)
            if output_format_prompt:
                input_text += f"\n\n{output_format_prompt}"

        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        try:
            # Send start message to callbacks
            await send_message_async(
                callbacks,
                message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    metadata={
                        "event": "agent_start",
                        "data": f"Starting OpenAI Agent SDK execution: {self._config.name}"
                    }
                )
            )

            # Run the OpenAI Agent
            with tracer.sprout() as t:
                result = await Runner.run(
                    self._openai_agent_sdk,
                    input=input_text,
                    max_turns=self._config.max_turns,
                )

                # Log the execution
                t.add({
                    "type": "openai_agent_sdk",
                    "class": self.__class__.__name__,
                    "agent_name": self._config.name,
                    "input": input_text,
                    "output": str(result.final_output),
                    "turns": self._count_conversation_turns(result),
                    "usage": result.usage.model_dump() if hasattr(result, 'usage') else {},
                    "error": ""
                })

                # Parse the response based on output format
                parsed_output = self._parse_response(str(result.final_output), output_format)

                # Send completion message to callbacks
                await send_message_async(
                    callbacks,
                    message=CallbackMessage(
                        source=__file__,
                        type=MessageType.LOG,
                        metadata={
                            "event": "agent_complete",
                            "data": (
                                f"OpenAI Agent SDK execution completed: "
                                f"{self._count_conversation_turns(result)} turns"
                            )
                        }
                    )
                )

                # Create response
                response = AgentResponse(
                    name=self._name,
                    class_name=self.__class__.__name__,
                    response=parsed_output,
                    trace_id=t.id if hasattr(t, 'id') else ""
                )

                return response

        except Exception as e:
            # Send error message to callbacks
            await send_message_async(
                callbacks,
                message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    metadata={
                        "event": "agent_error",
                        "data": f"OpenAI Agent SDK execution failed: {str(e)}"
                    }
                )
            )

            # Log error
            with tracer.sprout() as t:
                t.add({
                    "type": "openai_agent_sdk",
                    "class": self.__class__.__name__,
                    "agent_name": self._config.name,
                    "input": input_text,
                    "output": "",
                    "error": str(e)
                })
            raise

    async def _cleanup(self):
        """Cleanup OpenAI Agent resources."""
        # OpenAI Agent SDK handles its own cleanup
        self._openai_agent_sdk = None
        self._mcp_tools = []

    def get_description(self, with_tools_description=True) -> str:
        """Get agent description."""
        description = self._config.instructions
        text = f"OpenAI Agent SDK name: {self._name}\nInstructions: {description}"

        if with_tools_description and self._mcp_tools:
            # Extract tool names from function tools
            tool_names = []
            for tool in self._mcp_tools:
                if hasattr(tool, '__name__'):
                    tool_names.append(tool.__name__)
                elif hasattr(tool, 'name'):
                    tool_names.append(tool.name)
                else:
                    tool_names.append(str(tool))
            text += f"\nAvailable MCP tools: {', '.join(tool_names)}"

        return text

    def get_openai_agent_sdk(self) -> Optional[Agent]:
        """Get the underlying OpenAI Agent instance."""
        return self._openai_agent_sdk

    @property
    def openai_agent_sdk(self) -> Optional[Agent]:
        """Property to access the underlying OpenAI Agent."""
        return self._openai_agent_sdk
