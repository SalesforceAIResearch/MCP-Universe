"""
Mistral LLMs
"""
# pylint: disable=broad-exception-caught
import os
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from dotenv import load_dotenv
from pydantic_core import from_json
from mistralai import Mistral
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class MistralConfig(BaseConfig):
    """
    Configuration for Mistral language models.

    Attributes:
        model_name (str): Name of the Mistral model to use. Default is "mistral-large-latest".
        api_key (str): Mistral API key. Retrieved from MISTRAL_API_KEY environment variable.
        temperature (float): Controls randomness in output generation. Default is 1.0.
        top_p (float): Controls diversity of output generation. Default is 1.0.
        frequency_penalty (float): Reduces repetition of token sequences. Default is 0.0.
        presence_penalty (float): Encourages the model to talk about new topics. Default is 0.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Default is 2048.
        seed (int): Seed for deterministic output generation. Default is 12345.

    Note:
        For more information on available models, see:
        https://docs.mistral.ai/getting-started/models/models_overview/
    """
    model_name: str = "mistral-large-latest"  # mistral-large-latest, codestral-latest, open-mistral-nemo
    api_key: str = os.getenv("MISTRAL_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 2048
    seed: int = 12345


class MistralModel(BaseLLM):
    """
    Interacts with Mistral language models.

    This class provides methods for generating content using Mistral models,
    supporting both free-form text and structured output based on Pydantic models.

    Attributes:
        config_class (Type[MistralConfig]): Configuration class for Mistral models.
        alias (str): Short name for the model, set to "mistral".
    """
    config_class = MistralConfig
    alias = "mistral"
    env_vars = ["MISTRAL_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initializes the MistralModel instance.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the model.
                Can be a dictionary or a string. If None, default configuration is used.
        """
        super().__init__()
        self.config = MistralModel.config_class.load(config)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the Mistral model.

        Args:
            messages (List[dict[str, str]]): List of message dictionaries,
                each containing 'role' and 'content' keys.
            response_format (Type[PydanticBaseModel], optional): Pydantic model
                defining the structure of the desired output. If None, generates
                free-form text.
            **kwargs: Additional keyword arguments for the Mistral API.

        Returns:
            Union[str, PydanticBaseModel, None]: Generated content as a string
                if no response_format is provided, a Pydantic model instance if
                response_format is provided, or None if parsing structured output fails.
        """
        client = Mistral(api_key=self.config.api_key)
        if response_format is None:
            chat = client.chat.complete(
                model=self.config.model_name,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_tokens=self.config.max_completion_tokens,
                random_seed=self.config.seed,
                presence_penalty=self.config.presence_penalty,
                frequency_penalty=self.config.frequency_penalty,
                timeout_ms=int(kwargs.get("timeout", 30)) * 1000,
                messages=messages,
                **kwargs
            )
            return chat.choices[0].message.content

        chat = client.chat.complete(
            model=self.config.model_name,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            max_tokens=self.config.max_completion_tokens,
            random_seed=self.config.seed,
            presence_penalty=self.config.presence_penalty,
            frequency_penalty=self.config.frequency_penalty,
            timeout_ms=int(kwargs.get("timeout", 30)) * 1000,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs
        )
        try:
            return response_format.model_validate(from_json(chat.choices[0].message.content))
        except Exception:
            try:
                text = chat.choices[0].message.content.replace("\n", "\\n")
                return response_format.model_validate(from_json(text))
            except Exception:
                pass
            self.logger.error("Failed to parse the output:\n%s", str(chat.choices[0].message.content))
            return None

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("MISTRAL_API_KEY", self.config.api_key)
