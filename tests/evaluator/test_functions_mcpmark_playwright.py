"""Test functions for MCPMark Playwright evaluators."""
import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.mcpmark.playwright_functions import *


class TestFunctionsMCPMarkPlaywright(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPMark Playwright evaluator functions."""

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder_playwright = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/playwright"
        )
        self.config_folder_webarena = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/playwright_webarena"
        )

    # Playwright category tests
    @pytest.mark.skip
    async def test_playwright_eval_web_extraction_table(self):
        """this function is for playwright/eval_web-extraction_table.json"""
        config_file = os.path.join(
            self.config_folder_playwright,
            "eval_web-extraction_table.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_eval_web_cloudflare_turnstile_challenge(self):
        """this function is for playwright/eval_web-cloudflare_turnstile_challenge.json"""
        config_file = os.path.join(
            self.config_folder_playwright,
            "eval_web-cloudflare_turnstile_challenge.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_web_search_birth_of_arvinxu(self):
        """this function is for playwright/web_search-birth_of_arvinxu.json"""
        config_file = os.path.join(
            self.config_folder_playwright,
            "web_search-birth_of_arvinxu.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_web_search_r1_arxiv(self):
        """this function is for playwright/web_search-r1_arxiv.json"""
        config_file = os.path.join(
            self.config_folder_playwright,
            "web_search-r1_arxiv.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    # Playwright WebArena - Reddit category tests
    @pytest.mark.skip
    async def test_playwright_webarena_reddit_ai_data_analyst(self):
        """this function is for playwright_webarena/reddit/ai_data_analyst.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/ai_data_analyst.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_budget_europe_travel(self):
        """this function is for playwright_webarena/reddit/budget_europe_travel.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/budget_europe_travel.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_buyitforlife_research(self):
        """this function is for playwright_webarena/reddit/buyitforlife_research.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/buyitforlife_research.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_llm_research_summary(self):
        """this function is for playwright_webarena/reddit/llm_research_summary.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/llm_research_summary.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_movie_reviewer_analysis(self):
        """this function is for playwright_webarena/reddit/movie_reviewer_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/movie_reviewer_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_nba_statistics_analysis(self):
        """this function is for playwright_webarena/reddit/nba_statistics_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/nba_statistics_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_reddit_routine_tracker_forum(self):
        """this function is for playwright_webarena/reddit/routine_tracker_forum.json"""
        config_file = os.path.join(
            self.config_folder_webarena, "reddit/routine_tracker_forum.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    # Playwright WebArena - Shopping category tests
    @pytest.mark.skip
    async def test_playwright_webarena_shopping_advanced_product_analysis(self):
        """this function is for playwright_webarena/shopping/advanced_product_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/advanced_product_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_gaming_accessories_analysis(self):
        """this function is for playwright_webarena/shopping/gaming_accessories_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/gaming_accessories_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_health_routine_optimization(self):
        """this function is for playwright_webarena/shopping/health_routine_optimization.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/health_routine_optimization.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_holiday_baking_competition(self):
        """this function is for playwright_webarena/shopping/holiday_baking_competition.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/holiday_baking_competition.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_multi_category_budget_analysis(self):
        """this function is for playwright_webarena/shopping/multi_category_budget_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/multi_category_budget_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_printer_keyboard_search(self):
        """this function is for playwright_webarena/shopping/printer_keyboard_search.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/printer_keyboard_search.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_running_shoes_purchase(self):
        """this function is for playwright_webarena/shopping/running_shoes_purchase.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping/running_shoes_purchase.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    # Playwright WebArena - Shopping Admin category tests
    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_customer_segmentation_setup(self):
        """this function is for playwright_webarena/shopping_admin/
        customer_segmentation_setup.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/customer_segmentation_setup.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_fitness_promotion_strategy(self):
        """this function is for playwright_webarena/shopping_admin/
        fitness_promotion_strategy.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/fitness_promotion_strategy.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_marketing_customer_analysis(self):
        """this function is for playwright_webarena/shopping_admin/
        marketing_customer_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/marketing_customer_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_ny_expansion_analysis(self):
        """this function is for playwright_webarena/shopping_admin/ny_expansion_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/ny_expansion_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_products_sales_analysis(self):
        """this function is for playwright_webarena/shopping_admin/products_sales_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/products_sales_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_sales_inventory_analysis(self):
        """this function is for playwright_webarena/shopping_admin/sales_inventory_analysis.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/sales_inventory_analysis.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)

    @pytest.mark.skip
    async def test_playwright_webarena_shopping_admin_search_filtering_operations(self):
        """this function is for playwright_webarena/shopping_admin/
        search_filtering_operations.json"""
        config_file = os.path.join(
            self.config_folder_webarena,
            "shopping_admin/search_filtering_operations.json"
        )
        task = Task(config_file)
        print(task.get_evaluators())

        eval_results = await task.evaluate("")
        for eval_result in eval_results:
            print("func:", eval_result.config.func)
            print("op:", eval_result.config.op)
            print("op_args:", eval_result.config.op_args)
            print("value:", eval_result.config.value)
            passed_str = "\033[32mTrue\033[0m" if eval_result.passed else "\033[31mFalse\033[0m"
            print('Passed?:', passed_str)
            print("reason:", eval_result.reason)
            print('-' * 66)


if __name__ == "__main__":
    unittest.main()
