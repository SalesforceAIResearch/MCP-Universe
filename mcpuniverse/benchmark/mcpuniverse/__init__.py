"""MCP-Universe paper benchmark bundle (``task_configs/``, ``evaluators/``, ``cleanups.py``)."""
# Import submodules to register cleanup functions and evaluators
from . import cleanups  # noqa: F401
from . import evaluators  # noqa: F401
