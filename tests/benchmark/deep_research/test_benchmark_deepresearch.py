import unittest
import os
import re
import pytest
import argparse
import sys
from mcpuniverse.tracer.collectors import FileCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner
from mcpuniverse.benchmark.report import BenchmarkReport
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks

# Module-level variable to store benchmark name from command line
BENCHMARK_YAML = None
# SPECIAL_NAME = None


class TestBenchmarkRunner(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        if BENCHMARK_YAML is None:
            raise ValueError(
                "Benchmark yaml must be provided as a command-line argument"
            )

        # Extract a general benchmark name by removing the trailing underscore and number sequence
        benchmark_name = os.path.basename(BENCHMARK_YAML).replace(".yaml", "")
        benchmark_name_folder = re.sub(r"_\d+$", "", benchmark_name)
        # if SPECIAL_NAME is not None:
        #     benchmark_name_folder = f"{benchmark_name_folder}_{SPECIAL_NAME}"
        trace_collector = FileCollector(
            log_file=f"log/{benchmark_name_folder}/{benchmark_name}.log"
        )
        benchmark = BenchmarkRunner(BENCHMARK_YAML)
        results = await benchmark.run(
            trace_collector=trace_collector, callbacks=get_vprint_callbacks()
        )
        print(results)

        report = BenchmarkReport(
            benchmark,
            trace_collector=trace_collector,
            log_dir=f"{benchmark_name_folder}_report",
            log_name=benchmark_name,
        )
        report.dump()

        print("=" * 66)
        print("Evaluation Result")
        print("-" * 66)
        for task_name in results[0].task_results.keys():
            print(task_name)
            print("-" * 66)
            eval_results = results[0].task_results[task_name]["evaluation_results"]
            for eval_result in eval_results:
                print("func:", eval_result.config.func)
                print("op:", eval_result.config.op)
                print("op_args:", eval_result.config.op_args)
                print("value:", eval_result.config.value)
                print(
                    "Passed?:",
                    (
                        "\033[32mTrue\033[0m"
                        if eval_result.passed
                        else "\033[31mFalse\033[0m"
                    ),
                )
                print("-" * 66)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run benchmark tests")
    parser.add_argument(
        "benchmark_yaml",
        type=str,
        help="YAML file of the benchmark to run (e.g., test/deepresearch/seal_0_test_fc_v3.yaml)",
    )
    # parser.add_argument(
    #     'special_name',
    #     type=str,
    #     help='Special name of the benchmark to run',
    #     default=None)
    args, remaining_args = parser.parse_known_args()

    # Set the module-level benchmark name
    BENCHMARK_YAML = args.benchmark_yaml
    # SPECIAL_NAME = args.special_name

    # Pass remaining args to unittest (remove the script name and
    # benchmark_yaml)
    sys.argv = [sys.argv[0]] + remaining_args
    unittest.main()
