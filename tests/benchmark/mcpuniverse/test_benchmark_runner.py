import os
import unittest
import pytest
import pprint
from mcpuniverse.tracer.collectors import MemoryCollector
from mcpuniverse.benchmark.runner import (
    BenchmarkRunner,
    BenchmarkResultStore,
    BenchmarkConfig,
    EvaluationResult
)
from mcpuniverse.evaluator.evaluator import EvaluatorConfig

class TestBenchmarkRunner(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        trace_collector = MemoryCollector()
        benchmark = BenchmarkRunner("dummy/benchmark_1.yaml")
        results = await benchmark.run(
            trace_collector=trace_collector,
            store_folder=os.path.join(folder, "tmp")
        )
        print(results)
        trace_id = results[0].task_trace_ids["dummy/tasks/weather_1.json"]
        pprint.pprint(trace_collector.get(trace_id))

    @unittest.skip("skip")
    async def test_benchmark_result_store(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        store = BenchmarkResultStore(folder=os.path.join(folder, "tmp"))
        benchmark = BenchmarkConfig(
            description="test test",
            agent="test_agent",
            tasks=["google-map"]
        )
        store.dump_task_result(
            benchmark=benchmark,
            task_config_path=os.path.join(folder, "../data/task/weather_task.json"),
            evaluation_results=[
                EvaluationResult(
                    config=EvaluatorConfig(
                        func="get(key1) -> foreach -> get(key2)"
                    ),
                    response="response",
                    passed=True,
                    reason="testing",
                    error=""
                )
            ],
            trace_id="12345",
            overwrite=True
        )
        r = store.load_task_result(
            benchmark=benchmark,
            task_config_path=os.path.join(folder, "../data/task/weather_task.json")
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["trace_id"], "12345")
        self.assertEqual(r["results"][0].config.func, "get(key1) -> foreach -> get(key2)")
        self.assertEqual(r["results"][0].reason, "testing")


if __name__ == "__main__":
    unittest.main()
