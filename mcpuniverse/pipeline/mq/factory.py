"""Message queue factory for creating producers and consumers."""

import os
from typing import Callable, Literal
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.pipeline.mq.base import BaseProducer, BaseConsumer
from mcpuniverse.pipeline.mq.kafka_producer import Producer as KafkaProducer
from mcpuniverse.pipeline.mq.kafka_consumer import Consumer as KafkaConsumer

MQType = Literal["kafka", "rabbitmq"]


class MQFactory(metaclass=AutodocABCMeta):
    """Factory for creating message queue producers and consumers."""

    @staticmethod
    def create_producer(
            mq_type: MQType,
            host: str,
            port: str,
            topic: str,
            value_serializer: Callable,
            **kwargs
    ) -> BaseProducer:
        """
        Create a producer with default configuration.
        
        Args:
            mq_type: Message queue type ('kafka' or 'rabbitmq').
            host: Broker host.
            port: Broker port.
            topic: Default topic for messages.
            value_serializer: Function to serialize message values.
            **kwargs: Additional producer configuration.
            
        Returns:
            Configured producer instance.
            
        Raises:
            ValueError: If unsupported MQ type is specified.
        """
        if mq_type == "kafka":
            return KafkaProducer(
                host=host or os.environ.get("KAFKA_HOST", "localhost"),
                port=port or int(os.environ.get("KAFKA_PORT", 9092)),
                topic=topic,
                value_serializer=value_serializer,
                **kwargs
            )
        if mq_type == "rabbitmq":
            raise NotImplementedError("RabbitMQ producer not yet implemented")
        raise ValueError(f"Unsupported MQ type: {mq_type}")

    @staticmethod
    def create_consumer(
            mq_type: MQType,
            host: str,
            port: str,
            topic: str,
            value_deserializer: Callable,
            **kwargs
    ) -> BaseConsumer:
        """
        Create a consumer with default configuration.
        
        Args:
            mq_type: Message queue type ('kafka' or 'rabbitmq').
            host: Broker host.
            port: Broker port.
            topic: Topic to subscribe to.
            value_deserializer: Function to deserialize message values.
            **kwargs: Additional consumer configuration.
            
        Returns:
            Configured consumer instance.
            
        Raises:
            ValueError: If unsupported MQ type is specified.
        """
        if mq_type == "kafka":
            return KafkaConsumer(
                host=host or os.environ.get("KAFKA_HOST", "localhost"),
                port=port or int(os.environ.get("KAFKA_PORT", 9092)),
                topic=topic,
                value_deserializer=value_deserializer,
                **kwargs
            )
        if mq_type == "rabbitmq":
            raise NotImplementedError("RabbitMQ consumer not yet implemented")
        raise ValueError(f"Unsupported MQ type: {mq_type}")
