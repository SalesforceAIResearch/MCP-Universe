"""
Running Local LLMs with vLLM
"""
# pylint: disable=broad-exception-caught
import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from openai import RateLimitError, APIError, APITimeoutError
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

import requests

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()

@dataclass
class VLLMLocalConfig(BaseConfig):
    """
    Configuration for VLLM Local language models.

    Attributes:
        model_name (str): The name of the model to use (default: "gpt-oss-20b").
        api_key (str): The API key (default: environment variable VLLM_API_KEY).
        base_url (str): The base URL of the vLLM API (default: "http://localhost:2024/v1").
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
        reasoning (str): Reasoning level (default: "high").
    """
    model_name: str = "gpt-oss-120b"
    api_key: str = os.environ.get("VLLM_API_KEY", "token-abc123")
    base_url: str = os.environ.get("VLLM_BASE_URL", "http://localhost:2024")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 20000
    seed: int = 12345
    reasoning: str = "high"


class VLLMLocalModel(BaseLLM):
    """
    Running Local LLMs with vLLM.

    This class provides methods to interact with Local LLMs with vLLM,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[VLLMLocalConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = VLLMLocalConfig
    alias = "vllm_local"
    env_vars = ["VLLM_API_KEY", "VLLM_BASE_URL"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = VLLMLocalModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):  # pylint: disable=too-many-return-statements
        """
        Generates content using the vLLM Local model.

        Args:
            messages (List[dict[str, str]]): List of message dictionaries,
                each containing 'role' and 'content' keys.
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
        unused_response_format = response_format

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    f"{self.config.base_url}/v1/completions",
                    json={
                        "model": self.config.model_name,
                        "prompt": messages[0]['content'],
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_completion_tokens,
                        "top_p": self.config.top_p,
                        "frequency_penalty": self.config.frequency_penalty,
                        "presence_penalty": self.config.presence_penalty,
                        "seed": self.config.seed,
                        "use_beam_search": False,
                        "skip_special_tokens": False,
                    },
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=int(kwargs.get("timeout", 60))
                )
                response.raise_for_status()
                response = response.json()["choices"][0]["text"]
                return response

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
        self.config.api_key = context.env.get("VLLM_API_KEY", self.config.api_key)
        self.config.base_url = context.env.get("VLLM_BASE_URL", self.config.base_url)
