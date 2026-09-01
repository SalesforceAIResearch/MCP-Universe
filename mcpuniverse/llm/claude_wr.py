"""
Anthropic LLMs
"""
# pylint: disable=broad-exception-caught
import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List, Any

import json
import uuid
import requests
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()

@dataclass
class ClaudeWRConfig(BaseConfig):
    """
    Configuration for Claude models.

    Attributes:
        base_url (str): The Claude API base url.
        api_key (str): The Anthropic API key. Defaults to the value of the ANTHROPIC_API_KEY variable.
        model_name (str): The name of the Claude model to use. Defaults to "claude-sonnet-4".
        temperature (float): Controls randomness in output generation. Defaults to 1.0.
        top_p (Optional[float]): Controls diversity of output generation. Defaults to None.
            Cannot be specified together with temperature for newer Claude models.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 2048.
        thinking_budget_tokens (int): Token budget for thinking mode. Defaults to 4000.
        timeout (int): Request timeout in seconds (default: 60).
    """
    base_url: str = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com/v1/messages")
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model_name: str = "claude-sonnet-4-5"
    temperature: float = 1.0
    top_p: Optional[float] = None
    max_completion_tokens: int = 10000
    thinking_budget_tokens: int = 8000
    timeout: int = 60


class ClaudeWRModel(BaseLLM):
    """
    This class provides methods to generate content using Claude models.

    Attributes:
        config_class (Type[ClaudeConfig]): The configuration class for Claude models.
        alias (str): A short name for the model, set to "claude".
    """
    config_class = ClaudeWRConfig
    alias = "claude_wr"
    env_vars = ["ANTHROPIC_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize the ClaudeWRModel instance.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the model.
                Can be a dictionary or a string. If None, default configuration will be used.
        """
        super().__init__()
        self.config = ClaudeWRModel.config_class.load(config)
        self.logger = get_logger(self.__class__.__name__)

    def _generate(
        self,
        messages: List[dict[str, str]],
        response_format: Optional[Type[PydanticBaseModel]] = None,
        **kwargs
    ):
        """
        Generate content using the Claude model.

        Args:
            messages (List[dict[str, str]]): A list of message dictionaries,
                each containing 'role' and 'content' keys.
            response_format (Type[PydanticBaseModel], optional): A Pydantic model
                defining the structure of the desired output. If None, free-form
                text will be generated (Not supported yet).
            **kwargs: Additional keyword arguments including:
                - max_retries (int): Maximum number of retry attempts (default: 5)
                - base_delay (float): Base delay in seconds for exponential backoff (default: 10.0)
                - timeout (int): Request timeout in seconds (default: 30)

        Returns:
            Union[str, Response, None]: The generated content as a string if no tools,
                a Response object if tools are provided, or None if all retry attempts fail.
        """
        max_retries = kwargs.get("max_retries", 5)
        base_delay = kwargs.get("base_delay", 10.0)

        for attempt in range(max_retries + 1):
            try:
                system_messages = []
                formatted_messages = self._convert_openai_messages_to_claude(
                    messages, system_messages
                )
                if response_format is None:
                    data = {
                        "model": self.config.model_name,
                        "messages": formatted_messages,
                        "stream": False,
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_completion_tokens,
                    }
                    headers = {
                        'x-api-key': self.config.api_key,
                        'anthropic-version': '2023-06-01',
                        'content-type': 'application/json',
                    }

                    # Handle thinking parameter
                    data["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": kwargs.get("thinking_budget_tokens",
                        self.config.thinking_budget_tokens)
                    }

                    # Handle tools if provided - convert from OpenAI format to Claude format
                    if 'tools' in kwargs:
                        data['tools'] = self._convert_openai_tools_to_claude(kwargs['tools'])
                    # Remove our custom parameters from kwargs before updating data
                    filtered_kwargs = {k: v for k, v in kwargs.items()
                                     if k not in [
                                        'thinking_budget_tokens',
                                        'tools', 'max_retries',
                                        'base_delay']}
                    data.update(filtered_kwargs)

                    response = requests.post(
                        self.config.base_url,
                        json=data,
                        headers=headers,
                        timeout=self.config.timeout
                    )

                    # Check for HTTP errors
                    response.raise_for_status()

                    response_json = json.loads(response.text)

                    # If tools are provided, return a response object similar to OpenAI's format
                    if 'tools' in kwargs:
                        return self._create_openai_style_response(response_json)

                    # For backward compatibility, return just the text content when no tools
                    return response_json['result'][0]['text']
                raise NotImplementedError("claude wr does not support response_format!")

            except (requests.exceptions.RequestException, requests.exceptions.Timeout,
                    requests.exceptions.HTTPError) as e:
                if attempt == max_retries:
                    # Last attempt failed, return None instead of raising
                    logging.warning("All %d attempts failed. Last error: %s", max_retries + 1, e)
                    return None

                # Calculate delay with exponential backoff
                delay = base_delay * (2 ** attempt)
                logging.info("Attempt %d failed with error: %s. Retrying in %.1f seconds...",
                           attempt + 1, e, delay)
                time.sleep(delay)

            except Exception as e:
                # For non-retryable errors, return None instead of raising
                logging.error("Non-retryable error occurred: %s", e)
                print("error", e)
                return None

    def _handle_system_message(self, message: dict, system_messages: List[str]):
        """Handle system message by adding to system_messages list."""
        system_messages.append(message["content"])

    def _handle_user_message(self, message: dict) -> dict:
        """Handle user message conversion."""
        return {
            "role": "user",
            "content": message["content"]
        }

    def _handle_assistant_message_with_tools(self, message: dict) -> dict:
        """Handle assistant message with tool calls."""
        content_blocks = []

        # Add text content if present
        if message.get("content"):
            content_blocks.append({
                "type": "text",
                "text": message["content"]
            })

        # Add tool use blocks
        for tool_call in message["tool_calls"]:
            if tool_call.get("type") == "function":
                func = tool_call["function"]
                # Parse arguments if they're a JSON string
                arguments = func["arguments"]
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                content_blocks.append({
                    "type": "tool_use",
                    "id": tool_call["id"],
                    "name": func["name"],
                    "input": arguments
                })

        return {
            "role": "assistant",
            "content": content_blocks
        }

    def _handle_assistant_message(self, message: dict) -> dict:
        """Handle regular assistant message."""
        return {
            "role": "assistant",
            "content": message["content"]
        }

    def _handle_tool_message(self, messages: List[dict]) -> dict:
        """Handle tool result message."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message["content"]
                }
                for message in messages
            ]
        }

    def _convert_openai_messages_to_claude(
            self,
            messages: List[dict],
            system_messages: List[str]
        ) -> List[dict]:
        """
        Convert OpenAI format messages to Claude format, handling tool calls and tool results.

        Args:
            messages: OpenAI format messages
            system_messages: List to collect system messages

        Returns:
            List of Claude format messages
        """
        claude_messages = []

        # for message in messages:
        i = 0
        while i < len(messages):
            message = messages[i]
            role = message.get("role")

            if role == "system":
                self._handle_system_message(message, system_messages)
                i += 1
            elif role == "user":
                claude_messages.append(self._handle_user_message(message))
                i += 1
            elif role == "assistant":
                claude_messages.append(message)
                i += 1
            elif role == "tool":
                all_tool_messages = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    all_tool_messages.append(messages[i])
                    i += 1
                claude_messages.append(self._handle_tool_message(all_tool_messages))
        return claude_messages

    def _convert_openai_tools_to_claude(self, openai_tools: List[dict]) -> List[dict]:
        """
        Convert OpenAI format tools to Claude format.

        OpenAI format:
        {
            "type": "function",
            "function": {
                "name": "function_name",
                "description": "function description",
                "parameters": {...}
            }
        }

        Claude format:
        {
            "name": "function_name",
            "description": "function description",
            "input_schema": {...}
        }
        """
        claude_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func_def = tool["function"]
                if "title" in func_def:
                    del func_def["title"]
                claude_tool = {
                    "name": func_def["name"],
                    "description": func_def.get("description", ""),
                    "input_schema": func_def.get("parameters", {})
                }
                claude_tools.append(claude_tool)
        return claude_tools

    def _create_openai_style_response(self, response_json: dict):
        """
        Create an OpenAI-style response object from Claude's response.

        Args:
            response_json (dict): The raw response

        Returns:
            A response object with OpenAI-style structure
        """
        # Create a simple response object that mimics OpenAI's structure using dataclasses
        @dataclass
        class Choice:
            """Choice class for OpenAI-style response"""
            message: Any

        @dataclass
        class Message:
            """Message class for OpenAI-style response"""
            content: Optional[str] = None
            tool_calls: Optional[List[Any]] = None

        @dataclass
        class Response:
            """Response class for OpenAI-style response"""
            choices: List[Choice]
            model: str

        # Extract content and tool calls from Claude's response
        # Claude's result is an array of content blocks directly
        if 'content' in response_json:  # vertex ai response
            return response_json
        result_blocks = []

        # Convert Claude content blocks to OpenAI format
        openai_tool_calls = []
        text_content = ""

        for block in result_blocks:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    text_content += block.get('text', '')
                elif block.get('type') == 'tool_use':
                    # Convert Claude tool_use to OpenAI tool_call format
                    tool_id = block.get('id', str(uuid.uuid4()))
                    tool_name = block.get('name', '')
                    tool_input = block.get('input', {})

                    # Create OpenAI-style tool call as dict (JSON serializable)
                    tool_call = {
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": (
                                json.dumps(tool_input)
                                if isinstance(tool_input, dict)
                                else str(tool_input)
                            )
                        }
                    }
                    openai_tool_calls.append(tool_call)

        # Set content and tool_calls
        content = text_content if text_content else None
        tool_calls = openai_tool_calls if openai_tool_calls else None

        # Create the response structure
        message = Message(content=content, tool_calls=tool_calls)
        choice = Choice(message)
        response = Response(choices=[choice], model=self.config.model_name)
        return response

    def support_tool_call(self) -> bool:
        """
        Return a flag indicating if the model supports function/tool call API.
        """
        return True

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("ANTHROPIC_API_KEY", self.config.api_key)
