"""
A ReAct agent implementation.

This module contains the ReAct agent class and its configuration, based on the paper
'ReAct: Synergizing Reasoning and Acting in Language Models' (https://arxiv.org/abs/2210.03629).
"""
# pylint: disable=broad-exception-caught
import os
import json
from typing import Optional, Union, Dict, List
from collections import OrderedDict
from dataclasses import dataclass
from mcp.types import TextContent

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import (
    send_message,
    send_message_async,
    CallbackMessage,
    MessageType
)
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
        summarize_tool_response (bool): Whether to summarize tool responses using the LLM.
    """
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "react_prompt.j2")
    context_examples: str = ""
    max_iterations: int = 5
    summarize_tool_response: bool = False


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
        params = {
            "INSTRUCTION": self._config.instruction,
            "QUESTION": question,
            "MAX_STEPS": self._config.max_iterations
        }
        if self._config.context_examples:
            params.update({"CONTEXT_EXAMPLES": self._config.context_examples})
        params.update(self._config.template_vars)
        if self._history:
            params.update({"HISTORY": "\n\n".join(self._history)})
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
            history_type (str): The type of the history entry (e.g., "thought", "action", "result").
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
        callbacks = kwargs.get("callbacks", [])

        for iter_num in range(self._config.max_iterations):
            prompt = self._build_prompt(message)
            response = await self._llm.generate_async(
                messages=[{"role": "user", "content": prompt}],
                tracer=tracer,
                callbacks=callbacks
            )
            try:
                response = response.strip().strip('`').strip()
                if response.startswith("json"):
                    response = response[4:].strip()
                parsed_response = json.loads(response)
                if "thought" not in parsed_response:
                    raise ValueError("Invalid response format")
                self._add_history(
                    history_type=f"Step {iter_num + 1}",
                    message="",
                )
                if "answer" in parsed_response:
                    self._add_history(
                        history_type="answer",
                        message=parsed_response["answer"]
                    )
                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["thought"],
                        answer=parsed_response["answer"]
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
                        self._add_history(history_type="result", message="Invalid action")
                        await self._send_callback_message(
                            callbacks=callbacks,
                            iter_num=iter_num,
                            thought=parsed_response["thought"],
                            action=parsed_response["action"],
                            result="Invalid action"
                        )
                    else:
                        self._add_history(
                            history_type="action",
                            message=f"Using tool `{action['tool']}` in server `{action['server']}`"
                        )
                        self._add_history(
                            history_type="action input",
                            message=str(action.get("arguments", "none"))
                        )
                        try:
                            tool_result = await self.call_tool(action, tracer=tracer, callbacks=callbacks)
                            tool_content = tool_result.content[0]
                            tool_summary = None
                            if not isinstance(tool_content, TextContent):
                                raise ValueError("Tool output is not a text")
                            if self._config.summarize_tool_response:
                                context = json.dumps(action, indent=2)
                                tool_summary = await self.summarize_tool_response(
                                    tool_content.text,
                                    context=context,
                                    tracer=tracer
                                )
                                self._add_history(history_type="result", message=tool_summary)
                            else:
                                self._add_history(history_type="result", message=tool_content.text)

                            result = tool_summary if tool_summary else tool_content.text
                            await self._send_callback_message(
                                callbacks=callbacks,
                                iter_num=iter_num,
                                thought=parsed_response["thought"],
                                action=parsed_response['action'],
                                result=result
                            )
                        except Exception as e:
                            self._add_history(history_type="result", message=str(e)[:300])
                            await self._send_callback_message(
                                callbacks=callbacks,
                                iter_num=iter_num,
                                thought=parsed_response["thought"],
                                action=parsed_response['action'],
                                result=str(e)
                            )

                elif "result" in parsed_response:
                    self._add_history(
                        history_type="thought",
                        message=parsed_response["thought"]
                    )
                    self._add_history(
                        history_type="result",
                        message=parsed_response["result"]
                    )
                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["thought"],
                        result=parsed_response["result"]
                    )
                else:
                    raise ValueError("Invalid response format")

            except json.JSONDecodeError as e:
                self._logger.error("Failed to parse response: %s", str(e))
                self._add_history(
                    history_type="error",
                    message="I encountered an error in parsing LLM response. Let me try again."
                )
                send_message(callbacks, message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    data={
                        "step": iter_num + 1,
                        "error": f"Failed to parse response: {str(e)}"
                    }
                ))
            except Exception as e:
                self._logger.error("Failed to process response: %s", str(e))
                self._add_history(
                    history_type="error",
                    message="I encountered an unexpected error. Let me try a different approach."
                )
                send_message(callbacks, message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    data={
                        "step": iter_num + 1,
                        "error": f"Failed to process response: {str(e)}"
                    }
                ))

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

    def reset(self):
        """Reset the agent."""
        self.clear_history()

    @staticmethod
    async def _send_callback_message(
            callbacks,
            iter_num: int,
            thought: str = "",
            action: str = "",
            result: str = "",
            answer: str = ""
    ):
        """Send log messages."""
        logs = []
        if thought:
            logs.append(("thought", thought))
        if action:
            logs.append(("action", action))
        if result:
            logs.append(("result", result))
        if answer:
            logs.append(("answer", answer))

        data = OrderedDict({"Iteration": iter_num + 1})
        for tag, value in logs:
            data[tag] = value
        send_message(callbacks, message=CallbackMessage(
            source=__file__,
            type=MessageType.LOG,
            data=data
        ))
        data = [
            f"{'=' * 66}\n",
            f"Iteration: {iter_num + 1}\n",
            f"{'-' * 66}\n",
        ]
        for tag, value in logs:
            data.append(f"\033[32m{tag.capitalize()}: {value}\n\n\033[0m")
        await send_message_async(
            callbacks,
            message=CallbackMessage(
                source=__file__,
                type=MessageType.LOG,
                metadata={
                    "event": "plain_text",
                    "data": "".join(data)
                }
            )
        )
