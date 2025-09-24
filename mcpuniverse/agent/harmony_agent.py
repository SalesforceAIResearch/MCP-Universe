"""
A Harmony ReAct agent implementation for GPT-OSS models.
"""
# pylint: disable=broad-exception-caught
import os
import json
from typing import Optional, Union, Dict, List
from collections import OrderedDict
from dataclasses import dataclass

import tiktoken

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import (
    send_message,
    send_message_async,
    CallbackMessage,
    MessageType,
)
from .base import BaseAgentConfig, BaseAgent
from .utils import render_tools_namespace, render_harmony_chain, parse_harmony
from .types import AgentResponse

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")


@dataclass
class HarmonyReActConfig(BaseAgentConfig):
    """
    Configuration class for Harmony ReAct agents.

    Attributes:
        system_prompt (str): The system prompt template file or string.
        context_examples (str): Additional context examples for the agent (not used).
        max_iterations (int): Maximum number of reasoning iterations.
        summarize_tool_response (bool): Whether to summarize tool responses using the LLM.
    """
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "react_prompt.j2")
    context_examples: str = ""
    max_iterations: int = 5
    summarize_tool_response: bool = False


class HarmonyReAct(BaseAgent):
    """
    Harmony ReAct agent implementation.

    This class implements the Harmony agent for GPT-OSS models.

    Attributes:
        config_class (Type[HarmonyReActConfig]): The configuration class for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = HarmonyReActConfig
    alias = ["harmony_react"]

    def __init__(
        self,
        mcp_manager: MCPManager,
        llm: BaseLLM,
        config: Optional[Union[Dict, str]] = None,
    ):
        """
        Initialize a Harmony ReAct agent.

        Args:
            mcp_manager (MCPManager): An MCP server manager for handling tool interactions.
            llm (BaseLLM): A language model for generating responses.
            config (Optional[Union[Dict, str]]): Agent configuration as a dictionary or file path.
        """
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")
        self._tools_namespace_ts = ""
        self._history: List[str] = []
        self._remove_tool_output = False
        # Initialize attributes to avoid W0201 (defined outside __init__)
        self.encoding = None
        self._message = ""

    async def _initialize(self):
        """Initialize the harmony agent after tools are loaded."""
        if self._tools and self._config.summarize_tool_response:
            self.encoding = tiktoken.encoding_for_model("gpt-oss-120b")

        self._tools_namespace_ts = render_tools_namespace(self._tools)

    def _build_prompt(self, question: str, output_format: Optional[Union[str, Dict]] = None):
        """
        Construct the prompt for the language model.

        Args:
            question (str): The user's question or task.

        Returns:
            str: The constructed prompt in harmony format.
        """
        instruction = f"""{self._config.instruction}\n
