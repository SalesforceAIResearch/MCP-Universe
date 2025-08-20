"""
A module containing a basic LLM calling agent implementation.

This module defines the BasicAgentConfig and BasicAgent classes, which provide
a simple interface for interacting with LLMs.
"""
# pylint: disable=unused-argument
from typing import Optional, Union, Dict, List
from dataclasses import dataclass
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from .base import BaseAgentConfig, BaseAgent
from .utils import build_system_prompt
from .types import AgentResponse


@dataclass
class BasicAgentConfig(BaseAgentConfig):
    """
    Configuration class for basic LLM calling agents.

    This class extends BaseAgentConfig and can be used to customize the
    behavior of BasicAgent instances.
    """


class BasicAgent(BaseAgent):
    """
    A basic agent class for making LLM calls.

    This class implements a simple agent that interacts with a LLM to
    generate responses based on user input.

    Attributes:
        config_class (Type): The configuration class used for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = BasicAgentConfig
    alias = ["basic"]

    def __init__(
            self,
            mcp_manager: Optional[MCPManager] = None,
            llm: BaseLLM = None,
            config: Optional[Union[Dict, str]] = None,
            **kwargs
    ):
        """
        Initialize a BasicAgent instance.

        Args:
            llm (BaseLLM): The LLM to be used by this agent.
            config (Optional[Union[Dict, str]]): Agent configuration, either as a
                dictionary or a string reference to a predefined configuration.
            **kwargs: Additional keyword arguments for agent initialization.
        """
        assert llm is not None, "LLM cannot be None"
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

    async def _execute(
            self,
            message: Union[str, List[str]],
            output_format: Optional[Union[str, Dict]] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute a command by sending a message to the LLM and processing the response.

        Args:
            message (Union[str, List[str]]): The user message or list of messages to be processed.
            output_format (Optional[Union[str, Dict]]): Desired format for the output, if any.
            **kwargs: Additional keyword arguments for execution.

        Returns:
            AgentResponse: An object containing the LLM's response and associated metadata.
        """
        params = {"INSTRUCTION": self._config.instruction}
        params.update(self._config.template_vars)
        prompt = build_system_prompt(
            system_prompt_template=self._config.system_prompt,
            tool_prompt_template=self._config.tools_prompt,
            tools=None,
            **params
        )
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        if output_format is not None:
            message = message + "\n\n" + self._get_output_format_prompt(output_format)
        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        response = await self._llm.generate_async(
            messages=[{"role": "system", "content": prompt},
                      {"role": "user", "content": message}],
            tracer=tracer,
            callbacks=callbacks,
            remote_mcp=self.get_remote_mcp_list()
        )
        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=response,
            trace_id=tracer.trace_id
        )
