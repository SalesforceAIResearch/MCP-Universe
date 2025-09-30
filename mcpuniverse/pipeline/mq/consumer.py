"""MQ consumer"""
# pylint: disable=broad-exception-caught
import logging
from typing import Callable, Any, Optional, List, Generator, Union
from kafka import KafkaConsumer
from kafka.errors import KafkaError, KafkaTimeoutError
from mcpuniverse.common.misc import AutodocABCMeta

logger = logging.getLogger(__name__)


class Consumer(metaclass=AutodocABCMeta):
    """
    Production-ready Kafka consumer with robust error handling and configuration.
    
    Provides reliable message consumption with proper connection management,
    offset handling, and comprehensive error handling.
    """

    def __init__(
            self,
            host: str,
            port: int,
            topic: Union[str, List[str]],
            value_deserializer: Callable,
            key_deserializer: Optional[Callable] = None,
            bootstrap_servers: Optional[List[str]] = None,
            group_id: str = "mcpuniverse-group",
            auto_offset_reset: str = "latest",
            enable_auto_commit: bool = True,
            **kwargs
    ):
        """
        Initialize Kafka consumer with production-ready settings.
        
        Args:
            host: Kafka broker host.
            port: Kafka broker port.
            topic: Topic(s) to subscribe to.
            value_deserializer: Function to deserialize message values.
            key_deserializer: Function to deserialize message keys.
            bootstrap_servers: List of bootstrap servers (overrides host:port).
            group_id: Consumer group ID.
            auto_offset_reset: Offset reset strategy ('earliest', 'latest', 'none').
            enable_auto_commit: Whether to auto-commit offsets.
            **kwargs: Additional KafkaConsumer configuration.
        """
        self._host = host
        self._port = port
        self._topic = topic

        servers = bootstrap_servers if bootstrap_servers else [f"{host}:{port}"]
        config = {
            "bootstrap_servers": servers,
            "group_id": group_id,
            "auto_offset_reset": auto_offset_reset,
            "enable_auto_commit": enable_auto_commit,
            "value_deserializer": value_deserializer,
            **kwargs
        }
        if key_deserializer:
            config["key_deserializer"] = key_deserializer

        try:
            self._client = KafkaConsumer(topic, **config)
            logger.info("Kafka consumer initialized successfully for topics: %s", self._topics)
        except Exception as e:
            logger.error("Failed to initialize Kafka consumer: %s", str(e))
            raise

    def __del__(self):
        """Cleanup Kafka client."""
        self.close()

    def consume_messages(
            self,
            timeout_ms: int = 1000,
            max_messages: Optional[int] = None
    ) -> Generator[Any, None, None]:
        """
        Generator that yields messages from Kafka topics.
        
        Args:
            timeout_ms: Timeout for polling messages.
            max_messages: Maximum number of messages to consume (None for unlimited).
            
        Yields:
            Deserialized message values.
        """
        message_count = 0

        while True:
            if max_messages is not None and message_count >= max_messages:
                logger.info("Reached maximum message limit: %d", max_messages)
                break

            try:
                message_batch = self._client.poll(
                    timeout_ms=timeout_ms,
                    max_records=self._client.config.get('max_poll_records', 500)
                )
                if not message_batch:
                    continue

                for _, messages in message_batch.items():
                    for message in messages:
                        try:
                            logger.debug(
                                "Received message from topic=%s partition=%s offset=%s",
                                message.topic,
                                message.partition,
                                message.offset
                            )
                            yield message.value
                            message_count += 1
                            if max_messages is not None and message_count >= max_messages:
                                return

                        except Exception as e:
                            logger.error("Error processing message: %s", str(e))
                            continue

            except KafkaTimeoutError:
                logger.debug("Poll timeout, continuing...")
                continue
            except KafkaError as e:
                logger.error("Kafka error during poll: %s", str(e))
                break
            except Exception as e:
                logger.error("Unexpected error during poll: %s", str(e))
                break

    def seek_to_beginning(self, partitions: Optional[List] = None):
        """
        Seek to the beginning of topics/partitions.
        
        Args:
            partitions: Specific partitions to seek (None for all assigned partitions).
        """
        try:
            if partitions:
                self._client.seek_to_beginning(*partitions)
            else:
                self._client.seek_to_beginning()
            logger.info("Seeked to beginning of partitions")
        except Exception as e:
            logger.error("Error seeking to beginning: %s", str(e))

    def seek_to_end(self, partitions: Optional[List] = None):
        """
        Seek to the end of topics/partitions.
        
        Args:
            partitions: Specific partitions to seek (None for all assigned partitions).
        """
        try:
            if partitions:
                self._client.seek_to_end(*partitions)
            else:
                self._client.seek_to_end()
            logger.info("Seeked to end of partitions")
        except Exception as e:
            logger.error("Error seeking to end: %s", str(e))

    def close(self, timeout: Optional[float] = None):
        """
        Close the consumer and release resources.
        
        Args:
            timeout: Maximum time to wait for close completion.
        """
        try:
            self._client.close(timeout_ms=timeout)
            logger.info("Kafka consumer closed successfully")
        except Exception as e:
            logger.error("Error closing Kafka consumer: %s", str(e))
