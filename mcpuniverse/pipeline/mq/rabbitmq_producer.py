"""RabbitMQ message queue producer."""
# pylint: disable=broad-exception-caught
from typing import Callable, Any, Optional
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError, ConnectionClosed
from mcpuniverse.common.logger import get_logger
from mcpuniverse.pipeline.mq.base import BaseProducer


class Producer(BaseProducer):
    """
    Production-ready RabbitMQ producer with robust error handling and configuration.
    
    Provides reliable message publishing with proper connection management,
    retries, and comprehensive error handling.
    """

    def __init__(
            self,
            host: str,
            port: int,
            topic: str,
            value_serializer: Callable,
            username: Optional[str] = None,
            password: Optional[str] = None,
            exchange: str = "",
            durable: bool = True,
            **kwargs
    ):
        """
        Initialize RabbitMQ producer with production-ready settings.
        
        Args:
            host: RabbitMQ broker host.
            port: RabbitMQ broker port.
            topic: Default queue/topic for messages.
            value_serializer: Function to serialize message values.
            username: RabbitMQ username for authentication.
            password: RabbitMQ password for authentication.
            exchange: Exchange name (empty string for default exchange).
            durable: Whether to make queues durable.
            **kwargs: Additional pika connection parameters.
        """
        super().__init__(host=host, port=port, topic=topic, value_serializer=value_serializer)
        self._logger = get_logger(self.__class__.__name__)
        self._username = username
        self._password = password
        self._exchange = exchange
        self._durable = durable
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
            self._logger.info("RabbitMQ producer connected successfully")
        except AMQPConnectionError as e:
            self._logger.error("Failed to connect to RabbitMQ: %s", str(e))
            raise e
        except Exception as e:
            self._logger.error("Failed to initialize RabbitMQ producer: %s", str(e))
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

    def send(
            self,
            obj: Any,
            topic: Optional[str] = None,
            exchange: Optional[str] = None,
            properties: Optional[pika.BasicProperties] = None,
            **kwargs
    ) -> bool:
        """
        Send a message to RabbitMQ with robust error handling.
        
        Args:
            obj: Message value to send.
            topic: Queue name to send to (defaults to instance topic).
            exchange: Exchange to publish to (defaults to instance exchange).
            properties: Message properties.
            
        Returns:
            True if message sent successfully, False otherwise.
        """
        target_topic = topic or self._topic
        target_exchange = exchange if exchange is not None else self._exchange

        try:
            self._ensure_connection()
            serialized_message = self._value_serializer(obj)
            self._channel.queue_declare(queue=target_topic, durable=self._durable)
            self._channel.basic_publish(
                exchange=target_exchange,
                routing_key=target_topic,
                body=serialized_message,
                properties=properties
            )
            self._logger.debug(
                "Message sent successfully to exchange=%s routing_key=%s",
                target_exchange,
                target_topic
            )
            return True

        except (AMQPConnectionError, ConnectionClosed) as e:
            self._logger.error("RabbitMQ connection error sending to %s: %s", target_topic, str(e))
            return False
        except AMQPChannelError as e:
            self._logger.error("RabbitMQ channel error sending to %s: %s", target_topic, str(e))
            return False
        except Exception as e:
            self._logger.error("Unexpected error sending to %s: %s", target_topic, str(e))
            return False

    def send_persistent(
            self,
            obj: Any,
            topic: Optional[str] = None,
            exchange: Optional[str] = None,
            **kwargs
    ) -> bool:
        """
        Send a persistent message to RabbitMQ.
        
        Args:
            obj: Message value to send.
            topic: Queue name to send to (defaults to instance topic).
            exchange: Exchange to publish to (defaults to instance exchange).
            
        Returns:
            True if message sent successfully, False otherwise.
        """
        properties = pika.BasicProperties(delivery_mode=2)  # Make message persistent
        return self.send(
            obj=obj,
            topic=topic,
            exchange=exchange,
            properties=properties,
            **kwargs
        )

    def declare_queue(self, queue_name: str, durable: bool = True, **kwargs) -> bool:
        """
        Declare a queue.
        
        Args:
            queue_name: Name of the queue to declare.
            durable: Whether the queue should be durable.
            **kwargs: Additional queue declaration parameters.
            
        Returns:
            True if queue declared successfully, False otherwise.
        """
        try:
            self._ensure_connection()
            self._channel.queue_declare(queue=queue_name, durable=durable, **kwargs)
            self._logger.debug("Queue %s declared successfully", queue_name)
            return True
        except Exception as e:
            self._logger.error("Failed to declare queue %s: %s", queue_name, str(e))
            return False

    def declare_exchange(
            self,
            exchange_name: str,
            exchange_type: str = "direct",
            durable: bool = True,
            **kwargs
    ) -> bool:
        """
        Declare an exchange.
        
        Args:
            exchange_name: Name of the exchange to declare.
            exchange_type: Type of exchange (direct, topic, fanout, headers).
            durable: Whether the exchange should be durable.
            **kwargs: Additional exchange declaration parameters.
            
        Returns:
            True if exchange declared successfully, False otherwise.
        """
        try:
            self._ensure_connection()
            self._channel.exchange_declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                durable=durable,
                **kwargs
            )
            self._logger.debug("Exchange %s declared successfully", exchange_name)
            return True
        except Exception as e:
            self._logger.error("Failed to declare exchange %s: %s", exchange_name, str(e))
            return False

    def close(self, **kwargs):
        """
        Close the producer and release resources.
        """
        try:
            if self._channel and not self._channel.is_closed:
                self._channel.close()
                self._logger.debug("RabbitMQ channel closed")
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                self._logger.info("RabbitMQ producer closed successfully")
        except Exception as e:
            self._logger.error("Error closing RabbitMQ producer: %s", str(e))
        finally:
            self._channel = None
            self._connection = None
