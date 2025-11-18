"""Test functions for MCPMark filesystem evaluators."""
import os
import unittest
import pytest
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator.mcpmark.filesystem_functions import *


class TestFunctionsMCPMarkFilesystem(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPMark filesystem evaluator functions."""

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))
        self.config_folder = os.path.join(
            self.folder,
            "../../mcpuniverse/benchmark/configs/test/mcpmark/filesystem"
        )

    # Desktop category tests
    @pytest.mark.skip
    async def test_desktop_music_report(self):
        """ this function is for desktop/music_report.json"""
        config_file = os.path.join(self.config_folder, "desktop/music_report.json")
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
    async def test_desktop_project_management(self):
        """ this function is for desktop/project_management.json"""
        config_file = os.path.join(self.config_folder, "desktop/project_management.json")
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
    async def test_desktop_timeline_extraction(self):
        """ this function is for desktop/timeline_extraction.json"""
        config_file = os.path.join(self.config_folder, "desktop/timeline_extraction.json")
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

    # Desktop Template category tests
    @pytest.mark.skip
    async def test_desktop_template_budget_computation(self):
        """ this function is for desktop_template/budget_computation.json"""
        config_file = os.path.join(self.config_folder, "desktop_template/budget_computation.json")
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
    async def test_desktop_template_contact_information(self):
        """ this function is for desktop_template/contact_information.json"""
        config_file = os.path.join(self.config_folder, "desktop_template/contact_information.json")
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
    async def test_desktop_template_file_arrangement(self):
        """ this function is for desktop_template/file_arrangement.json"""
        config_file = os.path.join(self.config_folder, "desktop_template/file_arrangement.json")
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

    # File Context category tests
    @pytest.mark.skip
    async def test_file_context_duplicates_searching(self):
        """ this function is for file_context/duplicates_searching.json"""
        config_file = os.path.join(self.config_folder, "file_context/duplicates_searching.json")
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
    async def test_file_context_file_merging(self):
        """ this function is for file_context/file_merging.json"""
        config_file = os.path.join(self.config_folder, "file_context/file_merging.json")
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
    async def test_file_context_file_splitting(self):
        """ this function is for file_context/file_splitting.json"""
        config_file = os.path.join(self.config_folder, "file_context/file_splitting.json")
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
    async def test_file_context_pattern_matching(self):
        """ this function is for file_context/pattern_matching.json"""
        config_file = os.path.join(self.config_folder, "file_context/pattern_matching.json")
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
    async def test_file_context_uppercase(self):
        """ this function is for file_context/uppercase.json"""
        config_file = os.path.join(self.config_folder, "file_context/uppercase.json")
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

    # File Property category tests
    @pytest.mark.skip
    async def test_file_property_size_classification(self):
        """ this function is for file_property/size_classification.json"""
        config_file = os.path.join(self.config_folder, "file_property/size_classification.json")
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
    async def test_file_property_time_classification(self):
        """ this function is for file_property/time_classification.json"""
        config_file = os.path.join(self.config_folder, "file_property/time_classification.json")
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

    # Folder Structure category tests
    @pytest.mark.skip
    async def test_folder_structure_structure_analysis(self):
        """ this function is for folder_structure/structure_analysis.json"""
        config_file = os.path.join(self.config_folder, "folder_structure/structure_analysis.json")
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
    async def test_folder_structure_structure_mirror(self):
        """ this function is for folder_structure/structure_mirror.json"""
        config_file = os.path.join(self.config_folder, "folder_structure/structure_mirror.json")
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

    # Legal Document category tests
    @pytest.mark.skip
    async def test_legal_document_dispute_review(self):
        """ this function is for legal_document/dispute_review.json"""
        config_file = os.path.join(self.config_folder, "legal_document/dispute_review.json")
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
    async def test_legal_document_individual_comments(self):
        """ this function is for legal_document/individual_comments.json"""
        config_file = os.path.join(self.config_folder, "legal_document/individual_comments.json")
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
    async def test_legal_document_solution_tracing(self):
        """ this function is for legal_document/solution_tracing.json"""
        config_file = os.path.join(self.config_folder, "legal_document/solution_tracing.json")
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

    # Papers category tests
    @pytest.mark.skip
    async def test_papers_author_folders(self):
        """ this function is for papers/author_folders.json"""
        config_file = os.path.join(self.config_folder, "papers/author_folders.json")
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
    async def test_papers_find_math_paper(self):
        """ this function is for papers/find_math_paper.json"""
        config_file = os.path.join(self.config_folder, "papers/find_math_paper.json")
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
    async def test_papers_organize_legacy_papers(self):
        """ this function is for papers/organize_legacy_papers.json"""
        config_file = os.path.join(self.config_folder, "papers/organize_legacy_papers.json")
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

    # Student Database category tests
    @pytest.mark.skip
    async def test_student_database_duplicate_name(self):
        """ this function is for student_database/duplicate_name.json"""
        config_file = os.path.join(self.config_folder, "student_database/duplicate_name.json")
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
    async def test_student_database_english_talent(self):
        """ this function is for student_database/english_talent.json"""
        config_file = os.path.join(self.config_folder, "student_database/english_talent.json")
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
    async def test_student_database_gradebased_score(self):
        """ this function is for student_database/gradebased_score.json"""
        config_file = os.path.join(self.config_folder, "student_database/gradebased_score.json")
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

    # ThreeStudio category tests
    @pytest.mark.skip
    async def test_threestudio_code_locating(self):
        """ this function is for threestudio/code_locating.json"""
        config_file = os.path.join(self.config_folder, "threestudio/code_locating.json")
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
    async def test_threestudio_output_analysis(self):
        """ this function is for threestudio/output_analysis.json"""
        config_file = os.path.join(self.config_folder, "threestudio/output_analysis.json")
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
    async def test_threestudio_requirements_completion(self):
        """ this function is for threestudio/requirements_completion.json"""
        config_file = os.path.join(self.config_folder, "threestudio/requirements_completion.json")
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

    # VoteNet category tests
    @pytest.mark.skip
    async def test_votenet_dataset_comparison(self):
        """ this function is for votenet/dataset_comparison.json"""
        config_file = os.path.join(self.config_folder, "votenet/dataset_comparison.json")
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
    async def test_votenet_debugging(self):
        """ this function is for votenet/debugging.json"""
        config_file = os.path.join(self.config_folder, "votenet/debugging.json")
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
    async def test_votenet_requirements_writing(self):
        """ this function is for votenet/requirements_writing.json"""
        config_file = os.path.join(self.config_folder, "votenet/requirements_writing.json")
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
