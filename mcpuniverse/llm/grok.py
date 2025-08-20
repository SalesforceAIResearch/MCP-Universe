"""
Gork LLMs
"""
# pylint: disable=broad-exception-caught
import os
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from xai_sdk import Client
from xai_sdk.chat import system, user, assistant
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class GrokConfig(BaseConfig):
    """
    Configuration for xAI language models.

    Attributes:
        model_name (str): The name of the Grok model to use (default: "grok-3").
        api_key (str): The xAI API key (default: environment variable XAI_API_KEY).
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
    """
    model_name: str = "grok-4"
    api_key: str = os.getenv("XAI_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 2048
    seed: int = 12345


class GrokModel(BaseLLM):
    """
    Grok language models.

    This class provides methods to interact with xAI's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[GrokConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = GrokConfig
    alias = "grok"
    env_vars = ["XAI_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = GrokModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the Grok model.

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
        client = Client(api_key=self.config.api_key)
        grok_messages = []
        for message in messages:
            if message["role"] == "system":
                grok_messages.append(system(message["content"]))
            elif message["role"] == "user":
                grok_messages.append(user(message["content"]))
            elif message["role"] == "assistant":
                grok_messages.append(assistant(message["content"]))
            else:
                raise ValueError(f"Unsupported message role: {message['role']}")

        if response_format is None:
            chat = client.chat.create(
                model=self.config.model_name,
                messages=grok_messages,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                # frequency_penalty=self.config.frequency_penalty,   # Not supported by Grok-4
                # presence_penalty=self.config.presence_penalty,     # Not supported by Grok-4
                max_tokens=self.config.max_completion_tokens,
                seed=self.config.seed
            )
            response = chat.sample()
            return response.content
        raise NotImplementedError("Grok does not support response_format!")

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("XAI_API_KEY", self.config.api_key)
