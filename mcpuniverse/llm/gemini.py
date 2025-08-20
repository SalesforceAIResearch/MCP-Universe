"""
Gemini LLMs
"""
import os
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class GeminiConfig(BaseConfig):
    """
    Configuration for Gemini language models.

    Attributes:
        model_name (str): The name of the Gemini model to use (default: "gemini-2.0-flash").
        api_key (str): The Gemini API key (default: environment variable GEMINI_API_KEY).
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
    """
    model_name: str = "gemini-2.0-flash"
    api_key: str = os.getenv("GEMINI_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 2048
    seed: int = 12345


class GeminiModel(BaseLLM):
    """
    Gemini language models.

    This class provides methods to interact with Gemini's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[GeminiConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = GeminiConfig
    alias = "gemini"
    env_vars = ["GEMINI_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = GeminiModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the Gemini model.

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
        client = genai.Client(api_key=self.config.api_key)
        system_messages, formatted_messages = [], []
        for message in messages:
            if message["role"] == "system":
                system_messages.append(message["content"])
            else:
                formatted_messages.append(message["content"])
        system_message = "\n\n".join(system_messages)

        config = types.GenerateContentConfig(
            http_options=types.HttpOptions(
                timeout=int(kwargs.get("timeout", 30)) * 1000
            ),
            system_instruction=system_message,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            frequency_penalty=self.config.frequency_penalty,
            presence_penalty=self.config.presence_penalty,
            max_output_tokens=self.config.max_completion_tokens,
            seed=self.config.seed,
            response_schema=response_format
        )
        chat = client.models.generate_content(
            model=self.config.model_name,
            config=config,
            contents="\n\n".join(formatted_messages)
        )
        if response_format is None:
            return chat.text
        return chat.parsed

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("GEMINI_API_KEY", self.config.api_key)
