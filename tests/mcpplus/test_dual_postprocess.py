"""Tests for DualPostProcessAgent helper methods."""
import unittest
from unittest.mock import MagicMock, AsyncMock

from mcpuniverse.mcpplus.agent.react_dual_postprocess import (
    DualPostProcessAgent,
    DualPostProcessAgentConfig
)
from mcpuniverse.mcpplus.common.executor import SafeCodeExecutor


class TestDualPostProcessAgentConfig(unittest.TestCase):
    """Test cases for DualPostProcessAgentConfig."""

    def test_default_values(self):
        """Test default config values."""
        config = DualPostProcessAgentConfig()
        self.assertFalse(config.enable_memory)
        self.assertEqual(config.max_iterations, 3)
        self.assertFalse(config.enable_reflection)
        self.assertIsNone(config.max_tool_output_chars)
        self.assertEqual(config.execution_timeout, 500)
        self.assertIsNone(config.custom_prompt)

    def test_custom_values(self):
        """Test custom config values."""
        config = DualPostProcessAgentConfig(
            max_iterations=5,
            enable_reflection=True,
            max_tool_output_chars=10000,
            execution_timeout=300,
            custom_prompt="Custom extraction prompt"
        )
        self.assertEqual(config.max_iterations, 5)
        self.assertTrue(config.enable_reflection)
        self.assertEqual(config.max_tool_output_chars, 10000)
        self.assertEqual(config.execution_timeout, 300)
        self.assertEqual(config.custom_prompt, "Custom extraction prompt")