Your goal is to reason about the task and use tools to answer it accurately. 
Please use only the tools that are explicitly defined below. 
At each step, you can either use a tool or provide a final answer. 
Do **not** ask clarifying questions.
Your MUST output the final answer within {self._config.max_iterations} steps. Be aware of the number of steps remaining.
Return the final answer in the final channel.
"""
        if output_format is not None:
            instruction = instruction + "\n\n" + self._get_output_format_prompt(output_format)
        else:
            instruction = (
                instruction
                + "\n\n"
                + "Follow this JSON format when you output the final answer: "
                + "[final_answer] or {final_answer}. "
                + "No extra text. Do not include any literal such as json before the output. "
                + "Do not wrap in code fences."
            )
        prompt = render_harmony_chain(
            developer_instructions=instruction,
            tools_namespace_ts=self._tools_namespace_ts,
            user_first_message=question,
            rounds=self._history,
            reasoning=self._llm.config.reasoning,
        )

        return prompt

    def _add_history(
        self,
        analysis: str,
        tool_call_name: Optional[str] = None,
        tool_call_arguments: Optional[dict] = None,
        tool_result: Optional[str] = None,
    ) -> None:
        """
        Appends a new round to the rounds list.

        Each round must have:
            - analysis (str)
            - tool_call (dict with name and arguments) [optional]
            - tool_result (str) [optional]
        """
        if not isinstance(analysis, str):
            raise TypeError("analysis must be a string")
        if tool_call_name is not None and not isinstance(tool_call_name, str):
            raise TypeError("tool_call_name must be a string if provided")
        if tool_call_arguments is not None and not isinstance(tool_call_arguments, dict):
            raise TypeError("tool_call_arguments must be a dict if provided")
        if tool_result is not None and not isinstance(tool_result, str):
            raise TypeError("tool_result must be a string if provided")

        round_entry = {"analysis": analysis}
        if tool_call_name is not None:
            round_entry["tool_call"] = {
                "name": tool_call_name,
                "arguments": tool_call_arguments or {},
            }
            if tool_result is not None:
                round_entry["tool_result"] = tool_result
        self._history.append(round_entry)

    async def _execute(
        self,
        message: Union[str, List[str]],
        output_format: Optional[Union[str, Dict]] = None,
        **kwargs,
    ) -> AgentResponse:
        """
        Execute the Harmony agent's reasoning and action loop.

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
        self._message = message

        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        format_error_count = 0

        for iter_num in range(self._config.max_iterations):
            try:
                prompt = self._build_prompt(message, output_format)
                messages = [{"role": "raw", "content": prompt}]

                while True:
                    response = await self._llm.generate_async(
                        messages=messages,
                        tracer=tracer,
                        callbacks=callbacks,
                    )
                    if response:
                        break
                if response is None:
                    continue
                parsed_response = parse_harmony(response)

                if "analysis" not in parsed_response:
                    raise ValueError("Invalid response format: missing analysis")

                if parsed_response["tool_call"]:
                    action = parsed_response["tool_call"][0]
                    if not isinstance(action, dict) or "server" not in action or "tool" not in action:
                        tool_result = "Invalid tool call"
                    else:
                        try:
                            tool_result = await self.call_tool(
                                action,
                                tracer=tracer,
                                callbacks=callbacks,
                            )
                            tool_result = tool_result.content[0].text
                        except Exception as e:
                            tool_result = "Error calling tool: " + str(e)[:500]

                        self._add_history(
                            analysis=parsed_response["analysis"],
                            tool_call_name=action["tool_name"],
                            tool_call_arguments=action["arguments"],
                            tool_result=tool_result,
                        )

                        if self._config.summarize_tool_response:
                            if self._remove_tool_output and len(self._history) >= 2:
                                self._history[-2]["tool_result"] = ""
                                self._remove_tool_output = False
                            tokens = self.encoding.encode(tool_result)
                            if len(tokens) > 2000:
                                self._history[-1]["tool_result"] = (
                                    tool_result[:50000]
                                    + "\n"
                                    + "Please summarize the above tool output in the next step. "
                                      "Put the summary in the analysis channel, keep all the important information."
                                )
                                self._remove_tool_output = True

                        tool_result = tool_result[:500] + "\n..."  # truncate for printing

                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["analysis"],
                        action=action,
                        result=tool_result,
                    )

                if not parsed_response["tool_call"] and parsed_response["final"] is not None:

                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["analysis"],
                        answer=parsed_response["final"],
                    )
                    return AgentResponse(
                        name=self._name,
                        class_name=self.__class__.__name__,
                        response=parsed_response["final"],
                        trace_id=tracer.trace_id,
                    )
                if not parsed_response["tool_call"] and parsed_response["final"] is None:
                    format_error_count += 1
                    if format_error_count <= 5:
                        analysis = (
                            parsed_response["analysis"]
                            + "\n\n"
                            + "Cannot find <|channel|>commentary or <|channel|>final. "
                              "In your next step, be careful with the channel format."
                        )
                        await self._send_callback_message(
                            callbacks=callbacks,
                            iter_num=iter_num,
                            thought=analysis,
                        )
                        self._add_history(
                            analysis=analysis,
                        )
                    else:
                        # give up, use the analysis as the answer
                        await self._send_callback_message(
                            callbacks=callbacks,
                            iter_num=iter_num,
                            answer=parsed_response["analysis"],
                        )
                        return AgentResponse(
                            name=self._name,
                            class_name=self.__class__.__name__,
                            response=parsed_response["analysis"],
                            trace_id=tracer.trace_id,
                        )

            except Exception as e:
                self._logger.error("Failed to process response: %s", str(e))
                response = response + "\n\n" + "Failed to process response: " + str(e)
                self._add_history(
                    analysis=response,
                )
                await self._send_callback_message(
                    callbacks=callbacks,
                    iter_num=iter_num,
                    thought=response,
                )

        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response="I'm sorry, but I couldn't find a satisfactory answer within the allowed number of iterations.",
            trace_id=tracer.trace_id,
        )

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
        answer: str = "",
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
        send_message(
            callbacks,
            message=CallbackMessage(
                source=__file__,
                type=MessageType.LOG,
                data=data,
            ),
        )
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
                    "data": "".join(data),
                },
            ),
        )

    @staticmethod
    def _get_output_format_prompt(output_format: Union[str, Dict]) -> str:
        """Return the custom output-format prompt for Harmony agent."""
        custom_output_format_prompt = """
Follow this JSON format when you output the final answer:
{output_format}
No markdown formatting. No extra text. Do not include any literal such as json before the output. Do not wrap in code fences."
Property names must be enclosed in double quotes.
""".strip()

        if output_format is not None:
            if isinstance(output_format, dict):
                output_format_prompt = custom_output_format_prompt.format(
                    output_format=json.dumps(output_format, indent=2)
                )
            else:
                output_format_prompt = output_format
            return output_format_prompt.strip()
        return ""
