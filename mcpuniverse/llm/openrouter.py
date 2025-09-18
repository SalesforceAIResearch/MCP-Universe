"""
OpenRouter LLMs
"""
# pylint: disable=broad-exception-caught
import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from openai import OpenAI
from openai import RateLimitError, APIError, APITimeoutError
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()

model_name_map = {
    "Qwen3Coder_OR": "qwen/qwen3-coder",
    "GrokCoderFast1_OR": "x-ai/grok-code-fast-1",
    "GPTOSS120B_OR": "openai/gpt-oss-120b",
    "GPTOSS20B_OR": "openai/gpt-oss-20b",
    "DeepSeekV3_1_OR": "deepseek/deepseek-chat-v3.1",
    "GLM4_5_OR": "z-ai/glm-4.5",
    "GLM4_5_AIR_OR": "z-ai/glm-4.5-air",
    "KimiK2_OR": "moonshotai/kimi-k2"
}

@dataclass
class OpenRouterConfig(BaseConfig):
    """
    Configuration for OpenRouter language models.

    Attributes:
        model_name (str): The name of the OpenRouter model to use (default: "GPTOSS120B_OR").
        api_key (str): The OpenRouter API key (default: environment variable OPENROUTER_API_KEY).
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
        reasoning (str): Reasoning level (default: "high").
    """
    model_name: str = "KimiK2_OR"
    api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 100000
    seed: int = 12345
    reasoning: str = "high"


class OpenRouterModel(BaseLLM):
    """
    OpenRouter language models.

    This class provides methods to interact with OpenRouter's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[OpenRouterConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = OpenRouterConfig
    alias = "openrouter"
    env_vars = ["OPENROUTER_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = OpenRouterModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]] = None,
            prompt: str = None,
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the OpenRouter model.

        Args:
            messages (List[dict[str, str]]): List of message dictionaries,
                each containing 'role' and 'content' keys.
            prompt (str): Raw prompt, only if messages is None, needs to handle the format yourself.
            response_format (Type[PydanticBaseModel], optional): Pydantic model
                defining the structure of the desired output. If None, generates
                free-form text.
            **kwargs: Additional keyword arguments including:
                - max_retries (int): Maximum number of retry attempts (default: 5)
                - base_delay (float): Base delay in seconds for exponential backoff (default: 10.0)
                - timeout (int): Request timeout in seconds (default: 60)

        Returns:
            Union[str, PydanticBaseModel, None]: Generated content as a string
                if no response_format is provided, a Pydantic model instance if
                response_format is provided, or None if parsing structured output fails.
                Returns None if all retry attempts fail or non-retryable errors occur.
        """
        max_retries = kwargs.get("max_retries", 5)
        base_delay = kwargs.get("base_delay", 10.0)
        # Map model name to OpenRouter model name
        model_name = model_name_map.get(self.config.model_name, self.config.model_name)

        if messages is None and prompt is None:
            raise ValueError("messages or prompt must be provided")

        for attempt in range(max_retries + 1):
            try:
                client = OpenAI(api_key=self.config.api_key, base_url="https://openrouter.ai/api/v1")
                if response_format is None:
                    if prompt is not None:
                        chat = client.completions.create(
                            prompt=prompt,
                            model=model_name,
                            temperature=self.config.temperature,
                            # max_tokens=self.config.max_completion_tokens,
                            timeout=int(kwargs.get("timeout", 60)),
                            top_p=self.config.top_p,
                            frequency_penalty=self.config.frequency_penalty,
                            presence_penalty=self.config.presence_penalty,
                            seed=self.config.seed,
                        )
                        return chat.choices[0].text
                    else:         
                        chat = client.chat.completions.create(
                            messages=messages,
                            model=model_name,
                            temperature=self.config.temperature,
                            # max_tokens=self.config.max_completion_tokens,
                            timeout=int(kwargs.get("timeout", 60)),
                            top_p=self.config.top_p,
                            frequency_penalty=self.config.frequency_penalty,
                            presence_penalty=self.config.presence_penalty,
                            seed=self.config.seed,
                            **kwargs
                        )
                    
                    # If tools are provided, return the entire response object
                    # so the caller can handle both content and tool_calls
                    if 'tools' in kwargs:
                        return chat
                    # For backward compatibility, return just content when no tools
                    return chat.choices[0].message.content

                chat = client.beta.chat.completions.parse(
                    messages=messages,
                    model=model_name,
                    temperature=self.config.temperature,
                    timeout=int(kwargs.get("timeout", 60)),
                    top_p=self.config.top_p,
                    frequency_penalty=self.config.frequency_penalty,
                    presence_penalty=self.config.presence_penalty,
                    seed=self.config.seed,
                    response_format=response_format,
                    **kwargs
                )
                # If tools are provided, return the entire response object
                # so the caller can handle both content and tool_calls
                if 'tools' in kwargs:
                    return chat
                # For backward compatibility, return just parsed content when no tools
                return chat.choices[0].message.parsed

            except (RateLimitError, APIError, APITimeoutError) as e:
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
                return None

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("OPENROUTER_API_KEY", self.config.api_key)