class TestDualPostProcessAgentHelpers(unittest.TestCase):
    """Test cases for DualPostProcessAgent helper methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm = MagicMock()
        self.mock_llm.config = MagicMock()
        self.mock_llm.config.model_name = "gpt-4"
        self.executor = SafeCodeExecutor(timeout=10)
        self.agent = DualPostProcessAgent(
            llm=self.mock_llm,
            safe_executor=self.executor,
            config=DualPostProcessAgentConfig()
        )

    def test_parse_llm_response_simple_json(self):
        """Test parsing simple JSON response."""
        response = '{"direct_extraction": "extracted text", "code": "result = data"}'
        result = self.agent._parse_llm_response(response)
        self.assertEqual(result["direct_extraction"], "extracted text")
        self.assertEqual(result["code"], "result = data")
        self.assertEqual(result["thought"], "")

    def test_parse_llm_response_with_thought(self):
        """Test parsing JSON response with thought field."""
        response = '{"direct_extraction": "text", "code": "x=1", "thought": "analyzing data"}'
        result = self.agent._parse_llm_response(response)
        self.assertEqual(result["thought"], "analyzing data")

    def test_parse_llm_response_with_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        response = '''```json
{"direct_extraction": "extracted", "code": "result = data.strip()"}
```'''
        result = self.agent._parse_llm_response(response)
        self.assertEqual(result["direct_extraction"], "extracted")
        self.assertEqual(result["code"], "result = data.strip()")

    def test_parse_llm_response_code_block_no_lang(self):
        """Test parsing JSON wrapped in code block without language."""
        response = '''```
{"direct_extraction": "test", "code": "result = 1"}
```'''
        result = self.agent._parse_llm_response(response)
        self.assertEqual(result["direct_extraction"], "test")

    def test_execute_extraction_code_success(self):
        """Test successful code execution."""
        code = "result = data.upper()"
        result, error = self.agent._execute_extraction_code(code, "hello")
        self.assertEqual(result, "HELLO")
        self.assertIsNone(error)

    def test_execute_extraction_code_empty(self):
        """Test empty code returns empty result."""
        result, error = self.agent._execute_extraction_code("", "data")
        self.assertEqual(result, "")
        self.assertIsNone(error)

    def test_execute_extraction_code_error(self):
        """Test code execution error handling."""
        code = "result = undefined_variable"
        result, error = self.agent._execute_extraction_code(code, "data")
        self.assertEqual(result, "")
        self.assertIsNotNone(error)
        self.assertIn("variable reference error", error.lower())

    def test_validate_output_sizes(self):
        """Test output size validation."""
        tool_output = "x" * 1000  # ~250 tokens
        direct_extraction = "short"  # ~1 token
        code_result = "also short"  # ~2 tokens

        sizes = self.agent._validate_output_sizes(
            tool_output, direct_extraction, code_result
        )

        self.assertIn("input_tokens", sizes)
        self.assertIn("direct_tokens", sizes)
        self.assertIn("code_tokens", sizes)
        self.assertIn("max_allowed", sizes)
        self.assertIn("direct_too_large", sizes)
        self.assertIn("code_too_large", sizes)

        # Short outputs should not be too large
        self.assertFalse(sizes["direct_too_large"])
        self.assertFalse(sizes["code_too_large"])

    def test_validate_output_sizes_too_large(self):
        """Test detection of oversized outputs."""
        tool_output = "x" * 100  # Small input
        direct_extraction = "y" * 1000  # Much larger than input
        code_result = "z" * 1000

        sizes = self.agent._validate_output_sizes(
            tool_output, direct_extraction, code_result
        )

        # Outputs larger than 50% of input should be flagged
        self.assertTrue(sizes["direct_too_large"])
        self.assertTrue(sizes["code_too_large"])

    def test_format_output_both_present(self):
        """Test output formatting with both extraction results."""
        output = self.agent._format_output(
            direct_extraction="Direct result here",
            code_result="Code result here",
            code_error=None
        )

        self.assertIn("DUAL EXTRACTION RESULTS", output)
        self.assertIn("DIRECT EXTRACTION", output)
        self.assertIn("CODE-BASED EXTRACTION", output)
        self.assertIn("Direct result here", output)
        self.assertIn("Code result here", output)

    def test_format_output_with_error(self):
        """Test output formatting with code error."""
        output = self.agent._format_output(
            direct_extraction="Direct result",
            code_result="",
            code_error="NameError: undefined variable"
        )

        self.assertIn("Direct result", output)
        self.assertIn("ERROR:", output)
        self.assertIn("NameError", output)

    def test_format_output_empty_direct(self):
        """Test output formatting with empty direct extraction."""
        output = self.agent._format_output(
            direct_extraction="",
            code_result="Code output",
            code_error=None
        )

        self.assertIn("(No output)", output)
        self.assertIn("Code output", output)

    def test_log_retry_reason_both_empty(self):
        """Test retry reason logging for empty outputs."""
        # This just ensures no exception is raised
        self.agent._log_retry_reason(0, False, False, None)

    def test_log_retry_reason_direct_empty(self):
        """Test retry reason logging for empty direct extraction."""
        self.agent._log_retry_reason(0, False, True, None)

    def test_log_retry_reason_code_failed(self):
        """Test retry reason logging for failed code execution."""
        self.agent._log_retry_reason(0, True, False, "SyntaxError")

    def test_log_success(self):
        """Test success logging for different scenarios."""
        # These just ensure no exceptions are raised
        self.agent._log_success(True, True)
        self.agent._log_success(True, False)
        self.agent._log_success(False, True)

    def test_finalize_extraction_with_results(self):
        """Test finalization with partial results."""
        result = self.agent._finalize_extraction(
            tool_output="original",
            best_direct="best direct",
            best_code="best code",
            best_code_error=None
        )

        self.assertIn("best direct", result)
        self.assertIn("best code", result)

    def test_finalize_extraction_no_results(self):
        """Test finalization with no results returns original."""
        result = self.agent._finalize_extraction(
            tool_output="original output",
            best_direct="",
            best_code="",
            best_code_error=None
        )

        self.assertEqual(result, "original output")


class TestDualPostProcessAgentBuildPrompt(unittest.TestCase):
    """Test cases for prompt building."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm = MagicMock()
        self.executor = SafeCodeExecutor(timeout=10)
        self.agent = DualPostProcessAgent(
            llm=self.mock_llm,
            safe_executor=self.executor,
            config=DualPostProcessAgentConfig()
        )

    def test_build_prompt_basic(self):
        """Test basic prompt building."""
        prompt = self.agent._build_prompt(
            tool_name="test_tool",
            tool_description="A test tool",
            tool_output="some output data",
            expected_info="extract the value",
            iteration_history=[],
            iteration=0
        )

        self.assertIn("test_tool", prompt)
        self.assertIn("A test tool", prompt)
        self.assertIn("some output data", prompt)
        self.assertIn("extract the value", prompt)

    def test_build_prompt_with_history(self):
        """Test prompt building with iteration history."""
        history = [
            {
                "iteration": 1,
                "direct": "first attempt",
                "code": "x = 1",
                "code_result": "",
                "error": "Code failed"
            }
        ]

        prompt = self.agent._build_prompt(
            tool_name="tool",
            tool_description="",
            tool_output="data",
            expected_info="info",
            iteration_history=history,
            iteration=1
        )

        self.assertIn("PREVIOUS ATTEMPTS", prompt)
        self.assertIn("Attempt 1", prompt)
        self.assertIn("Code failed", prompt)
        self.assertIn("different approach", prompt.lower())

    def test_build_prompt_no_description(self):
        """Test prompt building without tool description."""
        prompt = self.agent._build_prompt(
            tool_name="tool",
            tool_description="",
            tool_output="data",
            expected_info="info",
            iteration_history=[],
            iteration=0
        )

        # Should not have description section
        self.assertNotIn("Description:", prompt)


if __name__ == "__main__":
    unittest.main()
