"""
Shared prepare-function registry for benchmark tasks.

Handlers register into :data:`PREPARE_FUNCTIONS` via :func:`prepare_func` using
``(benchmark_id, prepare_func_name)`` keys so different suites can reuse the same
logical names without collision.
"""
from __future__ import annotations

from typing import Any, Callable, Tuple

PrepareKey = Tuple[str, str]

PREPARE_FUNCTIONS: dict[PrepareKey, Callable[..., Any]] = {}


def prepare_func(benchmark_id: str, prepare_func_name: str):
    """A decorator that registers ``prepare_func_name`` under ``benchmark_id``."""

    def _decorator(func: Callable[..., Any]):
        key = (benchmark_id, prepare_func_name)
        assert key not in PREPARE_FUNCTIONS, (
            f"Duplicated prepare function: {key!r}"
        )
        PREPARE_FUNCTIONS[key] = func

        async def _wrapper(*args: Any, **kwargs: Any):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator
