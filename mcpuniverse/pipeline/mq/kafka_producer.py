"""Kafka message queue producer."""
# pylint: disable=broad-exception-caught
from typing import Callable, Any, Optional, List
from kafka import KafkaProducer
from kafka.errors import KafkaError, KafkaTimeoutError, MessageSizeTooLargeError
from mcpuniverse.common.logger import get_logger
from mcpuniverse.pipeline.mq.base import BaseProducer


class Producer(BaseProducer):
    """
    Production-ready Kafka producer with robust error handling and configuration.
    
    Provides reliable message publishing with proper connection management,
    retries, and comprehensive error handling.
    """

    def __init__(
            self,
            host: str,
            port: int,
            topic: str,
            value_serializer: Callable,
            key_serializer: Optional[Callable] = None,
            bootstrap_servers: Optional[List[str]] = None,
            retries: int = 100,
            retry_backoff_ms: int = 500,
            batch_size: int = 16384,
            **kwargs
    ):
        """
        Initialize Kafka producer with production-ready settings.
        
        Args:
            host: Kafka broker host.
            port: Kafka broker port.
            topic: Default topic for messages.
            value_serializer: Function to serialize message values.
            key_serializer: Function to serialize message keys.
            bootstrap_servers: List of bootstrap servers (overrides host:port).
            retries: Number of retry attempts for failed sends.
            batch_size: Batch size for batching messages.
            **kwargs: Additional KafkaProducer configuration.
        """
        super().__init__(host=host, port=port, topic=topic, value_serializer=value_serializer)
        self._logger = get_logger(self.__class__.__name__)

        servers = bootstrap_servers if bootstrap_servers else [f"{host}:{port}"]
        config = {
            "bootstrap_servers": servers,
            "value_serializer": value_serializer,
            "retries": retries,
            "retry_backoff_ms": retry_backoff_ms,
            "batch_size": batch_size,
            "enable_idempotence": True,  # Ensure exactly-once semantics
            **kwargs
        }
        if key_serializer:
            config["key_serializer"] = key_serializer

        try:
            self._client = KafkaProducer(**config)
            self._logger.info("Kafka producer initialized successfully")
        except Exception as e:
            self._logger.error("Failed to initialize Kafka producer: %s", str(e))
            raise

    def send(
            self,
            obj: Any,
            topic: Optional[str] = None,
            key: Any = None,
            partition: Optional[int] = None,
            **kwargs
    ) -> bool:
        """
        Send a message to Kafka with robust error handling.
        
        Args:
            obj: Message value to send.
            topic: Topic to send to (defaults to instance topic).
            key: Message key for partitioning.
            partition: Specific partition to send to.
            
        Returns:
            True if message sent successfully, False otherwise.
        """
        target_topic = topic or self._topic

        try:
            future = self._client.send(
                topic=target_topic,
                value=obj,
                key=key,
                partition=partition
            )

            # Wait for send to complete with timeout
            record_metadata = future.get(timeout=60)
            self._logger.debug(
                "Message sent successfully to topic=%s partition=%s offset=%s",
                record_metadata.topic,
                record_metadata.partition,
                record_metadata.offset
            )
            return True

        except KafkaTimeoutError as e:
            self._logger.error("Kafka send timeout for topic %s: %s", target_topic, str(e))
            return False
        except MessageSizeTooLargeError as e:
            self._logger.error("Kafka too large message sending to topic %s: %s", target_topic, str(e))
            return False
        except KafkaError as e:
            self._logger.error("Kafka error sending to topic %s: %s", target_topic, str(e))
            return False
        except Exception as e:
            self._logger.error("Unexpected error sending to topic %s: %s", target_topic, str(e))
            return False

    def send_async(
            self,
            obj: Any,
            topic: Optional[str] = None,
            key: Any = None,
            partition: Optional[int] = None,
            callback: Optional[Callable] = None
    ):
        """
        Send a message asynchronously to Kafka.
        
        Args:
            obj: Message value to send.
            topic: Topic to send to (defaults to instance topic).
            key: Message key for partitioning.
            partition: Specific partition to send to.
            callback: Callback function for send result.
        """
        target_topic = topic or self._topic

        def error_callback(exception):
            self._logger.error("Async send failed for topic %s: %s", target_topic, str(exception))
            if callback:
                callback(None, exception)

        def success_callback(record_metadata):
            self._logger.debug(
                "Async message sent to topic=%s partition=%s offset=%s",
                record_metadata.topic,
                record_metadata.partition,
                record_metadata.offset
            )
            if callback:
                callback(record_metadata, None)

        try:
            future = self._client.send(
                topic=target_topic,
                value=obj,
                key=key,
                partition=partition
            )
            future.add_callback(success_callback)
            future.add_errback(error_callback)

        except Exception as e:
            self._logger.error("Failed to initiate async send to topic %s: %s", target_topic, str(e))
            if callback:
                callback(None, e)

    def flush(self, timeout: Optional[float] = None) -> bool:
        """
        Flush all buffered messages.
        
        Args:
            timeout: Maximum time to wait for flush completion.
            
        Returns:
            True if flush completed successfully, False otherwise.
        """
        try:
            self._client.flush(timeout=timeout)
            self._logger.debug("Producer flush completed successfully")
            return True
        except Exception as e:
            self._logger.error("Producer flush failed: %s", str(e))
            return False

    def close(self, timeout: Optional[float] = None, **kwargs):
        """
        Close the producer and release resources.
        
        Args:
            timeout: Maximum time to wait for close completion.
        """
        try:
            self._client.close(timeout=timeout)
            self._logger.info("Kafka producer closed successfully")
        except Exception as e:
            self._logger.error("Error closing Kafka producer: %s", str(e))
