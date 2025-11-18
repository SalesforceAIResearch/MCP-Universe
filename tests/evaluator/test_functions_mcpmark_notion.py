"""Test functions for MCPMark Notion evaluators."""
import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.mcpmark.notion_functions import *


class TestFunctionsMCPMarkNotion(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPMark Notion evaluator functions."""

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/notion"
        )

    # Company In A Box category tests
    @pytest.mark.skip
    async def test_company_in_a_box_employee_onboarding(self):
        """this function is for company_in_a_box/employee_onboarding.json"""
        config_file = os.path.join(
            self.config_folder,
            "company_in_a_box/employee_onboarding.json"
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
    async def test_company_in_a_box_goals_restructure(self):
        """this function is for company_in_a_box/goals_restructure.json"""
        config_file = os.path.join(
            self.config_folder,
            "company_in_a_box/goals_restructure.json"
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
    async def test_company_in_a_box_quarterly_review_dashboard(self):
        """this function is for company_in_a_box/quarterly_review_dashboard.json"""
        config_file = os.path.join(
            self.config_folder,
            "company_in_a_box/quarterly_review_dashboard.json"
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

    # Computer Science Student Dashboard category tests
    @pytest.mark.skip
    async def test_computer_science_student_dashboard_code_snippets_go(self):
        """this function is for computer_science_student_dashboard/code_snippets_go.json"""
        config_file = os.path.join(
            self.config_folder,
            "computer_science_student_dashboard/code_snippets_go.json"
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
    async def test_computer_science_student_dashboard_courses_internships_relation(self):
        """this function is for computer_science_student_dashboard/
        courses_internships_relation.json"""
        config_file = os.path.join(
            self.config_folder,
            "computer_science_student_dashboard/"
            "courses_internships_relation.json"
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
    async def test_computer_science_student_dashboard_study_session_tracker(self):
        """this function is for computer_science_student_dashboard/study_session_tracker.json"""
        config_file = os.path.join(
            self.config_folder,
            "computer_science_student_dashboard/study_session_tracker.json"
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

    # IT Trouble Shooting Hub category tests
    @pytest.mark.skip
    async def test_it_trouble_shooting_hub_asset_retirement_migration(self):
        """this function is for it_trouble_shooting_hub/asset_retirement_migration.json"""
        config_file = os.path.join(
            self.config_folder,
            "it_trouble_shooting_hub/asset_retirement_migration.json"
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
    async def test_it_trouble_shooting_hub_security_audit_ticket(self):
        """this function is for it_trouble_shooting_hub/security_audit_ticket.json"""
        config_file = os.path.join(
            self.config_folder,
            "it_trouble_shooting_hub/security_audit_ticket.json"
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
    async def test_it_trouble_shooting_hub_verification_expired_update(self):
        """this function is for it_trouble_shooting_hub/verification_expired_update.json"""
        config_file = os.path.join(
            self.config_folder,
            "it_trouble_shooting_hub/verification_expired_update.json"
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

    # Japan Travel Planner category tests
    @pytest.mark.skip
    async def test_japan_travel_planner_daily_itinerary_overview(self):
        """this function is for japan_travel_planner/daily_itinerary_overview.json"""
        config_file = os.path.join(
            self.config_folder,
            "japan_travel_planner/daily_itinerary_overview.json"
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
    async def test_japan_travel_planner_packing_progress_summary(self):
        """this function is for japan_travel_planner/packing_progress_summary.json"""
        config_file = os.path.join(
            self.config_folder,
            "japan_travel_planner/packing_progress_summary.json"
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
    async def test_japan_travel_planner_remove_osaka_itinerary(self):
        """this function is for japan_travel_planner/remove_osaka_itinerary.json"""
        config_file = os.path.join(
            self.config_folder,
            "japan_travel_planner/remove_osaka_itinerary.json"
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
    async def test_japan_travel_planner_restaurant_expenses_sync(self):
        """this function is for japan_travel_planner/restaurant_expenses_sync.json"""
        config_file = os.path.join(
            self.config_folder,
            "japan_travel_planner/restaurant_expenses_sync.json"
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

    # Online Resume category tests
    @pytest.mark.skip
    async def test_online_resume_layout_adjustment(self):
        """this function is for online_resume/layout_adjustment.json"""
        config_file = os.path.join(
            self.config_folder, "online_resume/layout_adjustment.json"
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
    async def test_online_resume_projects_section_update(self):
        """this function is for online_resume/projects_section_update.json"""
        config_file = os.path.join(
            self.config_folder, "online_resume/projects_section_update.json"
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
    async def test_online_resume_skills_development_tracker(self):
        """this function is for online_resume/skills_development_tracker.json"""
        config_file = os.path.join(
            self.config_folder,
            "online_resume/skills_development_tracker.json"
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
    async def test_online_resume_work_history_addition(self):
        """this function is for online_resume/work_history_addition.json"""
        config_file = os.path.join(
            self.config_folder, "online_resume/work_history_addition.json"
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

    # Python Roadmap category tests
    @pytest.mark.skip
    async def test_python_roadmap_expert_level_lessons(self):
        """this function is for python_roadmap/expert_level_lessons.json"""
        config_file = os.path.join(
            self.config_folder, "python_roadmap/expert_level_lessons.json"
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
    async def test_python_roadmap_learning_metrics_dashboard(self):
        """this function is for python_roadmap/learning_metrics_dashboard.json"""
        config_file = os.path.join(
            self.config_folder,
            "python_roadmap/learning_metrics_dashboard.json"
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

    # Self Assessment category tests
    @pytest.mark.skip
    async def test_self_assessment_faq_column_layout(self):
        """this function is for self_assessment/faq_column_layout.json"""
        config_file = os.path.join(
            self.config_folder, "self_assessment/faq_column_layout.json"
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
    async def test_self_assessment_hyperfocus_analysis_report(self):
        """this function is for self_assessment/hyperfocus_analysis_report.json"""
        config_file = os.path.join(
            self.config_folder,
            "self_assessment/hyperfocus_analysis_report.json"
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
    async def test_self_assessment_numbered_list_emojis(self):
        """this function is for self_assessment/numbered_list_emojis.json"""
        config_file = os.path.join(
            self.config_folder, "self_assessment/numbered_list_emojis.json"
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

    # Standard Operating Procedure category tests
    @pytest.mark.skip
    async def test_standard_operating_procedure_deployment_process_sop(self):
        """this function is for standard_operating_procedure/deployment_process_sop.json"""
        config_file = os.path.join(
            self.config_folder,
            "standard_operating_procedure/deployment_process_sop.json"
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
    async def test_standard_operating_procedure_section_organization(self):
        """this function is for standard_operating_procedure/section_organization.json"""
        config_file = os.path.join(
            self.config_folder,
            "standard_operating_procedure/section_organization.json"
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

    # Team Projects category tests
    @pytest.mark.skip
    async def test_team_projects_priority_tasks_table(self):
        """this function is for team_projects/priority_tasks_table.json"""
        config_file = os.path.join(
            self.config_folder, "team_projects/priority_tasks_table.json"
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
    async def test_team_projects_swap_tasks(self):
        """this function is for team_projects/swap_tasks.json"""
        config_file = os.path.join(
            self.config_folder, "team_projects/swap_tasks.json"
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

    # Toronto Guide category tests
    @pytest.mark.skip
    async def test_toronto_guide_change_color(self):
        """this function is for toronto_guide/change_color.json"""
        config_file = os.path.join(
            self.config_folder, "toronto_guide/change_color.json"
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
    async def test_toronto_guide_weekend_adventure_planner(self):
        """this function is for toronto_guide/weekend_adventure_planner.json"""
        config_file = os.path.join(
            self.config_folder,
            "toronto_guide/weekend_adventure_planner.json"
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
