"""Base abstract classes for message queue producers and consumers."""

from abc import abstractmethod
from typing import Any, Callable, Generator
from mcpuniverse.common.misc import AutodocABCMeta


class BaseProducer(metaclass=AutodocABCMeta):
    """Abstract base class for message queue producers."""

    def __init__(
            self,
            host: str,
            port: int,
            topic: str,
            value_serializer: Callable
    ):
        """
        Initialize the producer with connection parameters.
        
        Args:
            host: Message broker host.
            port: Message broker port.
            topic: Default topic for messages.
            value_serializer: Function to serialize message values.
        """
        self._host = host
        self._port = port
        self._topic = topic
        self._value_serializer = value_serializer

    def __del__(self):
        """Cleanup producer resources."""
        self.close()

    @abstractmethod
    def send(self, obj: Any, **kwargs) -> bool:
        """
        Send a message to the message queue.
        
        Args:
            obj: Message object to send.
            **kwargs: Additional send parameters.
            
        Returns:
            True if message sent successfully, False otherwise.
        """

    @abstractmethod
    def close(self, **kwargs):
        """
        Close the producer and release resources.
        
        Args:
            **kwargs: Additional close parameters.
        """


class BaseConsumer(metaclass=AutodocABCMeta):
    """Abstract base class for message queue consumers."""

    def __init__(
            self,
            host: str,
            port: int,
            topic: str,
            value_deserializer: Callable
    ):
        """
        Initialize the consumer with connection parameters.
        
        Args:
            host: Message broker host.
            port: Message broker port.
            topic: Topic to subscribe to.
            value_deserializer: Function to deserialize message values.
        """
        self._host = host
        self._port = port
        self._topic = topic
        self._value_deserializer = value_deserializer

    def __del__(self):
        """Cleanup consumer resources."""
        self.close()

    @abstractmethod
    def consume_messages(self, **kwargs) -> Generator:
        """
        Consume messages from the message queue.
        
        Args:
            **kwargs: Additional consumption parameters.
            
        Yields:
            Deserialized message values.
        """

    @abstractmethod
    def close(self, **kwargs):
        """
        Close the consumer and release resources.
        
        Args:
            **kwargs: Additional close parameters.
        """
