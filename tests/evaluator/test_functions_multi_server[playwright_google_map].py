import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.github.functions import *


class TestFunctionsExtra(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(self.folder, "../../mcpuniverse/benchmark/configs/test/multi_server")

    @pytest.mark.skip
    async def test_task_0005(self):
        """this function is for multi-server_task_playwright_google_map_0005.json"""
        llm_response = {
            "friend_city": "Aston, Birmingham",
            "my_city": "Liverpool",
            "hotel": {
                "name": "The Midland",
                "place id": "ChIJN1t_t3uEmsRkM73_67p73Y",
                "full address": "126-130 Poultry, London EC2R 8AA, United Kingdom"
            }
        }
        config_file = os.path.join(self.config_folder, "multi-server_task_playwright_google_map_0005.json")
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate(json.dumps(llm_response))
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
