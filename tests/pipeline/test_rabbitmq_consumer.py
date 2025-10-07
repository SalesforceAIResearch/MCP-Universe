import os
import unittest
import pytest
import json
from dotenv import load_dotenv
from mcpuniverse.pipeline.mq.rabbitmq_consumer import Consumer

load_dotenv()


class TestMQConsumer(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        consumer = Consumer(
            host=os.environ.get("RABBITMQ_HOST", "localhost"),
            port=int(os.environ.get("RABBITMQ_PORT", 5672)),
            topic="drivers",
            value_deserializer=lambda x: json.loads(x.decode("utf-8"))
        )
        for location in consumer.consume_messages():
            driver_id = location['driver_id']
            latitude = location['latitude']
            longitude = location['longitude']
            timestamp = location['timestamp']
            print(f"Received location update for Driver {driver_id}: ({latitude}, {longitude}) at {timestamp}")


if __name__ == "__main__":
    unittest.main()
