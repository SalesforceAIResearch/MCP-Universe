"""
Salesforce LLM Express Gateway Provider

This provider routes requests through the Salesforce Engineering AI Model Gateway
using an OpenAI-compatible API format. It supports any model available
through the gateway (Claude, OpenAI, etc.).

Configuration:
    Both the gateway URL and API key must be set via environment variables
    to maintain security and avoid exposing internal infrastructure in the codebase.

    Required environment variables:
        - ENG_AI_MODEL_GW_URL: Gateway endpoint URL (e.g., "https://your-gateway.example.com")
        - ENG_AI_MODEL_GW_KEY: Your gateway API key

    Example usage:
        export ENG_AI_MODEL_GW_URL="https://your-gateway.example.com"
        export ENG_AI_MODEL_GW_KEY="your-api-key"

        # Then use in your code or with mcp-build-plus:
        mcp-build-plus --mcp-config ~/.cursor/mcp.json \
            --llm-provider sf_llm_express_gateway \
            --llm-model gpt-5-mini \
            --llm-api-key-env ENG_AI_MODEL_GW_KEY
"""
import os
import time
import logging

from openai import OpenAI, RateLimitError, APIError, APITimeoutError

from mcpuniverse.common.context import Context
from .openai import OpenAIModel, OpenAIConfig


class SFLLMExpressGatewayConfig(OpenAIConfig):
    """
    Configuration for Salesforce LLM Express Gateway.

    Both the gateway URL and API key should be set via environment variables
    to avoid exposing internal infrastructure details in the codebase.

    Required environment variables:
        - ENG_AI_MODEL_GW_URL: The gateway endpoint URL (e.g., "https://your-gateway.example.com")
        - ENG_AI_MODEL_GW_KEY: The gateway API key

    Attributes:
        base_url (str): The gateway endpoint URL from ENG_AI_MODEL_GW_URL environment variable.
        model_name (str): The model to use. Defaults to "gpt-5-mini".
        api_key (str): The gateway API key from ENG_AI_MODEL_GW_KEY environment variable.
        temperature (float): Controls randomness in output generation. Defaults to 0.0.
        top_p (float): Controls diversity of output generation. Defaults to 1.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 10000.
    """
    base_url: str = os.getenv("ENG_AI_MODEL_GW_URL", "")
    model_name: str = "gpt-5-mini"
    api_key: str = os.getenv("ENG_AI_MODEL_GW_KEY", "")
    temperature: float = 0.0
    top_p: float = 1.0
    max_completion_tokens: int = 10000


class SFLLMExpressGatewayModel(OpenAIModel):
    """
    LLM provider for Salesforce LLM Express Gateway.

    This class extends OpenAIModel since the gateway uses an OpenAI-compatible API.
    It routes requests through the Salesforce Engineering AI Model Gateway, supporting
    any model available on the gateway (Claude, OpenAI, etc.).

    The gateway provides:
    - Centralized billing and rate limiting
    - Support for multiple model providers
    - Enterprise-grade security and compliance

    Attributes:
        config_class: The configuration class.
        alias: Short name "sf_llm_express_gateway".
        env_vars: Required environment variables.
    """
    config_class = SFLLMExpressGatewayConfig
    alias = "sf_llm_express_gateway"
    env_vars = ["ENG_AI_MODEL_GW_URL", "ENG_AI_MODEL_GW_KEY"]

    def _generate(self, messages, response_format=None, **kwargs):
        """
        Override parent _generate for gateway-specific behavior.

        Key differences from parent:
        1. Skips reasoning_effort parameter (LiteLLM proxy validates strictly)
        2. Re-raises non-retryable errors instead of returning None

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys.
            response_format: Optional Pydantic model for structured output.
            **kwargs: Additional keyword arguments.

        Returns:
            Generated content or response object.

        Raises:
            Exception: Re-raises non-retryable errors for visibility.
        """
        max_retries = kwargs.get("max_retries", 5)
        base_delay = kwargs.get("base_delay", 10.0)

        for attempt in range(max_retries + 1):
            try:
                client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)

                # Don't add reasoning_effort for gateway models - the LiteLLM proxy
                # has stricter parameter validation than direct OpenAI API

                if response_format is None:
                    params = {
                        "messages": messages,
                        "model": self.config.model_name,
                        "temperature": self.config.temperature,
                        "top_p": self.config.top_p,
                        "max_completion_tokens": self.config.max_completion_tokens,
                        "timeout": self.config.timeout,
                    }
                    if 'tools' in kwargs:
                        params["parallel_tool_calls"] = self.config.parallel_tool_calls
                    params.update(kwargs)
                    chat = client.chat.completions.create(**params)
                    if 'tools' in kwargs:
                        return chat
                    return chat.choices[0].message.content

                params = {
                    "messages": messages,
                    "model": self.config.model_name,
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "max_completion_tokens": self.config.max_completion_tokens,
                    "response_format": response_format,
                }
                if 'tools' in kwargs:
                    params["parallel_tool_calls"] = self.config.parallel_tool_calls
                params.update(kwargs)
                chat = client.beta.chat.completions.parse(**params)
                if 'tools' in kwargs:
                    return chat
                return chat.choices[0].message.parsed

            except (RateLimitError, APIError, APITimeoutError) as e:
                # These are retryable errors
                if attempt == max_retries:
                    logging.warning("All %d attempts failed. Last error: %s", max_retries + 1, e)
                    return None

                delay = base_delay * (2 ** attempt)
                logging.info("Attempt %d failed with error: %s. Retrying in %.1f seconds...",
                           attempt + 1, e, delay)
                time.sleep(delay)

            except Exception as e:
                # Non-retryable errors - re-raise so they're visible
                logging.error("Non-retryable error occurred: %s", e)
                raise

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (URL and API keys).

        Args:
            context: The context containing environment variables.
        """
        super().set_context(context)
        # Update config values from environment
        self.config.api_key = context.env.get("ENG_AI_MODEL_GW_KEY", self.config.api_key)
        self.config.base_url = context.env.get("ENG_AI_MODEL_GW_URL", self.config.base_url)
        # No need to create client here - OpenAIModel._generate() creates it using these config values
