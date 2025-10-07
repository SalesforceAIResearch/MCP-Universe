"""RabbitMQ message queue consumer."""
# pylint: disable=broad-exception-caught
import time
from typing import Callable, Optional, Generator
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError, ConnectionClosed
from mcpuniverse.common.logger import get_logger
from mcpuniverse.pipeline.mq.base import BaseConsumer


class Consumer(BaseConsumer):
    """
    Production-ready RabbitMQ consumer with robust error handling and generator-based message consumption.
    
    Provides reliable message consumption with proper connection management,
    acknowledgments, and comprehensive error handling.
    """

    def __init__(
            self,
            host: str,
            port: int,
            topic: str,
            value_deserializer: Callable,
            username: Optional[str] = None,
            password: Optional[str] = None,
            exchange: str = "",
            durable: bool = True,
            auto_ack: bool = False,
            prefetch_count: int = 1,
            **kwargs
    ):
        """
        Initialize RabbitMQ consumer with production-ready settings.
        
        Args:
            host: RabbitMQ broker host.
            port: RabbitMQ broker port.
            topic: Queue name to consume from.
            value_deserializer: Function to deserialize message values.
            username: RabbitMQ username for authentication.
            password: RabbitMQ password for authentication.
            exchange: Exchange name (empty string for default exchange).
            durable: Whether the queue should be durable.
            auto_ack: Whether to automatically acknowledge messages.
            prefetch_count: Number of unacknowledged messages to prefetch.
            **kwargs: Additional pika connection parameters.
        """
        super().__init__(host=host, port=port, topic=topic, value_deserializer=value_deserializer)
        self._logger = get_logger(self.__class__.__name__)
        self._username = username
        self._password = password
        self._exchange = exchange
        self._durable = durable
        self._auto_ack = auto_ack
        self._prefetch_count = prefetch_count
        self._connection = None
        self._channel = None
        # Establish connection
        self._connect(**kwargs)

    def _connect(self, **kwargs):
        """Establish connection to RabbitMQ broker."""
        credentials = None
        if self._username and self._password:
            credentials = pika.PlainCredentials(self._username, self._password)
        connection_params = pika.ConnectionParameters(
            host=self._host, port=self._port, credentials=credentials, **kwargs)
        try:
            self._connection = pika.BlockingConnection(connection_params)
            self._channel = self._connection.channel()
            self._channel.queue_declare(queue=self._topic, durable=self._durable)
            self._channel.basic_qos(prefetch_count=self._prefetch_count)
            self._logger.info("RabbitMQ consumer connected successfully")
        except AMQPConnectionError as e:
            self._logger.error("Failed to connect to RabbitMQ: %s", str(e))
            raise e
        except Exception as e:
            self._logger.error("Failed to initialize RabbitMQ consumer: %s", str(e))
            raise e

    def _ensure_connection(self):
        """Ensure connection is active, reconnect if necessary."""
        if self._connection is None or self._connection.is_closed:
            self._logger.info("Reconnecting to RabbitMQ...")
            self._connect()
        elif self._channel is None or self._channel.is_closed:
            self._logger.info("Reopening RabbitMQ channel...")
            self._channel = self._connection.channel()
            self._channel.queue_declare(queue=self._topic, durable=self._durable)
            self._channel.basic_qos(prefetch_count=self._prefetch_count)

    def consume_messages(
            self,
            timeout_seconds: Optional[float] = 10.0,
            max_messages: Optional[int] = None,
            queue_name: Optional[str] = None,
            **kwargs
    ) -> Generator:
        """
        Generator that yields messages from RabbitMQ queue.
        
        Args:
            timeout_seconds: Timeout for consuming messages in seconds.
            max_messages: Maximum number of messages to consume (None for unlimited).
            queue_name: Queue name to consume from (defaults to instance topic).
            
        Yields:
            Deserialized message values.
        """
        target_queue = queue_name or self._topic
        message_count = 0

        try:
            self._ensure_connection()
            while True:
                if max_messages is not None and message_count >= max_messages:
                    self._logger.info("Reached maximum message limit: %d", max_messages)
                    break
                try:
                    method_frame, _, body = self._channel.basic_get(
                        queue=target_queue,
                        auto_ack=self._auto_ack
                    )
                    if method_frame is None:
                        # No message available, wait and continue
                        if timeout_seconds:
                            time.sleep(min(timeout_seconds, 1.0))
                        continue

                    try:
                        # Deserialize the message
                        deserialized_value = self._value_deserializer(body)
                        self._logger.debug(
                            "Received message from queue=%s delivery_tag=%s",
                            target_queue,
                            method_frame.delivery_tag
                        )
                        # Yield the message with acknowledgment info
                        yield deserialized_value
                        # Acknowledge the message if not auto-ack
                        if not self._auto_ack:
                            self._channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                        message_count += 1

                    except Exception as e:
                        self._logger.error("Error processing message: %s", str(e))
                        # Reject the message if not auto-ack
                        if not self._auto_ack and method_frame:
                            self._channel.basic_nack(
                                delivery_tag=method_frame.delivery_tag,
                                requeue=False
                            )

                except (AMQPConnectionError, ConnectionClosed) as e:
                    self._logger.error("RabbitMQ connection error: %s", str(e))
                    time.sleep(5)
                    self._ensure_connection()
                except AMQPChannelError as e:
                    self._logger.error("RabbitMQ channel error: %s", str(e))
                    time.sleep(2)
                    self._ensure_connection()
                except Exception as e:
                    self._logger.error("Unexpected error during message consumption: %s", str(e))
                    time.sleep(2)
                    self._ensure_connection()

        except KeyboardInterrupt:
            self._logger.info("Consumer stopped by user")
        except Exception as e:
            self._logger.error("Fatal error in message consumption: %s", str(e))
            raise e

    def acknowledge_message(self, delivery_tag: int) -> bool:
        """
        Manually acknowledge a message.
        
        Args:
            delivery_tag: Delivery tag of the message to acknowledge.
            
        Returns:
            True if acknowledgment was successful, False otherwise.
        """
        try:
            self._ensure_connection()
            self._channel.basic_ack(delivery_tag=delivery_tag)
            self._logger.debug("Message acknowledged: delivery_tag=%s", delivery_tag)
            return True
        except Exception as e:
            self._logger.error("Failed to acknowledge message: %s", str(e))
            return False

    def reject_message(self, delivery_tag: int, requeue: bool = True) -> bool:
        """
        Reject a message.
        
        Args:
            delivery_tag: Delivery tag of the message to reject.
            requeue: Whether to requeue the message.
            
        Returns:
            True if rejection was successful, False otherwise.
        """
        try:
            self._ensure_connection()
            self._channel.basic_nack(delivery_tag=delivery_tag, requeue=requeue)
            self._logger.debug("Message rejected: delivery_tag=%s requeue=%s", delivery_tag, requeue)
            return True
        except Exception as e:
            self._logger.error("Failed to reject message: %s", str(e))
            return False

    def close(self, **kwargs):
        """
        Close the consumer and release resources.
        """
        try:
            if self._channel and not self._channel.is_closed:
                self._channel.close()
                self._logger.debug("RabbitMQ channel closed")
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                self._logger.info("RabbitMQ consumer closed successfully")
        except Exception as e:
            self._logger.error("Error closing RabbitMQ consumer: %s", str(e))
        finally:
            self._channel = None
            self._connection = None
