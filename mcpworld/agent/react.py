"""
A ReAct agent implementation.

This module contains the ReAct agent class and its configuration, based on the paper
'ReAct: Synergizing Reasoning and Acting in Language Models' (https://arxiv.org/abs/2210.03629).
"""
# pylint: disable=broad-exception-caught
import os
import json
from typing import Optional, Union, Dict, List
from dataclasses import dataclass
from mcp.types import TextContent

from mcpworld.mcp.manager import MCPManager
from mcpworld.llm.base import BaseLLM
from mcpworld.common.logger import get_logger
from mcpworld.tracer import Tracer
from .base import BaseAgentConfig, BaseAgent
from .utils import build_system_prompt
from .types import AgentResponse

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")


@dataclass
class ReActConfig(BaseAgentConfig):
    """
    Configuration class for ReAct agents.

    Attributes:
        system_prompt (str): The system prompt template file or string.
        context_examples (str): Additional context examples for the agent.
        max_iterations (int): Maximum number of reasoning iterations.
    """
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "react_prompt.j2")
    context_examples: str = ""
    max_iterations: int = 5


class ReAct(BaseAgent):
    """
    ReAct agent implementation.

    This class implements the ReAct (Reasoning+Acting) paradigm,
    allowing the agent to alternate between reasoning and acting to solve tasks.

    Attributes:
        config_class (Type[ReActConfig]): The configuration class for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = ReActConfig
    alias = ["react"]

    def __init__(
            self,
            mcp_manager: MCPManager,
            llm: BaseLLM,
            config: Optional[Union[Dict, str]] = None
    ):
        """
        Initialize a ReAct agent.

        Args:
            mcp_manager (MCPManager): An MCP server manager for handling tool interactions.
            llm (BaseLLM): A language model for generating responses.
            config (Optional[Union[Dict, str]]): Agent configuration as a dictionary or file path.
        """
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")
        self._history: List[str] = []

    def _build_prompt(self, question: str):
        """
        Construct the prompt for the language model.

        Args:
            question (str): The user's question or task.

        Returns:
            str: The constructed prompt including system instructions, context, and history.
        """
        params = {"INSTRUCTION": self._config.instruction, "QUESTION": question}
        if self._config.context_examples:
            params.update({"CONTEXT_EXAMPLES": self._config.context_examples})
        params.update(self._config.template_vars)
        if self._history:
            params.update({"HISTORY": "\n".join(self._history)})
        return build_system_prompt(
            system_prompt_template=self._config.system_prompt,
            tool_prompt_template=self._config.tools_prompt,
            tools=self._tools,
            **params
        )

    def _add_history(self, history_type: str, message: str):
        """
        Add a record to the agent's conversation history.

        Args:
            history_type (str): The type of the history entry (e.g., "thought", "action", "observation").
            message (str): The content of the history entry.
        """
        self._history.append(f"{history_type.title()}: {message}")

    async def _execute(
            self,
            message: Union[str, List[str]],
            output_format: Optional[Union[str, Dict]] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the ReAct agent's reasoning and action loop.

        This method processes the user's message, generates thoughts and actions,
        and returns a final answer or explanation.

        Args:
            message (Union[str, List[str]]): The user's message or a list of messages.
            output_format (Optional[Union[str, Dict]]): Desired format for the output.
            **kwargs: Additional keyword arguments.

        Returns:
            AgentResponse: The agent's final response, including the answer and trace information.
        """
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        if output_format is not None:
            message = message + "\n\n" + self._get_output_format_prompt(output_format)
        tracer = kwargs.get("tracer", Tracer())

        for _ in range(self._config.max_iterations):
            prompt = self._build_prompt(message)
            response = self._llm.generate(
                messages=[{"role": "user", "content": prompt}],
                tracer=tracer
            )
            try:
                response = response.strip().strip('`').strip()
                if response.startswith("json"):
                    response = response[4:].strip()
                parsed_response = json.loads(response)
                if "thought" not in parsed_response:
                    raise ValueError("Invalid response format")
                if "answer" in parsed_response:
                    self._add_history(
                        history_type="answer",
                        message=parsed_response["answer"]
                    )
                    return AgentResponse(
                        name=self._name,
                        class_name=self.__class__.__name__,
                        response=parsed_response["answer"],
                        trace_id=tracer.trace_id
                    )
                if "action" in parsed_response:
                    self._add_history(
                        history_type="thought",
                        message=parsed_response["thought"]
                    )
                    action = parsed_response["action"]
                    if not isinstance(action, dict) or "server" not in action or "tool" not in action:
                        self._add_history(history_type="action", message=str(action))
                        self._add_history(history_type="observation", message="Invalid action")
                    else:
                        self._add_history(
                            history_type="action",
                            message=f"Using tool `{action['tool']}` in server `{action['server']}`"
                        )
                        try:
                            result = await self.call_tool(action)
                            content = result.content[0]
                            if not isinstance(content, TextContent):
                                raise ValueError("Output is not a text")
                            self._add_history(
                                history_type="action input",
                                message=str(action.get("arguments", "none"))
                            )
                            self._add_history(history_type="observation", message=content.text)
                        except Exception as e:
                            self._add_history(history_type="observation", message=str(e)[:300])
                else:
                    raise ValueError("Invalid response format")

            except json.JSONDecodeError as e:
                self._logger.error("Failed to parse response: %s", str(e))
                self._add_history(
                    history_type="error",
                    message="I encountered an error in parsing LLM response. Let me try again."
                )
            except Exception as e:
                self._logger.error("Failed to process response: %s", str(e))
                self._add_history(
                    history_type="error",
                    message="I encountered an unexpected error. Let me try a different approach."
                )
        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response="I'm sorry, but I couldn't find a satisfactory answer within the allowed number of iterations.",
            trace_id=tracer.trace_id
        )

    def get_history(self) -> str:
        """
        Retrieve the agent's conversation history.

        Returns:
            str: A string representation of the agent's conversation history.
        """
        return "\n".join(self._history)

    def clear_history(self):
        """
        Clear the agent's conversation history.
        """
        self._history = []
