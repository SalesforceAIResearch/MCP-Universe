"""
Salesforce Research Gateway Provider

This provider routes requests through the Salesforce Research Gateway
with support for multiple model types (Claude, OpenAI, etc.).

The gateway uses different endpoints for different model families:
- Claude models: /claude3/process (with Claude-native format)
- OpenAI models: /openai/process/v1/ (with OpenAI-compatible format)

Configuration:
    Both the gateway URL and API key must be set via environment variables
    to maintain security and avoid exposing internal infrastructure in the codebase.

    Required environment variables:
        - RESEARCH_GATEWAY_URL: Base gateway URL (e.g., "https://your-gateway.example.com")
        - SALESFORCE_GATEWAY_KEY: Your gateway API key

    Example usage:
        export RESEARCH_GATEWAY_URL="https://your-gateway.example.com"
        export SALESFORCE_GATEWAY_KEY="your-api-key"

        # Then use in your code or with mcp-build-plus:
        mcp-build-plus --mcp-config ~/.cursor/mcp.json \
            --llm-provider sf_research_gateway \
            --llm-model gpt-5-mini \
            --llm-api-key-env SALESFORCE_GATEWAY_KEY
"""
import os
import time
import logging
import json
import uuid
from typing import Dict, Union, Optional, List, Type, Any
from dataclasses import dataclass

import requests
from openai import OpenAI
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from .base import BaseLLM


# Claude model name mappings (for Research Gateway)
CLAUDE_MODEL_MAP = {
    "claude-sonnet-4": {
        "model_name": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "thinking_enabled": False
    },
    "claude-sonnet-4-thinking": {
        "model_name": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "thinking_enabled": True
    },
    "claude-opus-4": {
        "model_name": "us.anthropic.claude-opus-4-20250514-v1:0",
        "thinking_enabled": False
    },
    "claude-opus-4-thinking": {
        "model_name": "us.anthropic.claude-opus-4-20250514-v1:0",
        "thinking_enabled": True
    }
}


@dataclass
class SFResearchGatewayConfig(BaseConfig):
    """
    Configuration for Salesforce Research Gateway.

    Both the gateway URL and API key should be set via environment variables
    to avoid exposing internal infrastructure details in the codebase.

    Required environment variables:
        - RESEARCH_GATEWAY_URL: The base gateway URL (without endpoint path)
        - SALESFORCE_GATEWAY_KEY: The gateway API key

    Attributes:
        base_url (str): The base gateway URL from RESEARCH_GATEWAY_URL environment variable.
        model_name (str): The model to use. Defaults to "gpt-5-mini".
        api_key (str): The gateway API key from SALESFORCE_GATEWAY_KEY environment variable.
        temperature (float): Controls randomness in output generation. Defaults to 0.0.
        top_p (float): Controls diversity of output generation. Defaults to 1.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 10000.
        thinking_budget_tokens (int): Token budget for Claude thinking mode. Defaults to 4000.
    """
    base_url: str = os.getenv("RESEARCH_GATEWAY_URL", "")
    model_name: str = "gpt-5-mini"
    api_key: str = os.getenv("SALESFORCE_GATEWAY_KEY", "")
    temperature: float = 0.0
    top_p: float = 1.0
    max_completion_tokens: int = 10000
    thinking_budget_tokens: int = 4000


