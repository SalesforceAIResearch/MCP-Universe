"""MQ producer"""
# pylint: disable=broad-exception-caught
import logging
from typing import Callable, Any, Optional, List
from kafka import KafkaProducer
from kafka.errors import KafkaError, KafkaTimeoutError
from mcpuniverse.common.misc import AutodocABCMeta

logger = logging.getLogger(__name__)


class Producer(metaclass=AutodocABCMeta):
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
            buffer_memory: int = 33554432,
            max_block_ms: int = 60000,
            request_timeout_ms: int = 60000,
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
            buffer_memory: Total memory available for buffering.
            max_block_ms: Maximum time to block on send/partitions-for calls.
            request_timeout_ms: Request timeout for broker requests.
            **kwargs: Additional KafkaProducer configuration.
        """
        self._host = host
        self._port = port
        self._topic = topic

        servers = bootstrap_servers if bootstrap_servers else [f"{host}:{port}"]
        config = {
            "bootstrap_servers": servers,
            "value_serializer": value_serializer,
            "retries": retries,
            "retry_backoff_ms": retry_backoff_ms,
            "batch_size": batch_size,
            "buffer_memory": buffer_memory,
            "max_block_ms": max_block_ms,
            "request_timeout_ms": request_timeout_ms,
            "enable_idempotence": True,  # Ensure exactly-once semantics
            "max_in_flight_requests_per_connection": 5,
            **kwargs
        }
        if key_serializer:
            config["key_serializer"] = key_serializer

        try:
            self._client = KafkaProducer(**config)
            logger.info("Kafka producer initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Kafka producer: %s", str(e))
            raise

    def __del__(self):
        """Cleanup Kafka client"""
        self.close()

    def send(
            self,
            obj: Any,
            topic: Optional[str] = None,
            key: Any = None,
            partition: Optional[int] = None
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
            logger.debug(
                "Message sent successfully to topic=%s partition=%s offset=%s",
                record_metadata.topic,
                record_metadata.partition,
                record_metadata.offset
            )
            return True

        except KafkaTimeoutError as e:
            logger.error("Kafka send timeout for topic %s: %s", target_topic, str(e))
            return False
        except KafkaError as e:
            logger.error("Kafka error sending to topic %s: %s", target_topic, str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error sending to topic %s: %s", target_topic, str(e))
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
            logger.error("Async send failed for topic %s: %s", target_topic, str(exception))
            if callback:
                callback(None, exception)

        def success_callback(record_metadata):
            logger.debug(
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
            logger.error("Failed to initiate async send to topic %s: %s", target_topic, str(e))
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
            logger.debug("Producer flush completed successfully")
            return True
        except Exception as e:
            logger.error("Producer flush failed: %s", str(e))
            return False

    def close(self, timeout: Optional[float] = None):
        """
        Close the producer and release resources.
        
        Args:
            timeout: Maximum time to wait for close completion.
        """
        try:
            self._client.close(timeout=timeout)
            logger.info("Kafka producer closed successfully")
        except Exception as e:
            logger.error("Error closing Kafka producer: %s", str(e))
