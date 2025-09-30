import unittest
import pytest
import json
import random
import time
from mcpuniverse.pipeline.mq.producer import Producer


class TestMQProducer(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        producer = Producer(
            host="localhost",
            port=9092,
            topic="driver-location",
            value_serializer=lambda v: json.dumps(v).encode("utf-8")
        )
        while True:
            location = {
                "driver_id": "abc",
                "latitude": round(random.uniform(40.0, 41.0), 6),
                "longitude": round(random.uniform(-74.0, -73.0), 6),
                "timestamp": time.time()
            }
            producer.send(location)
            time.sleep(5)


if __name__ == "__main__":
    unittest.main()