class SFResearchGatewayModel(BaseLLM):
    """
    LLM provider for Salesforce Research Gateway.

    This class intelligently routes requests to the appropriate gateway endpoint
    based on the model type:
    - Claude models → /claude3/process with Claude-native format
    - OpenAI models → /openai/process/v1/ with OpenAI format

    Authentication uses custom X-Api-Key header for both endpoints.

    Attributes:
        config_class: The configuration class.
        alias: Short name "sf_research_gateway".
        env_vars: Required environment variables.
    """
    config_class = SFResearchGatewayConfig
    alias = "sf_research_gateway"
    env_vars = ["RESEARCH_GATEWAY_URL", "SALESFORCE_GATEWAY_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize the SFResearchGatewayModel instance.

        Args:
            config: Configuration for the model. Can be a dictionary or a string.
                If None, default configuration will be used.
        """
        super().__init__()
        self.config = SFResearchGatewayModel.config_class.load(config)
        self.logger = get_logger(self.__class__.__name__)
        self.client = None  # Will be created on demand for OpenAI models

    def _is_claude_model(self, model_name: str) -> bool:
        """Check if the model is a Claude model."""
        return "claude" in model_name.lower()

    def _is_openai_model(self, model_name: str) -> bool:
        """Check if the model is an OpenAI model."""
        return "gpt" in model_name.lower() or "openai" in model_name.lower()

    def _get_openai_client(self):
        """Get or create OpenAI client for OpenAI models."""
        if self.client is None:
            openai_url = f"{self.config.base_url.rstrip('/')}/openai/process/v1/"
            self.client = OpenAI(
                api_key="dummy",  # Required by OpenAI client but not used
                base_url=openai_url,
                default_headers={"X-Api-Key": self.config.api_key}
            )
        return self.client

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generate content using the appropriate gateway endpoint.

        Args:
            messages: A list of message dictionaries with 'role' and 'content' keys.
            response_format: A Pydantic model for structured output (OpenAI only).
            **kwargs: Additional keyword arguments.

        Returns:
            The generated content or response object.
        """
        model_name = self.config.model_name

        # Route based on model type
        if self._is_claude_model(model_name):
            return self._generate_claude(messages, response_format, **kwargs)
        if self._is_openai_model(model_name):
            return self._generate_openai(messages, response_format, **kwargs)
        raise ValueError(
            f"Unsupported model type: {model_name}. "
            f"Must be a Claude model (contains 'claude') or OpenAI model (contains 'gpt'/'openai')."
        )

    def _generate_openai(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """Generate using OpenAI endpoint."""
        client = self._get_openai_client()

        # Build completion parameters
        completion_params = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_completion_tokens,
        }

        # Add response format if provided
        if response_format:
            completion_params["response_format"] = response_format

        # Add tools if provided
        if "tools" in kwargs:
            completion_params["tools"] = kwargs["tools"]

        # Add any other kwargs
        for key in ["tool_choice", "parallel_tool_calls"]:
            if key in kwargs:
                completion_params[key] = kwargs[key]

        response = client.chat.completions.create(**completion_params)

        # Return based on whether tools were used
        if "tools" in kwargs:
            return response

        return response.choices[0].message.content

    def _generate_claude(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """Generate using Claude endpoint (mirrors claude_gateway.py logic)."""
        max_retries = kwargs.get("max_retries", 5)
        base_delay = kwargs.get("base_delay", 10.0)

        # Get Claude-specific model config
        model_config = CLAUDE_MODEL_MAP.get(self.config.model_name, {
            "model_name": self.config.model_name,
            "thinking_enabled": False
        })
        claude_model_name = model_config["model_name"]
        thinking_enabled = model_config["thinking_enabled"]

        for attempt in range(max_retries + 1):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'X-Api-Key': self.config.api_key
                }

                system_messages, formatted_messages = [], []
                formatted_messages = self._convert_openai_messages_to_claude(
                    messages, system_messages
                )
                system_message = "\n".join(system_messages)

                if response_format is None:
                    data = {
                        "prompts": formatted_messages,
                        "model_id": claude_model_name,
                        "stream": False,
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_completion_tokens,
                        "system": system_message,
                        "top_p": self.config.top_p,
                        "timeout": int(kwargs.get("timeout", 30))
                    }

                    # Handle thinking parameter
                    if thinking_enabled:
                        data["thinking"] = {
                            "type": "enabled",
                            "budget_tokens": kwargs.get("thinking_budget_tokens",
                            self.config.thinking_budget_tokens)
                        }

                    # Handle tools if provided
                    if 'tools' in kwargs:
                        data['tools'] = self._convert_openai_tools_to_claude(kwargs['tools'])

                    # Remove custom parameters from kwargs before updating data
                    filtered_kwargs = {k: v for k, v in kwargs.items()
                                     if k not in [
                                        'thinking_enabled',
                                        'thinking_budget_tokens',
                                        'tools', 'max_retries',
                                        'base_delay']}
                    data.update(filtered_kwargs)

                    claude_url = f"{self.config.base_url.rstrip('/')}/claude3/process"
                    response = requests.post(
                        claude_url,
                        json=data,
                        headers=headers,
                        timeout=int(kwargs.get("timeout", 30))
                    )

                    response.raise_for_status()
                    response_json = json.loads(response.text)

                    # If tools are provided, return a response object
                    if 'tools' in kwargs:
                        return self._create_openai_style_response(response_json)

                    # For backward compatibility, return just the text content
                    return response_json['result'][0]['text']

                raise NotImplementedError("Research gateway Claude endpoint does not support response_format!")

            except (requests.exceptions.RequestException, requests.exceptions.Timeout,
                    requests.exceptions.HTTPError) as e:
                if attempt == max_retries:
                    logging.warning("All %d attempts failed. Last error: %s", max_retries + 1, e)
                    return None

                delay = base_delay * (2 ** attempt)
                logging.info("Attempt %d failed with error: %s. Retrying in %.1f seconds...",
                           attempt + 1, e, delay)
                time.sleep(delay)

            except Exception as e:  # pylint: disable=broad-exception-caught
                # Catch any non-retryable errors (e.g., authentication, SSL, etc.)
                logging.error("Non-retryable error occurred: %s", e)
                return None

    # Claude message conversion methods (from claude_gateway.py)
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

        if message.get("content"):
            content_blocks.append({
                "type": "text",
                "text": message["content"]
            })

        for tool_call in message["tool_calls"]:
            if tool_call.get("type") == "function":
                func = tool_call["function"]
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

    def _handle_tool_message(self, message: dict) -> dict:
        """Handle tool result message."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message["content"]
                }
            ]
        }

    def _convert_openai_messages_to_claude(
            self,
            messages: List[dict],
            system_messages: List[str]
        ) -> List[dict]:
        """Convert OpenAI format messages to Claude format."""
        claude_messages = []

        for message in messages:
            role = message.get("role")

            if role == "system":
                self._handle_system_message(message, system_messages)
            elif role == "user":
                claude_messages.append(self._handle_user_message(message))
            elif role == "assistant":
                if "tool_calls" in message and message["tool_calls"]:
                    claude_messages.append(self._handle_assistant_message_with_tools(message))
                else:
                    claude_messages.append(self._handle_assistant_message(message))
            elif role == "tool":
                claude_messages.append(self._handle_tool_message(message))

        return claude_messages

    def _convert_openai_tools_to_claude(self, openai_tools: List[dict]) -> List[dict]:
        """Convert OpenAI format tools to Claude format."""
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
        """Create an OpenAI-style response object from Claude's response."""
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

        result_blocks = response_json.get('result', [])
        openai_tool_calls = []
        text_content = ""

        for block in result_blocks:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    text_content += block.get('text', '')
                elif block.get('type') == 'tool_use':
                    tool_id = block.get('id', str(uuid.uuid4()))
                    tool_name = block.get('name', '')
                    tool_input = block.get('input', {})

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

        content = text_content if text_content else None
        tool_calls = openai_tool_calls if openai_tool_calls else None

        message = Message(content=content, tool_calls=tool_calls)
        choice = Choice(message)
        response = Response(choices=[choice], model=self.config.model_name)
        return response

    def support_tool_call(self) -> bool:
        """Return a flag indicating if the model supports function/tool call API."""
        return True

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (URL and API keys).

        Args:
            context: The context containing environment variables.
        """
        super().set_context(context)
        self.config.api_key = context.env.get("SALESFORCE_GATEWAY_KEY", self.config.api_key)
        self.config.base_url = context.env.get("RESEARCH_GATEWAY_URL", self.config.base_url)

        # Reset client to force recreation with new settings
        self.client = None
