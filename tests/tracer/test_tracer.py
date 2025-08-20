import unittest
import time
from mcpuniverse.tracer import Tracer


class TestTracer(unittest.TestCase):

    def test(self):
        tracer = Tracer()
        with tracer.sprout() as tracer_a:
            tracer_a.add({"key": "a", "value": 1})
            tracer_a.add({"key": "b", "value": 2})
            time.sleep(0.5)
            with tracer_a.sprout() as tracer_b:
                tracer_b.add({"key": "c", "value": 3})
                tracer_b.add({"key": "d", "value": 4})
                time.sleep(0.5)
            with tracer_a.sprout() as tracer_c:
                tracer_c.add({"key": "e", "value": 5})
                tracer_c.add({"key": "f", "value": 6})
                time.sleep(0.5)
        records = tracer.get_trace()
        self.assertEqual(len(records), 3)
        self.assertEqual(len(records[0].records), 2)
        self.assertEqual(len(records[1].records), 2)
        self.assertEqual(len(records[2].records), 2)


if __name__ == "__main__":
    unittest.main()
