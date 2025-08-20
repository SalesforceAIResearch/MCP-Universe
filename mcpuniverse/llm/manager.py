"""
Manages and builds Large Language Models (LLMs).

This module provides a ModelManager class for creating and managing
various LLM clients, such as GPT-4 and Claude 3.
"""
# pylint: disable=too-few-public-methods
from typing import Dict, Union
from mcpuniverse.common.misc import BaseBuilder, ComponentABCMeta


class ModelManager(BaseBuilder):
    """
    Manages and builds Large Language Model (LLM) clients.

    This class provides functionality to create and manage various LLM clients,
    such as GPT-4 and Claude 3, based on provided configurations.

    Attributes:
        _MODELS: A dictionary of available LLM classes.
        _classes: A dictionary mapping model names to their respective classes.
    """
    _MODELS = ComponentABCMeta.get_class("llm")

    def __init__(self):
        super().__init__()
        self._classes = self._name_to_class(ModelManager._MODELS)

    def build_model(self, name: str, config: Union[Dict, str] = None):
        """
        Builds and returns an LLM client based on the specified name and configuration.

        Args:
            name (str): The name or alias of the LLM class to instantiate.
            config (Union[Dict, str], optional): Configuration for the model.
                Can be a dictionary of parameters or a string path to a config file.

        Returns:
            An instantiated LLM client.
        """
        assert name in self._classes, f"Model {name} is not found. Please choose models from {self._classes.keys()}"
        return self._classes[name](config)
