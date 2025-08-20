"""
LLMs supported by Ollama
"""
# pylint: disable=broad-exception-caught
import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List

import requests
from pydantic_core import from_json
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM
from .utils import extract_json_output

load_dotenv()


@dataclass
class OllamaConfig(BaseConfig):
    """
    Configuration for Ollama models.

    Attributes:
        model_name (str): Name of the Ollama model to use. Defaults to "llama3.2".
        ollama_url (str): URL of the Ollama API. Defaults to the value of OLLAMA_URL environment variable.
        temperature (float): Controls randomness in output. Higher values increase randomness. Defaults to 1.0.
        top_p (float): Controls diversity of output. Lower values increase focus on more likely tokens. Defaults to 1.0.
        frequency_penalty (float): Penalizes frequent tokens. Higher values reduce repetition. Defaults to 0.0.
        presence_penalty (float): Penalizes new tokens based on their presence in the text so far. Defaults to 0.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 2048.
        seed (int): Seed for random number generation, ensuring reproducibility. Defaults to 12345.
    """
    model_name: str = "llama3.2"
    ollama_url: str = os.getenv("OLLAMA_URL", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 2048
    seed: int = 12345


class OllamaModel(BaseLLM):
    """
    This class provides an interface to interact with language models supported by Ollama.
    It handles configuration, initialization, and generation of text based on input messages.

    Attributes:
        config_class (Type[OllamaConfig]): Configuration class for Ollama models.
        alias (str): Alias for the Ollama model, used for identification.
    """
    config_class = OllamaConfig
    alias = "ollama"
    env_vars = ["OLLAMA_URL"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initializes the Ollama instance.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the model.
                Can be a dictionary or a string. If None, default configuration is used.
        """
        super().__init__()
        self.config = OllamaModel.config_class.load(config)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generate content based on input messages using the Ollama model.

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
        ollama_url = self.config.ollama_url
        url = ollama_url.strip("/") + "/api/chat"
        if response_format is not None:
            schema = response_format.model_json_schema()["properties"]
            schema = {key: val["title"] for key, val in schema.items()}
            schema = json.dumps(schema)
            messages.append({"role": "user", "content": f"The results must follow this JSON format {schema}"})

        data = {
            "model": self.config.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "seed": self.config.seed,
                "num_predict": self.config.max_completion_tokens,
                "top_p": self.config.top_p,
                "temperature": self.config.temperature,
                "presence_penalty": self.config.presence_penalty,
                "frequency_penalty": self.config.frequency_penalty,
            }
        }
        if response_format is not None:
            data["format"] = "json"

        response = requests.post(url, json=data, timeout=int(kwargs.get("timeout", 30)))
        json_data = json.loads(response.text)
        content = json_data["message"]["content"]
        if response_format is None:
            return content
        try:
            return response_format.model_validate(from_json(content))
        except Exception:
            jsons = extract_json_output(content)
            for d in jsons:
                try:
                    return response_format.model_validate(d)
                except Exception:
                    pass
            self.logger.error("Failed to parse the output:\n%s", content)
            return None

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.ollama_url = context.env.get("OLLAMA_URL", self.config.ollama_url)
