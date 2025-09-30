import unittest
import pytest
import json
from mcpuniverse.pipeline.mq.consumer import Consumer


class TestMQConsumer(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        consumer = Consumer(
            host="localhost",
            port=9092,
            topic="driver-location",
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
