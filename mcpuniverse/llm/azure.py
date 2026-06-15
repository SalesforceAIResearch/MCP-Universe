"""
Azure OpenAI LLM provider.

Uses the official AzureOpenAI client. Configure via environment variables:
    - AZURE_API_KEY
    - AZURE_API_BASE (Azure resource endpoint URL)
    - AZURE_API_VERSION (optional, defaults to 2024-12-01-preview)

In YAML configs, set type: azure and model_name to your Azure deployment name.
"""
# pylint: disable=broad-exception-caught
import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List

from openai import AzureOpenAI
from openai import RateLimitError, APIError, APITimeoutError
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.context import Context
from .openai import OpenAIModel, OpenAIConfig

load_dotenv()

DEFAULT_AZURE_API_VERSION = "2024-12-01-preview"

_RETRYABLE_API_STATUS_CODES = {429, 500, 502, 503, 504}


def _normalize_azure_endpoint(endpoint: str) -> str:
    """Strip trailing slashes from the Azure endpoint URL."""
    return endpoint.rstrip("/") if endpoint else endpoint


@dataclass
class AzureOpenAIConfig(OpenAIConfig):
    """
    Configuration for Azure OpenAI language models.

    Attributes:
        api_key (str): From AZURE_API_KEY.
        azure_endpoint (str): From AZURE_API_BASE.
        api_version (str): From AZURE_API_VERSION, default 2024-12-01-preview.
        model_name (str): Azure deployment name (passed to the API as model).
    """
    api_key: str = os.getenv("AZURE_API_KEY", "")
    azure_endpoint: str = os.getenv("AZURE_API_BASE", "")
    api_version: str = os.getenv("AZURE_API_VERSION", DEFAULT_AZURE_API_VERSION)


class AzureOpenAIModel(OpenAIModel):
    """
    Azure OpenAI language models.

    Subclasses OpenAIModel for shared config shape and overrides _generate to use
    AzureOpenAI instead of OpenAI.
    """
    config_class = AzureOpenAIConfig
    alias = "azure"
    env_vars = ["AZURE_API_KEY", "AZURE_API_BASE"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super(OpenAIModel, self).__init__()
        self.config = AzureOpenAIModel.config_class.load(config)
        self.config.azure_endpoint = _normalize_azure_endpoint(self.config.azure_endpoint)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        max_retries = kwargs.pop("max_retries", 5)
        base_delay = kwargs.pop("base_delay", 10.0)

        for attempt in range(max_retries + 1):
            try:
                client = AzureOpenAI(
                    api_version=self.config.api_version,
                    azure_endpoint=self.config.azure_endpoint,
                    api_key=self.config.api_key,
                )
                # model_name is the Azure deployment name — never rewrite it.
                # reasoning_effort: pass via caller kwargs when the deployment supports it.

                if response_format is None:
                    params = {
                        "messages": messages,
                        "model": self.config.model_name,
                        "temperature": self.config.temperature,
                        "top_p": self.config.top_p,
                        "frequency_penalty": self.config.frequency_penalty,
                        "presence_penalty": self.config.presence_penalty,
                        "max_completion_tokens": self.config.max_completion_tokens,
                        "seed": self.config.seed,
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
                    "frequency_penalty": self.config.frequency_penalty,
                    "presence_penalty": self.config.presence_penalty,
                    "max_completion_tokens": self.config.max_completion_tokens,
                    "seed": self.config.seed,
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
                status_code = getattr(e, "status_code", None)
                if isinstance(e, APIError) and status_code not in _RETRYABLE_API_STATUS_CODES:
                    logging.error("Non-retryable API error occurred: %s", e)
                    return None

                if attempt == max_retries:
                    logging.warning("All %d attempts failed. Last error: %s", max_retries + 1, e)
                    return None

                delay = base_delay * (2 ** attempt)
                logging.info("Attempt %d failed with error: %s. Retrying in %.1f seconds...",
                           attempt + 1, e, delay)
                time.sleep(delay)

            except Exception as e:
                logging.error("Non-retryable error occurred: %s", e)
                return None

    def set_context(self, context: Context):
        """Refresh Azure credentials and endpoint from runtime environment."""
        super().set_context(context)
        self.config.api_key = context.env.get("AZURE_API_KEY", self.config.api_key)
        endpoint = context.env.get("AZURE_API_BASE", self.config.azure_endpoint)
        self.config.azure_endpoint = _normalize_azure_endpoint(endpoint)
        self.config.api_version = context.env.get(
            "AZURE_API_VERSION",
            self.config.api_version or DEFAULT_AZURE_API_VERSION,
        )
