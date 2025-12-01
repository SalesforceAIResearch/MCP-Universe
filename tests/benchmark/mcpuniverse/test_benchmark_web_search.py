import unittest
import pytest
from mcpuniverse.tracer.collectors import FileCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner
from mcpuniverse.benchmark.report import BenchmarkReport
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks


class TestBenchmarkRunner(unittest.IsolatedAsyncioTestCase):

    async def test(self):
        trace_collector = FileCollector(log_file="log/mcpuniverse/web_search.log")
        benchmark = BenchmarkRunner("mcpuniverse/web_search.yaml")
        results = await benchmark.run(trace_collector=trace_collector, callbacks=get_vprint_callbacks())
        print(results)

        report = BenchmarkReport(benchmark, trace_collector=trace_collector)
        report.dump()

        print('=' * 66)
        print('Evaluation Result')
        print('-' * 66)
        for task_name in results[0].task_results.keys():
            print(task_name)
            print('-' * 66)
            eval_results = results[0].task_results[task_name]["evaluation_results"]
            for eval_result in eval_results:
                print("func:", eval_result.config.func)
                print("op:", eval_result.config.op)
                print("op_args:", eval_result.config.op_args)
                print("value:", eval_result.config.value)
                print('Passed?:', "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m")
                print('-' * 66)


if __name__ == "__main__":
    unittest.main()
