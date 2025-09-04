"""
A module containing a basic function calling agent implementation.

This module defines the FunctionCallConfig and FunctionCall classes,
which provide functionality for creating and executing function calling agents.
These agents are stateless and make a single LLM call per execution.
"""
# pylint: disable=broad-exception-caught
from typing import Optional, Union, Dict, List
from dataclasses import dataclass
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from .base import BaseAgentConfig, BaseAgent
from .utils import build_system_prompt
from .types import AgentResponse
from .basic import BasicAgent


@dataclass
class DepreciatedFunctionCallConfig(BaseAgentConfig):
    """
    Configuration class for function calling agents.

    This class extends BaseAgentConfig and may include additional
    attributes specific to function calling agents.
    """


class DepreciatedFunctionCall(BaseAgent):
    """
    A stateless function calling agent that makes a single LLM call per execution.
    It does not maintain memory or context between calls.

    Attributes:
        config_class (Type): The configuration class used for this agent.
        alias (List[str]): Alternative names for identifying this agent type.
    """
    config_class = DepreciatedFunctionCallConfig
    alias = ["depreciated_function_call"]

    def __init__(
            self,
            mcp_manager: MCPManager,
            llm: BaseLLM,
            config: Optional[Union[Dict, str]] = None,
    ):
        """
        Initialize a depreciated function calling agent.

        Args:
            mcp_manager (MCPManager): An MCP server manager for handling MCP-related operations.
            llm (BaseLLM): A language model instance for generating responses.
            config (Optional[Union[Dict, str]]): Agent configuration, either as a dictionary or a string.
                Defaults to None, in which case default configuration will be used.
        """
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")
        self._reformatter = BasicAgent(
            llm=llm,
            config={"instruction": "You are a smart and helpful assistant for reformatting agent responses."}
        )

    async def _execute(
            self,
            message: Union[str, List[str]],
            output_format: Optional[Union[str, Dict]] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute a command using the depreciated function calling agent.

        Args:
            message (Union[str, List[str]]): The user message to process. If a list is provided,
                it will be joined into a single string.
            output_format (Optional[Union[str, Dict]]): Desired format for the output. If provided,
                the response will be reformatted accordingly.
            **kwargs: Additional keyword arguments. May include a 'tracer' for tracking the execution.

        Returns:
            AgentResponse: An object containing the agent's response and metadata.
        """
        params = {"INSTRUCTION": self._config.instruction}
        params.update(self._config.template_vars)
        prompt = build_system_prompt(
            system_prompt_template=self._config.system_prompt,
            tool_prompt_template=self._config.tools_prompt,
            tools=self._tools,
            **params
        )
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        response = await self._llm.generate_async(
            messages=[{"role": "system", "content": prompt},
                      {"role": "user", "content": message}],
            tracer=tracer,
            callbacks=callbacks
        )
        try:
            result = AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response=await self.call_tool(response, tracer=tracer, callbacks=callbacks),
                trace_id=tracer.trace_id
            )
            if output_format is not None:
                input_prompt = f"Please reformat the following agent response:\n\n{result.get_response_str()}"
                await self._reformatter.initialize()
                r = await self._reformatter.execute(
                    input_prompt, output_format=output_format, tracer=tracer)
                await self._reformatter.cleanup()
                result.response = r.response
            return result

        except Exception as e:
            self._logger.error("ERROR: %s", str(e))
            return AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response=response,
                trace_id=tracer.trace_id
            )
