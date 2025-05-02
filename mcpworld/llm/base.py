"""
Provides the base class for LLMs.

This module defines the BaseLLM class, which serves as a foundation for
implementing various LLM models. It includes abstract methods and utility
functions for generating content, handling messages, and managing configurations.
"""
from abc import abstractmethod
from typing import Any, List, Dict
from pydantic import BaseModel
from mcpworld.common.misc import ComponentABCMeta, ExportConfigMixin
from mcpworld.tracer import Tracer


class BaseLLM(ExportConfigMixin, metaclass=ComponentABCMeta):
    """
    Base class for LLMs.

    This abstract base class defines the interface and common functionality
    for LLM implementations. It includes methods for generating content,
    handling messages, and managing configurations.

    Attributes:
        config: Configuration settings for the LLM.
    """

    @abstractmethod
    def _generate(self, messages: List[dict[str, str]], **kwargs) -> Any:
        """Generates content based on formatted messages.

        This abstract method must be implemented by subclasses to define the
        specific content generation logic for each LLM type.

        Args:
            messages (List[dict[str, str]]): A list of message dictionaries,
                each containing 'role' and 'content' keys.
            **kwargs: Additional keyword arguments for model-specific parameters.

        Returns:
            Any: The generated content or model response.
        """
        raise NotImplementedError("`Generate` must be implemented by a subclass.")

    def generate(self, messages: List[dict[str, str]], tracer: Tracer = None, **kwargs) -> Any:
        """
        Generates content based on formatted messages with tracing support.

        This method wraps the _generate method, adding tracing functionality
        and error handling.

        Args:
            messages (List[dict[str, str]]): A list of message dictionaries,
                each containing 'role' and 'content' keys.
            tracer (Tracer, optional): Tracer object for tracking model outputs.
                If None, a new Tracer will be created.
            **kwargs: Additional keyword arguments for model-specific parameters.

        Returns:
            Any: The generated content or model response.

        Raises:
            Exception: If an error occurs during content generation.
        """
        tracer = tracer if tracer else Tracer()
        with tracer.sprout() as t:
            try:
                response = self._generate(messages, **kwargs)
                t.add({
                    "type": "llm",
                    "class": self.__class__.__name__,
                    "config": self.config.to_dict(),
                    "messages": messages,
                    "response": response.model_dump(mode="json")
                    if isinstance(response, BaseModel) else response,
                    "error": ""
                })
            except Exception as e:
                t.add({
                    "type": "llm",
                    "class": self.__class__.__name__,
                    "config": self.config.to_dict(),
                    "messages": messages,
                    "response": "",
                    "error": str(e)
                })
                raise e
        return response

    def get_response(
            self,
            system_message: str,
            user_message: str,
            tracer: Tracer = None,
            **kwargs
    ):
        """
        Generates content based on system and user messages.

        Args:
            system_message (str): The system message providing context or instructions.
            user_message (str): The user's input or query.
            tracer (Tracer, optional): Tracer object for tracking model outputs.
            **kwargs: Additional keyword arguments for model-specific parameters.

        Returns:
            Any: The generated content or model response.
        """
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]
        return self.generate(messages, tracer=tracer, **kwargs)

    def dump_config(self) -> Dict[str, Any]:
        """
        Returns a dictionary representation of the LLM configuration.

        Returns:
            Dict[str, Any]: A dictionary containing the LLM class name and configuration.
        """
        return {
            "class": self.__class__.__name__,
            "config": self.config.to_dict()
        }
