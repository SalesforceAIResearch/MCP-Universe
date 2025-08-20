"""
Provides a memory-based callback handler for processing callback messages.
"""
import json
from typing import Optional
from enum import Enum

from pydantic_core import from_json
from mcpuniverse.callbacks.base import CallbackMessage, BaseCallback


class MemoryHandler(BaseCallback):
    """
    A callback handler for storing callback messages in memory.
    """

    def __init__(self):
        """
        Initialize a new MemoryHandler instance.
        """
        super().__init__()
        self._mem = {}

    def call(self, message: CallbackMessage, **kwargs):
        """
        Process the callback message, i.e., insert the message into memory.

        Args:
            message (CallbackMessage): The message to be processed.
        """
        self.set(message)

    def set(self, message: CallbackMessage):
        """
        Store a callback message into memory.

        Args:
            message (CallbackMessage): The message to be stored.
        """
        key = f"callback:{message.source}:{message.type.value}"
        value = json.dumps(message.model_dump(mode="json"))
        self._mem[key] = value

    def get(self, source: str, message_type: str | Enum) -> Optional[CallbackMessage]:
        """
        Retrieve callback messages from memory.

        Args:
            source (str): The unique identifier of the source.
            message_type (str | Enum): The message type, e.g., "event", "response", etc.

        Returns:
            CallbackMessage: A message object.

        Note:
            This method automatically deserializes JSON-encoded fields back into
            their original data types.
        """
        if isinstance(message_type, Enum):
            message_type = message_type.value
        key = f"callback:{source}:{message_type}"
        value = self._mem.get(key, None)
        if value is None:
            return None
        return CallbackMessage.model_validate(from_json(value))
