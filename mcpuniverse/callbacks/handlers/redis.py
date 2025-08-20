"""
Provides a redis-based callback handler for processing callback messages.
"""
import json
from typing import Optional
from enum import Enum

import redis
from pydantic_core import from_json
from mcpuniverse.callbacks.base import CallbackMessage, BaseCallback


class RedisHandler(BaseCallback):
    """
    A callback handler for storing callback messages in redis.
    """

    def __init__(self, host: str = "localhost", port: int = 6379, expiration_time: int = 3600):
        """
        Initialize a new RedisHandler instance.

        Args:
            host (str, optional): The redis host address. Default "localhost".
            port (int, optional): The redis port. Default "6379".
            expiration_time (int, optional): The record expiration time. Default "3600".
        """
        super().__init__()
        self._redis = redis.Redis(host=host, port=port)
        self._expiration_time = expiration_time

    def call(self, message: CallbackMessage, **kwargs):
        """
        Process the callback message, i.e., insert the message into redis.

        Args:
            message (CallbackMessage): The message to be processed.
        """
        self.set(message)

    def set(self, message: CallbackMessage):
        """
        Store a callback message into redis.

        Args:
            message (CallbackMessage): The message to be stored.
        """
        key = f"callback:{message.source}:{message.type.value}"
        value = json.dumps(message.model_dump(mode="json"))
        self._redis.set(key, value)
        if self._expiration_time is not None and self._expiration_time > 0:
            self._redis.expire(key, self._expiration_time)

    def get(self, source: str, message_type: str | Enum) -> Optional[CallbackMessage]:
        """
        Retrieve callback messages from redis.

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
        value = self._redis.get(key)
        if value is None:
            return None
        return CallbackMessage.model_validate(from_json(value))
