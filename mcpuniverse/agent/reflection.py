"""
A Reflection agent implementation.

"""
# pylint: disable=broad-exception-caught
import os
import json
from typing import Optional, Union, Dict, List
from dataclasses import dataclass
from mcp.types import TextContent
from jinja2 import Environment

from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import (
    send_message_async,
    CallbackMessage,
    MessageType
)
from .react import ReAct, ReActConfig
from .types import AgentResponse

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")


@dataclass
class ReflectionConfig(ReActConfig):
    """
    Configuration class for Reflection agents.

    Attributes:
        reflection_prompt (str): The system prompt for the reflection agent.
    """
    reflection_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "reflection_prompt.j2")


class Reflection(ReAct):
    """
    Reflection agent implementation.

    This class implements the Reflection agent paradigm,

    Attributes:
        config_class (Type[ReflectionConfig]): The configuration class for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = ReflectionConfig
    alias = ["reflection"]

    def _build_reflection_prompt(self, question: str):
        """
        Construct the prompt for the language model.

        Args:
            question (str): The reflection question.

        Returns:
            str: The constructed prompt including system instructions, context, and history.
        """
        params = {
            "QUESTION": question,
            "HISTORY": "\n".join(self._history)
        }
        with open(self._config.reflection_prompt, "r", encoding="utf-8") as f:
            reflection_prompt_template = f.read()
        env = Environment(trim_blocks=True, lstrip_blocks=True)
        template = env.from_string(reflection_prompt_template)
        reflection_prompt = template.render(**params)
        return reflection_prompt

    async def _execute_reflection(self, question, tracer, callbacks):
        prompt = self._build_reflection_prompt(question)
        response = await self._llm.generate_async(
            messages=[{"role": "user", "content": prompt}],
            tracer=tracer,
            callbacks=callbacks
        )
        response = response.strip().strip('`').strip()
        if response.startswith("json"):
            response = response[4:].strip()
        parsed_response = json.loads(response)
        return parsed_response

    async def _execute(
            self,
            message: Union[str, List[str]],
            output_format: Optional[Union[str, Dict]] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the Reflection agent's reasoning and action loop.

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
                # import pdb;pdb.set_trace()
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
                    await send_message_async(callbacks, message=CallbackMessage(
                        source=__file__,
                        type=MessageType.LOG,
                        metadata={
                            "event": "plain_text",
                            "data": "".join([
                                f"{'=' * 66}\n",
                                f"Iteration: {iter_num + 1}\n",
                                f"{'-' * 66}\n",
                                f"\033[32mThought: {parsed_response['thought']}\n\n\033[0m",
                                f"\033[31mAnswer: {parsed_response['answer']}\n\n\033[0m",
                            ])
                        }
                    ))
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
                            await send_message_async(callbacks, message=CallbackMessage(
                                source=__file__,
                                type=MessageType.LOG,
                                metadata={
                                    "event": "plain_text",
                                    "data": "".join([
                                        f"{'=' * 66}\n",
                                        f"Iteration: {iter_num + 1}\n",
                                        f"{'-' * 66}\n",
                                        f"\033[32mThought: {parsed_response['thought']}\n\n\033[0m",
                                        f"\033[31mAction: {parsed_response['action']}\n\n\033[0m",
                                        f"\033[33mResult: {result}\n\033[0m",
                                    ])
                                }
                            ))
                        except Exception as e:
                            self._add_history(history_type="result", message=str(e)[:300])

                elif "result" in parsed_response:
                    self._add_history(
                        history_type="thought",
                        message=parsed_response["thought"]
                    )
                    self._add_history(
                        history_type="result",
                        message=parsed_response["result"]
                    )
                    await send_message_async(callbacks, message=CallbackMessage(
                        source=__file__,
                        type=MessageType.LOG,
                        metadata={
                            "event": "plain_text",
                            "data": "".join([
                                f"{'=' * 66}\n",
                                f"Iteration: {iter_num + 1}\n",
                                f"{'-' * 66}\n",
                                f"\033[32mThought: {parsed_response['thought']}\n\n\033[0m",
                                f"\033[33mResult: {parsed_response['result']}\n\n\033[0m"
                            ])
                        }
                    ))
                else:
                    raise ValueError("Invalid response format")
                # reflection process
                parsed_reflection_response = await self._execute_reflection(message, tracer, callbacks)
                if "reflection" not in parsed_reflection_response:
                    raise ValueError("Invalid reflection response format")
                self._add_history(history_type="reflection", message=parsed_reflection_response['reflection'])
                await send_message_async(callbacks, message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    metadata={
                        "event": "plain_text",
                        "data": "".join([
                            "\n",
                            f"\033[34mReflection: {parsed_reflection_response['reflection']}\n\033[0m",
                            "\n"
                        ])
                    }
                ))
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
