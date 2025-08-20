"""
This module provides the AgentManager class for managing and creating various types of agents in the MCP world.

The AgentManager allows for dynamic creation of different agent types, such as function calling agents or ReAct agents,
based on their class names or aliases. It also provides functionality to list available agent types.
"""
# pylint: disable=too-few-public-methods
from typing import Dict, Optional, List
from mcpuniverse.common.misc import BaseBuilder, ComponentABCMeta
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import BaseAgent


class AgentManager(BaseBuilder):
    """
    A manager class for creating and managing various types of agents.

    This class provides methods to:
    1. Build agents of different types based on their class names or aliases.
    2. List available agent types.

    Agents can be customized with different configurations, MCP managers, and language models.
    """

    _AGENTS = ComponentABCMeta.get_class("agent")

    def __init__(self):
        super().__init__()
        self._classes = self._name_to_class(AgentManager._AGENTS)

    def build_agent(
            self,
            class_name: str,
            mcp_manager: Optional[MCPManager] = None,
            llm: Optional[BaseLLM] = None,
            config: Optional[str | Dict] = None,
            **kwargs
    ) -> BaseAgent:
        """
        Create and return an agent instance of the specified type.

        Args:
            class_name (str): The name or alias of the agent class to instantiate.
            mcp_manager (Optional[MCPManager]): An MCP server manager instance. May be required for some agent types.
            llm (Optional[BaseLLM]): A language model instance. May be required for some agent types.
            config (Optional[Union[str, Dict]]): Configuration for the agent, either as a string or a dictionary.
            **kwargs: Additional keyword arguments to pass to the agent constructor.

        Returns:
            BaseAgent: An instance of the specified agent class.

        Raises:
            ValueError: If the specified agent class is not found in the available agents.
        """
        if class_name not in self._classes:
            raise ValueError(f"Agent {class_name} is not found. "
                             f"Please choose agent from {list(self._classes.keys())}")
        return self._classes[class_name](mcp_manager=mcp_manager, llm=llm, config=config, **kwargs)

    def list_available_agents(self) -> List[str]:
        """
        Get a list of all available agent class names.

        Returns:
            List[str]: A list of strings representing the names of all available agent classes.
        """
        return list(self._classes.keys())
