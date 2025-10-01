import os
import unittest
import pytest
import json
import random
import time
from dotenv import load_dotenv
from mcpuniverse.pipeline.mq.kafka_producer import Producer

load_dotenv()


class TestMQProducer(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        producer = Producer(
            host=os.environ.get("KAFKA_HOST", "localhost"),
            port=int(os.environ.get("KAFKA_PORT", 9092)),
            topic="drivers",
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
            print(f"Sent {location}")
            time.sleep(5)


if __name__ == "__main__":
    unittest.main()
