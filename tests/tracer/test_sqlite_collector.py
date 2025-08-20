import unittest
import pytest
from mcpuniverse.tracer.collectors.sqlite import SQLiteCollector
from mcpuniverse.tracer.types import TraceRecord, DataRecord


class TestSQLiteCollector(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        collector = SQLiteCollector()
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
        try:
            collector.insert(record)
        except:
            pass
        records = collector.get(trace_id="trace_id")
        self.assertEqual(len(records), 1)
        self.assertDictEqual(record.to_dict(), records[0].to_dict())


if __name__ == "__main__":
    unittest.main()
