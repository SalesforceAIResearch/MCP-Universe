"""MCPMark bundle (runner YAML, ``task_configs/``, ``server_list.json``, ``evaluators/``, ``prepares.py``, ``cleanups.py``)."""
# Import submodules to register prepare/cleanup functions
from . import prepares  # noqa: F401
from . import cleanups  # noqa: F401
from . import evaluators  # noqa: F401
