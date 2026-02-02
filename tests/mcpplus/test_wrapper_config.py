"""Tests for WrapperConfig."""
import unittest
from mcpuniverse.mcpplus.mcp.wrapper_manager import WrapperConfig


class TestWrapperConfig(unittest.TestCase):
    """Test cases for WrapperConfig dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = WrapperConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.token_threshold, 500)
        self.assertTrue(config.use_agent_llm)
        self.assertIsNone(config.post_process_llm)
        self.assertTrue(config.enable_memory)
        self.assertEqual(config.execution_timeout, 500)
        self.assertEqual(config.max_iterations, 3)
        self.assertEqual(config.post_processor_type, "dual")
        self.assertFalse(config.enable_reflection)
        self.assertIsNone(config.max_tool_output_chars)
        self.assertIsNone(config.expected_info_prompt_file)

    def test_custom_values(self):
        """Test that custom values override defaults."""
        config = WrapperConfig(
            enabled=True,
            token_threshold=1000,
            use_agent_llm=False,
            post_process_llm="custom_llm",
            enable_memory=False,
            execution_timeout=300,
            max_iterations=5,
            post_processor_type="extract",
            enable_reflection=True,
            max_tool_output_chars=50000,
            expected_info_prompt_file="/path/to/prompt.txt"
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.token_threshold, 1000)
        self.assertFalse(config.use_agent_llm)
        self.assertEqual(config.post_process_llm, "custom_llm")
        self.assertFalse(config.enable_memory)
        self.assertEqual(config.execution_timeout, 300)
        self.assertEqual(config.max_iterations, 5)
        self.assertEqual(config.post_processor_type, "extract")
        self.assertTrue(config.enable_reflection)
        self.assertEqual(config.max_tool_output_chars, 50000)
        self.assertEqual(config.expected_info_prompt_file, "/path/to/prompt.txt")

    def test_partial_override(self):
        """Test that only specified values are overridden."""
        config = WrapperConfig(
            enabled=True,
            token_threshold=750
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.token_threshold, 750)
        # Defaults should remain
        self.assertTrue(config.use_agent_llm)
        self.assertEqual(config.max_iterations, 3)
        self.assertEqual(config.post_processor_type, "dual")


if __name__ == "__main__":
    unittest.main()
