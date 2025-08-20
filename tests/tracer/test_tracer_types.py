import unittest
from mcpuniverse.tracer.types import TraceRecord, DataRecord


class TestTracerTypes(unittest.TestCase):

    def test(self):
        record = TraceRecord(
            id="id",
            trace_id="trace_id",
            parent_id="parent_id",
            records=[
                DataRecord(
                    timestamp=1,
                    data={"a": 0, "b": 1}
                )
            ],
            running_time=1,
            timestamp=2,
            span_index=0
        )
        r = TraceRecord.from_json(record.to_json())
        self.assertEqual(record.id, r.id)
        self.assertEqual(record.trace_id, r.trace_id)
        self.assertEqual(record.parent_id, r.parent_id)
        self.assertEqual(type(r.records[0]), DataRecord)
        self.assertEqual(r.records[0].timestamp, 1)
        self.assertDictEqual(record.records[0].data, r.records[0].data)


if __name__ == "__main__":
    unittest.main()
