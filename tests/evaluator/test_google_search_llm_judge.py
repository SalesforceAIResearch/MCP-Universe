import unittest
from unittest.mock import patch

from mcpuniverse.common.context import Context
from mcpuniverse.evaluator.google_search.functions import google_search__llm_as_a_judge


class TestGoogleSearchLlmAsAJudge(unittest.IsolatedAsyncioTestCase):

    @patch("mcpuniverse.evaluator.google_search.functions.call_judge_text")
    async def test_passes_when_judge_returns_correct_yes(self, mock_judge):
        mock_judge.return_value = (
            "extracted_final_answer: Paris\n"
            "reasoning: matches\n"
            "correct: yes"
        )
        passed, message = await google_search__llm_as_a_judge(
            "Paris",
            None,
            {"question": "Capital of France?", "correct_answer": "Paris"},
            context=Context(),
        )
        self.assertTrue(passed)
        self.assertEqual(message, "")
        mock_judge.assert_called_once()

    @patch("mcpuniverse.evaluator.google_search.functions.call_judge_text")
    async def test_fails_when_judge_returns_correct_no(self, mock_judge):
        mock_judge.return_value = (
            "extracted_final_answer: London\n"
            "reasoning: wrong city\n"
            "correct: no"
        )
        passed, message = await google_search__llm_as_a_judge(
            "London",
            None,
            {"question": "Capital of France?", "correct_answer": "Paris"},
            context=Context(),
        )
        self.assertFalse(passed)
        self.assertEqual(message, "output is not equal to ground-truth")


if __name__ == "__main__":
    unittest.main()
