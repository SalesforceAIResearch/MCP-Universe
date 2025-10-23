"""
Provides a verbose print-based callback handler for processing callback messages.
"""
import builtins
import time
from functools import partial
from typing import List

from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.benchmark.task import Task
from mcpuniverse.callbacks.base import CallbackMessage, BaseCallback


def _print(*args, delay=0.01, **kwargs):
    """Custom print function that adds delay between words for better readability.

    Args:
        *args: Variable length argument list to print
        delay (float, optional): Delay between words in seconds. Defaults to 0.01.
        **kwargs: Arbitrary keyword arguments passed to built-in print function
    """
    text = ' '.join(str(arg) for arg in args)
    words = text.split(" ")
    for word in words:
        builtins.print(word, end=' ', **kwargs, flush=True)
        time.sleep(delay)
    builtins.print()


class VPrintListToolsCallback(BaseCallback):
    """
    A callback handler for printing the list of tools for an agent.
    """

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Print the list of tools for an agent."""
        try:
            if (
                    'event' in message.metadata and message.metadata['event'] == 'list_tools' and
                    'data' in message.metadata and isinstance(message.metadata['data'], BaseAgent)
            ):
                vprint = partial(_print, delay=0.0001)
                agent = message.metadata['data']
                # pylint: disable=protected-access
                for server_name in agent._mcp_clients.keys():
                    avail_tools = await agent._mcp_clients[server_name].list_tools()

                    vprint('\n')
                    vprint('=' * 66)
                    vprint(f'\033[31mMCP Server: {server_name} includes {len(avail_tools)} tools\033[0m')
                    vprint('-' * 66)
                    for tool_idx, tool in enumerate(avail_tools, start=1):
                        vprint(f"{tool_idx}. {tool.name}")
                        vprint(f"Description: {tool.description}")
                        vprint('\n')
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error("Error processing message: %s", exc)


class VPrintTaskDescriptionCallback(BaseCallback):
    """
    A callback handler for printing the task description.
    """

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Print the task description."""
        try:
            if (
                    'event' in message.metadata and message.metadata['event'] == 'task_description' and
                    'data' in message.metadata and isinstance(message.metadata['data'], Task)
            ):
                vprint = partial(_print, delay=0.0001)
                task = message.metadata['data']
                vprint("\n")
                vprint("=" * 66)
                vprint("\033[31mTask Description:\033[0m")
                vprint("-" * 66)
                vprint(format(task.get_question().replace('\n', '\\n')))
                vprint("-" * 66)
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error("Error processing message: %s", exc)


class VPrintPlainTextCallback(BaseCallback):
    """
    A callback handler for printing plain text.
    """

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Print the plain text."""
        try:
            if (
                    'event' in message.metadata and message.metadata['event'] == 'plain_text' and
                    'data' in message.metadata and isinstance(message.metadata['data'], str)
            ):
                vprint = partial(_print, delay=0.0001)
                vprint(message.metadata['data'])
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error("Error processing message: %s", exc)


def get_vprint_callbacks() -> List[BaseCallback]:
    """Get the list of vprint callbacks."""
    return [
        VPrintPlainTextCallback(),
        VPrintListToolsCallback(),
        VPrintTaskDescriptionCallback()
    ]
