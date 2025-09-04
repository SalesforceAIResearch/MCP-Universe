"""
Anthropic LLMs
"""
# pylint: disable=broad-exception-caught
import os
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List

import json
import requests
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class ClaudeGatewayConfig(BaseConfig):
    """
    Configuration for Claude models.

    Attributes:
        model_url (str): The Salesforce gateway url.
        model_name (str): The name of the Claude model to use. Defaults to "claude-3-5-sonnet-20241022".
        api_key (str): The Salesforce gateway API key. Defaults to the value of the SALESFORCE_GATEWAY_KEY
            environment variable.
        temperature (float): Controls randomness in output generation. Defaults to 1.0.
        top_p (float): Controls diversity of output generation. Defaults to 1.0.
        max_completion_tokens (int): Maximum number of tokens to generate. Defaults to 2048.
    """
    model_url: str = "https://gateway.salesforceresearch.ai/claude3/process"
    # Models: us.anthropic.claude-3-7-sonnet-20250219-v1:0, anthropic.claude-3-5-sonnet-20241022-v2:0
    model_name: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    api_key: str = os.getenv("SALESFORCE_GATEWAY_KEY", "")
    temperature: float = 0.0
    top_p: float = 1.0
    max_completion_tokens: int = 10000


class ClaudeGatewayModel(BaseLLM):
    """
    This class provides methods to generate content using Claude models.

    Attributes:
        config_class (Type[ClaudeConfig]): The configuration class for Claude models.
        alias (str): A short name for the model, set to "claude".
    """
    config_class = ClaudeGatewayConfig
    alias = "claude_gateway"
    env_vars = ["SALESFORCE_GATEWAY_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize the ClaudeGatewayModel instance.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the model.
                Can be a dictionary or a string. If None, default configuration will be used.
        """
        super().__init__()
        self.config = ClaudeGatewayModel.config_class.load(config)
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
                text will be generated (Not supported yet).
            **kwargs: Additional keyword arguments to pass to the Anthropic API.

        Returns: The generated content.
        """
        headers = {
            'Content-Type': 'application/json',
            'X-Api-Key': self.config.api_key
        }
        system_messages, formatted_messages = [], []
        for message in messages:
            if message["role"] == "system":
                system_messages.append(message["content"])
            else:
                formatted_messages.append(message)
        system_message = "\n".join(system_messages)

        if response_format is None:
            data = {
                "prompts": formatted_messages,
                "model_id": self.config.model_name,
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_completion_tokens,
                "system": system_message,
                "top_p": self.config.top_p,
                "timeout": int(kwargs.get("timeout", 30)),
            }
            data.update(kwargs)
            response = requests.post(
                self.config.model_url,
                json=data,
                headers=headers,
                timeout=int(kwargs.get("timeout", 30))
            )
            return json.loads(response.text)['result'][0]['text']
        raise NotImplementedError("claude gateway does not support response_format!")

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("SALESFORCE_GATEWAY_KEY", self.config.api_key)
