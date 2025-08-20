"""
OpenAI LLMs
"""
# pylint: disable=broad-exception-caught
import os
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class OpenAIConfig(BaseConfig):
    """
    Configuration for OpenAI language models.

    Attributes:
        model_name (str): The name of the OpenAI model to use (default: "gpt-4o").
        api_key (str): The OpenAI API key (default: environment variable OPENAI_API_KEY).
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
    """
    model_name: str = "gpt-4o"
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 2048
    seed: int = 12345


class OpenAIModel(BaseLLM):
    """
    OpenAI language models.

    This class provides methods to interact with OpenAI's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[OpenAIConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = OpenAIConfig
    alias = "openai"
    env_vars = ["OPENAI_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = OpenAIModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the OpenAI model.

        Args:
            messages (List[dict[str, str]]): List of message dictionaries,
                each containing 'role' and 'content' keys.
            response_format (Type[PydanticBaseModel], optional): Pydantic model
                defining the structure of the desired output. If None, generates
                free-form text.
            **kwargs: Additional keyword arguments.

        Returns:
            Union[str, PydanticBaseModel, None]: Generated content as a string
                if no response_format is provided, a Pydantic model instance if
                response_format is provided, or None if parsing structured output fails.
        """
        client = OpenAI(api_key=self.config.api_key)
        if response_format is None:
            chat = client.chat.completions.create(
                messages=messages,
                model=self.config.model_name,
                temperature=self.config.temperature,
                timeout=int(kwargs.get("timeout", 30)),
                top_p=self.config.top_p,
                frequency_penalty=self.config.frequency_penalty,
                presence_penalty=self.config.presence_penalty,
                seed=self.config.seed,
                **kwargs
            )
            return chat.choices[0].message.content

        chat = client.beta.chat.completions.parse(
            messages=messages,
            model=self.config.model_name,
            temperature=self.config.temperature,
            timeout=int(kwargs.get("timeout", 30)),
            top_p=self.config.top_p,
            frequency_penalty=self.config.frequency_penalty,
            presence_penalty=self.config.presence_penalty,
            seed=self.config.seed,
            response_format=response_format,
            **kwargs
        )
        return chat.choices[0].message.parsed

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("OPENAI_API_KEY", self.config.api_key)
