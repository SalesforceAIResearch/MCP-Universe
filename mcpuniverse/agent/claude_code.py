"""
A module containing a claude-code agent.

This module defines the ClaudeCodeConfig and ClaudeCodeAgent classes, which provide
a simple interface for interacting with claude code SDK.
"""
# pylint: disable=unused-argument,broad-exception-caught
from typing import Optional, Union, Dict, List
from dataclasses import dataclass, asdict, is_dataclass, field
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import ToolUseBlock, ToolResultBlock, ResultMessage
from pydantic import BaseModel

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import (
    CallbackMessage,
    MessageType,
    send_message
)

from .base import BaseAgentConfig, BaseAgent
from .utils import build_system_prompt
from .types import AgentResponse


@dataclass
class ClaudeCodeConfig(BaseAgentConfig):
    """
    Configuration class for claude-code agents.
    """
    max_iterations: int = 10
    disallowed_tools: list = field(default_factory=lambda: [
        "Bash", "Edit", "MultiEdit", "Write", "NotebookEdit", "TodoWrite", "KillBash"])


class ClaudeCodeAgent(BaseAgent):
    """
    A claude code agent class for interacting with claude code SDK.

    This class implements a simple agent that interacts with claude code SDK to
    generate responses based on user input.

    Attributes:
        config_class (Type): The configuration class used for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = ClaudeCodeConfig
    alias = ["claude-code", "claude_code"]

    def __init__(
            self,
            mcp_manager: Optional[MCPManager],
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
        super().__init__(mcp_manager=mcp_manager, llm=None, config=config)
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
            include_tool_description=False,
            **params
        )
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        if output_format is not None:
            message = message + "\n\n" + self._get_output_format_prompt(output_format)
        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        try:
            mcp_servers = self.get_mcp_configs()
            async with ClaudeSDKClient(
                    options=ClaudeCodeOptions(
                        mcp_servers=mcp_servers,
                        permission_mode="bypassPermissions",
                        disallowed_tools=self._config.disallowed_tools,
                        system_prompt=prompt,
                        max_turns=self._config.max_iterations
                    )
            ) as client:
                await client.query(message)

                messages, final_response = [], None
                async for message in client.receive_response():
                    if hasattr(message, "content"):
                        for block in message.content:
                            messages.append(block)
                            if isinstance(block, BaseModel):
                                data = block.model_dump(mode="json")
                            elif is_dataclass(block):
                                data = asdict(block)
                            else:
                                data = block
                            send_message(callbacks, message=CallbackMessage(
                                source=self.id, type=MessageType.RESPONSE,
                                data=data,
                                project_id=self._project_id
                            ))
                    if isinstance(message, ResultMessage):
                        final_response = message.result

                for i, block in enumerate(messages):
                    if isinstance(block, ToolUseBlock):
                        if i + 1 >= len(messages) or not isinstance(messages[i + 1], ToolResultBlock):
                            response = "No response"
                        else:
                            response = messages[i + 1].content
                        names = [name for name in block.name.split("__") if name != "mcp"]
                        tracer.add({
                            "type": "tool",
                            "class": self.__class__.__name__,
                            "server": names[0],
                            "tool_name": names[1],
                            "arguments": block.input,
                            "response": response
                            if isinstance(response, BaseModel) else response,
                            "error": ""
                        })

                return AgentResponse(
                    name=self._name,
                    class_name=self.__class__.__name__,
                    response=final_response,
                    trace_id=tracer.trace_id
                )
        except Exception as e:
            self._logger.error("ERROR: %s", str(e))
            return AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response=str(e),
                trace_id=tracer.trace_id
            )
