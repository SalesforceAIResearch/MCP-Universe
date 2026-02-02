"""Tests for SafeCodeExecutor."""
import unittest
from mcpuniverse.mcpplus.common.executor import SafeCodeExecutor


class TestSafeCodeExecutor(unittest.TestCase):
    """Test cases for SafeCodeExecutor."""

    def setUp(self):
        """Set up test fixtures."""
        self.executor = SafeCodeExecutor(timeout=10)

    def test_basic_execution(self):
        """Test basic code execution with result variable."""
        code = "result = data.upper()"
        result = self.executor.execute(code, "hello world")
        self.assertEqual(result, "HELLO WORLD")

    def test_json_parsing(self):
        """Test JSON parsing in executed code."""
        code = """
import json
parsed = json.loads(data)
result = parsed.get("name", "unknown")
"""
        result = self.executor.execute(code, '{"name": "test", "value": 123}')
        self.assertEqual(result, "test")

    def test_list_filtering(self):
        """Test list comprehension and filtering."""
        code = "result = [x for x in data if x > 2]"
        result = self.executor.execute(code, [1, 2, 3, 4, 5])
        self.assertEqual(result, [3, 4, 5])

    def test_returns_data_when_no_result(self):
        """Test that data is returned when no result variable is set."""
        code = "x = 1 + 1"  # No result assignment
        result = self.executor.execute(code, "original data")
        self.assertEqual(result, "original data")

    def test_result_none_returns_data(self):
        """Test that data is returned when result is explicitly None."""
        code = "result = None"
        result = self.executor.execute(code, "fallback")
        self.assertEqual(result, "fallback")

    def test_blocks_eval(self):
        """Test that eval() is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("result = eval('1+1')", "test")
        self.assertIn("eval(", str(ctx.exception))

    def test_blocks_exec(self):
        """Test that exec() is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("exec('x=1')", "test")
        self.assertIn("exec(", str(ctx.exception))

    def test_blocks_os_system(self):
        """Test that os.system is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("import os; os.system('ls')", "test")
        self.assertIn("os.system", str(ctx.exception))

    def test_blocks_subprocess(self):
        """Test that subprocess is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("import subprocess", "test")
        self.assertIn("subprocess", str(ctx.exception))

    def test_blocks_builtins_access(self):
        """Test that __builtins__ access is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("x = __builtins__", "test")
        self.assertIn("__builtins__", str(ctx.exception))

    def test_blocks_import_dunder(self):
        """Test that __import__ is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("__import__('os')", "test")
        self.assertIn("__import__", str(ctx.exception))

    def test_blocks_pickle(self):
        """Test that pickle is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("import pickle", "test")
        self.assertIn("pickle", str(ctx.exception))

    def test_blocks_input(self):
        """Test that input() is blocked."""
        with self.assertRaises(ValueError) as ctx:
            self.executor.execute("x = input()", "test")
        self.assertIn("input(", str(ctx.exception))

    def test_case_insensitive_blocking(self):
        """Test that dangerous patterns are blocked case-insensitively."""
        with self.assertRaises(ValueError):
            self.executor.execute("EVAL('test')", "test")

    def test_complex_data_processing(self):
        """Test processing complex nested data structures."""
        code = """
import json
data_dict = json.loads(data)
result = {
    "count": len(data_dict["items"]),
    "names": [item["name"] for item in data_dict["items"]]
}
"""
        input_data = '{"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}'
        result = self.executor.execute(code, input_data)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["names"], ["a", "b", "c"])

    def test_string_manipulation(self):
        """Test various string operations."""
        code = """
lines = data.strip().split('\\n')
result = [line.strip() for line in lines if line.strip()]
"""
        result = self.executor.execute(code, "  line1  \n  line2  \n  \n  line3  ")
        self.assertEqual(result, ["line1", "line2", "line3"])


class TestSafeCodeExecutorBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility of SafeCodeExecutor import."""

    def test_import_from_wrapper_manager(self):
        """Test that SafeCodeExecutor can still be imported from wrapper_manager."""
        from mcpuniverse.mcpplus.mcp.wrapper_manager import SafeCodeExecutor as SE1
        from mcpuniverse.mcpplus.common.executor import SafeCodeExecutor as SE2
        self.assertIs(SE1, SE2)


if __name__ == "__main__":
    unittest.main()
