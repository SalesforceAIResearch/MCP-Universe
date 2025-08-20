"""
OpenAI LLMs
"""
# pylint: disable=broad-exception-caught
from typing import Dict, Union, Optional, Type, List
from openai import OpenAI, NOT_GIVEN
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.context import Context
from .base import BaseLLM
from .openai import OpenAIConfig

load_dotenv()


class OpenAIAgentModel(BaseLLM):
    """
    OpenAI language models.

    This class provides methods to interact with OpenAI's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[OpenAIConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = OpenAIConfig
    alias = ["openai-agentic", "openai-agent"]
    env_vars = ["OPENAI_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = OpenAIAgentModel.config_class.load(config)

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
        tools = kwargs.get("remote_mcp", [])
        if not tools:
            tools = NOT_GIVEN

        if response_format is None:
            resp = client.responses.create(
                input=messages,
                model=self.config.model_name,
                temperature=self.config.temperature,
                timeout=int(kwargs.get("timeout", 60)),
                top_p=self.config.top_p,
                tools=tools
            )
            return resp.output_text
        raise NotImplementedError("openai-agentic does not support response_format!")

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("OPENAI_API_KEY", self.config.api_key)

    def support_remote_mcp(self) -> bool:
        """
        Return a flag indicating if the model supports remote MCP servers.
        """
        return True
