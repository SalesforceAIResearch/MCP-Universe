"""
An agent for executing a workflow.

This module defines the WorkflowAgent class and its associated configuration,
which are used to manage and execute workflows within the mcpuniverse framework.
"""
# pylint: disable=unused-argument
from typing import Optional, Union, Dict, List
from dataclasses import dataclass
from mcpuniverse.common.logger import get_logger
from .base import BaseAgentConfig, BaseAgent, Executor
from .types import AgentResponse


@dataclass
class WorkflowAgentConfig(BaseAgentConfig):
    """
    Configuration class for workflow agents.

    This class extends BaseAgentConfig and may include additional
    workflow-specific configuration options.
    """


class WorkflowAgent(BaseAgent):
    """
    An agent for executing a workflow.

    Attributes:
        config_class (Type): The configuration class for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = WorkflowAgentConfig
    alias = ["workflow"]

    def __init__(
            self,
            workflow: Executor,
            config: Optional[Union[Dict, str]] = None,
            **kwargs
    ):
        """
        Initialize a WorkflowAgent.

        Args:
            workflow (Executor): An agent workflow to be executed.
            config (Optional[Union[Dict, str]]): Agent configuration as a dictionary or string.
            **kwargs: Additional keyword arguments.

        Note:
            This agent does not use mcp_manager or llm, which are set to None.
        """
        super().__init__(mcp_manager=None, llm=None, config=config)
        self._workflow = workflow
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

    async def _execute(self, message: Union[str, List[str]], **kwargs) -> AgentResponse:
        """
        Execute the workflow.

        Args:
            message (Union[str, List[str]]): User message or list of messages.
            **kwargs: Additional keyword arguments to pass to the workflow executor.

        Returns:
            AgentResponse: The result of the workflow execution.
        """
        response = await self._workflow.execute(message, **kwargs)
        return response

    async def _initialize(self):
        """Initialize the workflow."""
        await self._workflow.initialize()

    async def _cleanup(self):
        """Clean up the workflow after execution."""
        await self._workflow.cleanup()
