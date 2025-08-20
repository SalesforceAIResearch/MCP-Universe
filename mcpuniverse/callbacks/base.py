"""
Base classes for callbacks
"""
# pylint: disable=too-few-public-methods,broad-exception-caught
import datetime
from enum import Enum
from typing import List
from pydantic import BaseModel, Field
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.common.logger import get_logger


class MessageType(str, Enum):
    """
    Callback message types.
    """
    EVENT = "event"
    STATE = "state"
    RESPONSE = "response"
    STATUS = "status"
    REPORT = "report"
    LOG = "log"
    ERROR = "error"
    PROGRESS = "progress"


class Event(str, Enum):
    """
    Callback events.
    """
    BEFORE_CALL = "before_call"
    AFTER_CALL = "after_call"


class Status(str, Enum):
    """
    Running status of LLMs, MCPs and agents.
    """
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class CallbackMessage(BaseModel):
    """
    The data class for callback messages/parameters.
    """
    source: str = Field(description="The message source ID in the format `project_id:llm/agent/mcp:name`")
    type: MessageType = Field(default="", description="The message type")
    project_id: str = Field(default="", description="The project ID")
    data: str | dict = Field(default="", description="The message data")
    metadata: dict = Field(default_factory=dict, description="The message metadata")
    timestamp: float = Field(default=0, description="The message timestamp")


class BaseCallback(metaclass=AutodocABCMeta):
    """
    The base class for callback functions.
    """

    def __init__(self):
        self._logger = get_logger(self.__class__.__name__)

    def call(self, message: CallbackMessage, **kwargs):
        """Process the input message."""

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Process the input message."""

    def __call__(self, message: CallbackMessage, **kwargs):
        """Process the input message."""
        try:
            self.call(message, **kwargs)
        except Exception as e:
            self._logger.error("Callback error: %s", str(e))


class DefaultCallback(BaseCallback):
    """
    A default callback which does nothing.
    """

    def call(self, message: CallbackMessage, **kwargs):
        """Process the input message."""

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Process the input message."""


class Printer(BaseCallback):
    """
    Print call messages.
    """

    def __init__(self, message_types: List[str] = None):
        super().__init__()
        types = [x.value for x in list(MessageType)]
        if message_types is None:
            message_types = types
        for t in message_types:
            if t not in types:
                raise ValueError(f"Invalid message type: {t}")
        self._message_types = message_types

    def call(self, message: CallbackMessage, **kwargs):
        """Print call messages."""
        if message.type.value not in self._message_types:
            return
        print(message.model_dump(mode="json"))

    async def call_async(self, message: CallbackMessage, **kwargs):
        """Print call messages asynchronously."""
        self.call(message, **kwargs)


def send_message(callbacks: BaseCallback | List[BaseCallback], message: CallbackMessage):
    """Send a message to all the callbacks"""
    if message.timestamp == 0:
        message.timestamp = datetime.datetime.now(datetime.timezone.utc).timestamp()
    if callbacks is None:
        return
    if isinstance(callbacks, BaseCallback):
        callbacks = [callbacks]
    for callback in callbacks:
        callback(message)


async def send_message_async(callbacks: BaseCallback | List[BaseCallback], message: CallbackMessage):
    """Send a message to all the callbacks asynchronously"""
    if message.timestamp == 0:
        message.timestamp = datetime.datetime.now().timestamp()
    if callbacks is None:
        return
    if isinstance(callbacks, BaseCallback):
        callbacks = [callbacks]
    for callback in callbacks:
        await callback.call_async(message)
