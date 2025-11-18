"""Test functions for MCPMark Postgres evaluators."""
import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.mcpmark.postgres_functions import *


class TestFunctionsMCPMarkPostgres(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPMark Postgres evaluator functions."""

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/postgres"
        )

    # Chinook category tests
    @pytest.mark.skip
    async def test_chinook_customer_data_migration(self):
        """this function is for chinook/customer_data_migration.json"""
        config_file = os.path.join(
            self.config_folder, "chinook/customer_data_migration.json"
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
    async def test_chinook_employee_hierarchy_management(self):
        """this function is for chinook/employee_hierarchy_management.json"""
        config_file = os.path.join(
            self.config_folder,
            "chinook/employee_hierarchy_management.json"
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
    async def test_chinook_sales_and_music_charts(self):
        """this function is for chinook/sales_and_music_charts.json"""
        config_file = os.path.join(
            self.config_folder, "chinook/sales_and_music_charts.json"
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

    # DVDRental category tests
    @pytest.mark.skip
    async def test_dvdrental_customer_analysis_fix(self):
        """this function is for dvdrental/customer_analysis_fix.json"""
        config_file = os.path.join(
            self.config_folder, "dvdrental/customer_analysis_fix.json"
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
    async def test_dvdrental_customer_analytics_optimization(self):
        """this function is for dvdrental/customer_analytics_optimization.json"""
        config_file = os.path.join(
            self.config_folder,
            "dvdrental/customer_analytics_optimization.json"
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
    async def test_dvdrental_film_inventory_management(self):
        """this function is for dvdrental/film_inventory_management.json"""
        config_file = os.path.join(
            self.config_folder, "dvdrental/film_inventory_management.json"
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

    # Employees category tests
    @pytest.mark.skip
    async def test_employees_employee_demographics_report(self):
        """this function is for employees/employee_demographics_report.json"""
        config_file = os.path.join(
            self.config_folder,
            "employees/employee_demographics_report.json"
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
    async def test_employees_employee_performance_analysis(self):
        """this function is for employees/employee_performance_analysis.json"""
        config_file = os.path.join(
            self.config_folder,
            "employees/employee_performance_analysis.json"
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
    async def test_employees_employee_project_tracking(self):
        """this function is for employees/employee_project_tracking.json"""
        config_file = os.path.join(
            self.config_folder, "employees/employee_project_tracking.json"
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
    async def test_employees_employee_retention_analysis(self):
        """this function is for employees/employee_retention_analysis.json"""
        config_file = os.path.join(
            self.config_folder, "employees/employee_retention_analysis.json"
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
    async def test_employees_executive_dashboard_automation(self):
        """this function is for employees/executive_dashboard_automation.json"""
        config_file = os.path.join(
            self.config_folder,
            "employees/executive_dashboard_automation.json"
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
    async def test_employees_management_structure_analysis(self):
        """this function is for employees/management_structure_analysis.json"""
        config_file = os.path.join(
            self.config_folder,
            "employees/management_structure_analysis.json"
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

    # Lego category tests
    @pytest.mark.skip
    async def test_lego_consistency_enforcement(self):
        """this function is for lego/consistency_enforcement.json"""
        config_file = os.path.join(
            self.config_folder, "lego/consistency_enforcement.json"
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
    async def test_lego_database_security_policies(self):
        """this function is for lego/database_security_policies.json"""
        config_file = os.path.join(
            self.config_folder, "lego/database_security_policies.json"
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
    async def test_lego_transactional_inventory_transfer(self):
        """this function is for lego/transactional_inventory_transfer.json"""
        config_file = os.path.join(
            self.config_folder,
            "lego/transactional_inventory_transfer.json"
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

    # Security category tests
    @pytest.mark.skip
    async def test_security_rls_business_access(self):
        """this function is for security/rls_business_access.json"""
        config_file = os.path.join(
            self.config_folder, "security/rls_business_access.json"
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
    async def test_security_user_permission_audit(self):
        """this function is for security/user_permission_audit.json"""
        config_file = os.path.join(
            self.config_folder, "security/user_permission_audit.json"
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

    # Sports category tests
    @pytest.mark.skip
    async def test_sports_baseball_player_analysis(self):
        """this function is for sports/baseball_player_analysis.json"""
        config_file = os.path.join(
            self.config_folder, "sports/baseball_player_analysis.json"
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
    async def test_sports_participant_report_optimization(self):
        """this function is for sports/participant_report_optimization.json"""
        config_file = os.path.join(
            self.config_folder,
            "sports/participant_report_optimization.json"
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
    async def test_sports_team_roster_management(self):
        """this function is for sports/team_roster_management.json"""
        config_file = os.path.join(
            self.config_folder, "sports/team_roster_management.json"
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

    # Vectors category tests
    @pytest.mark.skip
    async def test_vectors_dba_vector_analysis(self):
        """this function is for vectors/dba_vector_analysis.json"""
        config_file = os.path.join(
            self.config_folder, "vectors/dba_vector_analysis.json"
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
