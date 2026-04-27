"""
Shared cleanup registry for benchmark tasks.

Handlers register into :data:`CLEANUP_FUNCTIONS` via :func:`cleanup_func`.
Concrete handlers live in bundle modules (e.g. :mod:`mcpuniverse.benchmark.mcpmark.cleanups`,
:mod:`mcpuniverse.benchmark.mcpuniverse.cleanups`) and load from :mod:`mcpuniverse.benchmark.hooks`
or suite-specific ``register_*`` entry points.
"""
from typing import Callable

CLEANUP_FUNCTIONS = {}


def cleanup_func(server_name: str, cleanup_func_name: str):
    """A decorator for cleanup functions"""

    def _decorator(func: Callable):
        assert (server_name, cleanup_func_name) not in CLEANUP_FUNCTIONS, (
            f"Duplicated cleanup function ({server_name}, {cleanup_func_name})"
        )
        CLEANUP_FUNCTIONS[(server_name, cleanup_func_name)] = func

        async def _wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator
