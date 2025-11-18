"""Test functions for MCPMark GitHub evaluators."""
import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.mcpmark.github_functions import *


class TestFunctionsMCPMarkGitHub(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPMark GitHub evaluator functions."""

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/github"
        )

    # Build Your Own X category tests
    @pytest.mark.skip
    async def test_build_your_own_x_find_commit_date(self):
        """this function is for build_your_own_x/find_commit_date.json"""
        config_file = os.path.join(
            self.config_folder, "build_your_own_x/find_commit_date.json"
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
    async def test_build_your_own_x_find_rag_commit(self):
        """this function is for build_your_own_x/find_rag_commit.json"""
        config_file = os.path.join(
            self.config_folder, "build_your_own_x/find_rag_commit.json"
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

    # Claude Code category tests
    @pytest.mark.skip
    async def test_claude_code_automated_changelog_generation(self):
        """this function is for claude_code/automated_changelog_generation.json"""
        config_file = os.path.join(
            self.config_folder,
            "claude_code/automated_changelog_generation.json"
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
    async def test_claude_code_claude_collaboration_analysis(self):
        """this function is for claude_code/claude_collaboration_analysis.json"""
        config_file = os.path.join(
            self.config_folder,
            "claude_code/claude_collaboration_analysis.json"
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
    async def test_claude_code_critical_issue_hotfix_workflow(self):
        """this function is for claude_code/critical_issue_hotfix_workflow.json"""
        config_file = os.path.join(
            self.config_folder,
            "claude_code/critical_issue_hotfix_workflow.json"
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
    async def test_claude_code_feature_commit_tracking(self):
        """this function is for claude_code/feature_commit_tracking.json"""
        config_file = os.path.join(
            self.config_folder, "claude_code/feature_commit_tracking.json"
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
    async def test_claude_code_label_color_standardization(self):
        """this function is for claude_code/label_color_standardization.json"""
        config_file = os.path.join(
            self.config_folder,
            "claude_code/label_color_standardization.json"
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

    # EasyR1 category tests
    @pytest.mark.skip
    async def test_easyr1_advanced_branch_strategy(self):
        """this function is for easyr1/advanced_branch_strategy.json"""
        config_file = os.path.join(
            self.config_folder, "easyr1/advanced_branch_strategy.json"
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
    async def test_easyr1_config_parameter_audit(self):
        """this function is for easyr1/config_parameter_audit.json"""
        config_file = os.path.join(
            self.config_folder, "easyr1/config_parameter_audit.json"
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
    async def test_easyr1_performance_regression_investigation(self):
        """this function is for easyr1/performance_regression_investigation.json"""
        config_file = os.path.join(
            self.config_folder,
            "easyr1/performance_regression_investigation.json"
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
    async def test_easyr1_qwen3_issue_management(self):
        """this function is for easyr1/qwen3_issue_management.json"""
        config_file = os.path.join(
            self.config_folder, "easyr1/qwen3_issue_management.json"
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

    # Harmony category tests
    @pytest.mark.skip
    async def test_harmony_fix_conflict(self):
        """this function is for harmony/fix_conflict.json"""
        config_file = os.path.join(
            self.config_folder, "harmony/fix_conflict.json"
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
    async def test_harmony_issue_pr_commit_workflow(self):
        """this function is for harmony/issue_pr_commit_workflow.json"""
        config_file = os.path.join(
            self.config_folder, "harmony/issue_pr_commit_workflow.json"
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
    async def test_harmony_issue_tagging_pr_closure(self):
        """this function is for harmony/issue_tagging_pr_closure.json"""
        config_file = os.path.join(
            self.config_folder, "harmony/issue_tagging_pr_closure.json"
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
    async def test_harmony_multi_branch_commit_aggregation(self):
        """this function is for harmony/multi_branch_commit_aggregation.json"""
        config_file = os.path.join(
            self.config_folder,
            "harmony/multi_branch_commit_aggregation.json"
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
    async def test_harmony_release_management_workflow(self):
        """this function is for harmony/release_management_workflow.json"""
        config_file = os.path.join(
            self.config_folder, "harmony/release_management_workflow.json"
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

    # MCPMark CI/CD category tests
    @pytest.mark.skip
    async def test_mcpmark_cicd_deployment_status_workflow(self):
        """this function is for mcpmark_cicd/deployment_status_workflow.json"""
        config_file = os.path.join(
            self.config_folder,
            "mcpmark_cicd/deployment_status_workflow.json"
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
    async def test_mcpmark_cicd_issue_management_workflow(self):
        """this function is for mcpmark_cicd/issue_management_workflow.json"""
        config_file = os.path.join(
            self.config_folder,
            "mcpmark_cicd/issue_management_workflow.json"
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
    async def test_mcpmark_cicd_linting_ci_workflow(self):
        """this function is for mcpmark_cicd/linting_ci_workflow.json"""
        config_file = os.path.join(
            self.config_folder, "mcpmark_cicd/linting_ci_workflow.json"
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
    async def test_mcpmark_cicd_pr_automation_workflow(self):
        """this function is for mcpmark_cicd/pr_automation_workflow.json"""
        config_file = os.path.join(
            self.config_folder, "mcpmark_cicd/pr_automation_workflow.json"
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

    # Missing Semester category tests
    @pytest.mark.skip
    async def test_missing_semester_assign_contributor_labels(self):
        """this function is for missing_semester/assign_contributor_labels.json"""
        config_file = os.path.join(
            self.config_folder,
            "missing_semester/assign_contributor_labels.json"
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
    async def test_missing_semester_find_legacy_name(self):
        """this function is for missing_semester/find_legacy_name.json"""
        config_file = os.path.join(
            self.config_folder, "missing_semester/find_legacy_name.json"
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
    async def test_missing_semester_find_salient_file(self):
        """this function is for missing_semester/find_salient_file.json"""
        config_file = os.path.join(
            self.config_folder, "missing_semester/find_salient_file.json"
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
