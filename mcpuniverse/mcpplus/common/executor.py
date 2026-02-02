"""
Safe code executor for post-processing agents.

This module provides a SafeCodeExecutor class that executes dynamically
generated Python code in a restricted environment with safety checks.
"""
# pylint: disable=broad-exception-caught,too-few-public-methods
import signal
from typing import Any, Dict

from mcpuniverse.common.logger import get_logger


class SafeCodeExecutor:
    """
    Safe Python code executor with blacklist-based restrictions.

    This class executes dynamically generated Python code in a restricted
    environment, blocking dangerous operations via a comprehensive blacklist.
    """

    def __init__(self, timeout: int = 10):
        """
        Initialize the safe code executor.

        Args:
            timeout: Maximum execution time in seconds.
        """
        self.timeout = timeout
        self._logger = get_logger(self.__class__.__name__)

    def execute(self, code: str, data: Any) -> Any:
        """
        Execute filter code with restrictions.

        Args:
            code: Python code to execute.
            data: Input data to be filtered.

        Returns:
            Filtered result from code execution.

        Raises:
            ValueError: If dangerous operations are detected.
            TimeoutError: If execution exceeds timeout.
            Exception: Any exception raised during code execution.
        """
        # Static analysis: Check for dangerous patterns
        self._check_code_safety(code)

        local_vars = {"data": data, "result": None}

        # Execute with timeout
        try:
            result = self._execute_with_timeout(code, local_vars)
            return result
        except Exception as e:
            self._logger.error("Code execution failed: %s", str(e))
            raise

    def _check_code_safety(self, code: str):
        """
        Check code for dangerous patterns using comprehensive blacklist.

        Args:
            code: Python code to check.

        Raises:
            ValueError: If dangerous operations are detected.
        """
        # Comprehensive blacklist of dangerous operations
        dangerous_patterns = [
            # Code execution
            'eval(', 'exec(',

            # Process/system operations
            'os.system', 'os.popen', 'os.spawn', 'os.exec',
            'subprocess', 'popen', 'sys.modules', 'ctypes'

            # Input operations
            'input(', 'raw_input(',

            # Introspection/reflection that can be dangerous
            '__builtins__', '__import__',
            '__class__', '__dict__', '__code__', '__bases__',
            '__subclasses__', '__mro__', '__globals__',

            # Module reloading
            'reload(', 'importlib',

            # Pickle (can execute arbitrary code)
            'pickle', 'cpickle', 'shelve',

            # Other dangerous operations
            'exit(', 'quit(', 'breakpoint('
        ]

        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                raise ValueError(f"Dangerous operation detected: {pattern}")

        self._logger.debug("Code safety check passed")

    def _execute_with_timeout(
        self,
        code: str,
        local_vars: Dict[str, Any]
    ) -> Any:
        """
        Execute code with a timeout.

        Args:
            code: Python code to execute.
            local_vars: Local variables including input data.

        Returns:
            Result of code execution.

        Raises:
            TimeoutError: If execution exceeds timeout.
        """
        def timeout_handler(signum, frame):  # pylint: disable=unused-argument
            raise TimeoutError(f"Code execution exceeded {self.timeout} seconds")

        # Set up timeout (Unix only)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(self.timeout)
        except (ValueError, AttributeError):
            # Windows or signal not available
            old_handler = None

        try:
            # Execute the code
            exec(code, local_vars)  # pylint: disable=exec-used

            # Return the result variable
            if "result" in local_vars and local_vars["result"] is not None:
                return local_vars["result"]

            # If no result variable, return the data
            return local_vars.get("data")

        except NameError as e:
            # Variable reference error - provide detailed context
            self._logger.error(
                "Variable reference error in generated code: %s\nCode:\n%s",
                str(e), code
            )
            raise ValueError(f"Generated code has variable reference error: {e}") from e
        except Exception as e:
            # Log the error with code context
            self._logger.error(
                "Code execution error: %s\nCode:\n%s",
                str(e), code
            )
            raise
        finally:
            # Cancel timeout
            if old_handler is not None:
                try:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                except (ValueError, AttributeError):
                    pass
