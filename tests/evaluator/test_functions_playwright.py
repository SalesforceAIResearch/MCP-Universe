import unittest
import os
import pytest
import json
from mcpuniverse.evaluator.playwright.functions import *
from mcpuniverse.benchmark.task import Task


class TestFunctionsExtra(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(self.folder, "../../mcpuniverse/benchmark/configs/test/multi_server")

    @unittest.skip("skip")
    async def test_func3(self):
        x = {
            "price": "SGD85.00"
        }
        value = ""
        op_args = {
            "days_after": 3,
            "theme_parks": ["USS", "ACW"],
            "adults": 2,
            "children": 1
        }
        resp = await playwright_check_rwsentosa_price_with_conditions(x, value, op_args)
        print(resp)

    @unittest.skip("skip")
    async def test_func5(self):
        """
        test_func5 to test playwright.check_flight_price function
        """
        config_folder = os.path.join(self.folder, "../../mcpuniverse/benchmark/configs/test/browser_automation")
        config_file = os.path.join(config_folder, "playwright_booking_task_0001.json")

        task = Task(config_file)
        print(task.get_evaluators())

        llm_response = {"price": "SGD85.00"}
        eval_results = await task.evaluate(json.dumps(llm_response))

        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            print('Passed?:', "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m")
            print("reason:", eval_result.reason)
            print('-' * 66)

    @unittest.skip("skip")
    async def test_func6(self):
        """
        test_func6 to test playwright.check_flight_price function
        """
        config_folder = os.path.join(self.folder, "../../mcpuniverse/benchmark/configs/test/browser_automation")
        config_file = os.path.join(config_folder, "playwright_booking_task_0003.json")

        task = Task(config_file)
        print(task.get_evaluators())

        llm_response = {"price": "SGD85.00"}
        eval_results = await task.evaluate(json.dumps(llm_response))

        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            print('Passed?:', "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m")
            print("reason:", eval_result.reason)
            print('-' * 66)

    @unittest.skip("skip")
    async def test_func7(self):
        """
        test_func7 to test playwright.get_flight_price_with_time function
        """
        price = await playwright__get_flight_price_with_time("2025-07-20")
        print(price)

        price = await playwright__get_flight_price(
            depart_date="2025-07-20",
            return_date="2025-07-26",
            from_location="LHR.AIRPORT",
            to_location="CDG.AIRPORT",
            from_country="GB",
            to_country="FR",
            from_location_name="London+Heathrow+Airport",
            to_location_name="Paris+-+Charles+de+Gaulle+Airport",
            flight_type="ROUNDTRIP",
            cabin_class="ECONOMY",
            adults=1,
            children=0,
            stops=0,
            sort="CHEAPEST",
            travel_purpose="leisure"
        )
        print(price)


if __name__ == "__main__":
    unittest.main()
