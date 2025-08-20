"""
Anthropic LLMs
"""
# pylint: disable=broad-exception-caught
import os
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class ClaudeConfig(BaseConfig):
    """
    Configuration for Claude models.

    Attributes:
        model_name (str): The name of the Claude model to use. Defaults to "claude-3-5-sonnet-20241022".
        api_key (str): The Anthropic API key. Defaults to the value of the ANTHROPIC_API_KEY environment variable.
        temperature (float): Controls randomness in output generation. Defaults to 1.0.
        top_p (float): Controls diversity of output generation. Defaults to 1.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 2048.
    """
    model_name: str = "claude-3-5-sonnet-20241022"
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    max_completion_tokens: int = 2048


class ClaudeModel(BaseLLM):
    """
    A class for interacting with Anthropic's Claude language models.

    This class provides methods to generate content using Claude models,
    supporting both free-form text generation and structured output based
    on Pydantic models.

    Attributes:
        config_class (Type[ClaudeConfig]): The configuration class for Claude models.
        alias (str): A short name for the model, set to "claude".
    """
    config_class = ClaudeConfig
    alias = "claude"
    env_vars = ["ANTHROPIC_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize the ClaudeModel instance.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the model.
                Can be a dictionary or a string. If None, default configuration will be used.
        """
        super().__init__()
        self.config = ClaudeModel.config_class.load(config)
        self.logger = get_logger(self.__class__.__name__)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generate content using the Claude model.

        Args:
            messages (List[dict[str, str]]): A list of message dictionaries,
                each containing 'role' and 'content' keys.
            response_format (Type[PydanticBaseModel], optional): A Pydantic model
                defining the structure of the desired output. If None, free-form
                text will be generated.
            **kwargs: Additional keyword arguments to pass to the Anthropic API.

        Returns:
            Union[str, PydanticBaseModel, None]: The generated content as a string
                if no response_format is provided, a Pydantic model instance if a
                response_format is provided, or None if parsing the structured output fails.
        """
        client = anthropic.Anthropic(api_key=self.config.api_key)
        system_messages, formatted_messages = [], []
        for message in messages:
            if message["role"] == "system":
                system_messages.append(message["content"])
            else:
                formatted_messages.append(message)
        system_message = "\n".join(system_messages)

        if response_format is None:
            chat = client.messages.create(
                model=self.config.model_name,
                max_tokens=self.config.max_completion_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                timeout=int(kwargs.get("timeout", 30)),
                system=system_message,
                messages=formatted_messages,
                **kwargs
            )
            return chat.content[0].text

        schema = response_format.model_json_schema()
        chat = client.messages.create(
            model=self.config.model_name,
            max_tokens=self.config.max_completion_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            timeout=int(kwargs.get("timeout", 30)),
            system=system_message,
            messages=formatted_messages,
            tools=[
                {
                    "name": "revise_output",
                    "description": "Revise an output using well-structured JSON.",
                    "input_schema": schema
                }
            ],
            tool_choice={"type": "tool", "name": "revise_output"},
            **kwargs
        )
        try:
            return response_format.model_validate(chat.content[0].input)
        except Exception:
            self.logger.error("Failed to parse the output:\n%s", str(chat.content[0].input))
            return None

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("ANTHROPIC_API_KEY", self.config.api_key)
