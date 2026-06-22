import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.benchmark.mcpuniverse.evaluators.github.functions import *


class TestFunctionsExtra(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(self.folder, "../../mcpuniverse/benchmark/mcpuniverse/task_configs/repository_management")

    @pytest.mark.skip
    async def test_task_0001(self):
        config_file = os.path.join(self.config_folder, "github_task_0001.json")
        task = Task(config_file, benchmark_id='mcpuniverse')
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            print('Passed?:', "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m")
            print("reason:", eval_result.reason)
            print('-' * 66)


if __name__ == "__main__":
    unittest.main()
