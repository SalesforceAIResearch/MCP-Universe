"""
Base classes for workflows.

This module provides abstract base classes for implementing workflow components,
including the BaseWorkflow class which serves as a foundation for specific workflow implementations.
"""
from abc import abstractmethod
from typing import List
from mcpuniverse.common.misc import ComponentABCMeta
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.agent.base import BaseAgent, Executor


class BaseWorkflow(Executor, metaclass=ComponentABCMeta):
    """
    The base class for all workflow implementations.

    This abstract base class provides a common structure and interface for workflows,
    including initialization and cleanup of associated agents, and execution of commands.

    Attributes:
        _name (str): The name of the workflow.
        _agents (List[BaseAgent]): A list of agents associated with this workflow.
    """

    def __init__(self):
        self._name = "workflow"
        self._agents: List[BaseAgent] = []
        self._project_id = ""

    async def initialize(self):
        """
        Initialize all agents associated with this workflow.

        This method should be called before executing the workflow to ensure
        all agents are properly set up.
        """
        for agent in self._agents:
            await agent.initialize()

    async def cleanup(self):
        """
        Perform cleanup operations for all associated agents.

        This method should be called after the workflow execution is complete
        to ensure proper resource management. Agents are cleaned up in reverse order.
        """
        for agent in self._agents[::-1]:
            await agent.cleanup()

    @abstractmethod
    async def execute(self, message: str | List[str], **kwargs) -> AgentResponse:
        """
        Execute a command or set of commands within the workflow.

        This method must be implemented by subclasses to define the specific
        behavior of the workflow.

        Args:
            message (str | List[str]): The command(s) to be executed.
            **kwargs: Additional keyword arguments for the execution.

        Returns:
            AgentResponse: The response from the workflow execution.
        """

    @property
    def name(self) -> str:
        """Return the workflow name."""
        return self._name

    def set_name(self, name: str):
        """
        Set the name of the workflow.

        Args:
            name (str): The new name for the workflow.
        """
        self._name = name

    def reset(self):
        """Reset the agents."""
        for agent in self._agents:
            agent.reset()

    @property
    def project_id(self) -> str:
        """Return the ID of the project using this workflow."""
        return self._project_id

    @project_id.setter
    def project_id(self, value: str):
        """Set the ID of the project using this workflow."""
        self._project_id = value

    @property
    def id(self):
        """Return the ID of this workflow."""
        if self._project_id:
            return f"{self._project_id}:workflow:{self._name}"
        return f"workflow:{self._name}"
