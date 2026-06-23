"""Tests for fully async rollouter env-pool preparation."""

import threading
from types import SimpleNamespace

import numpy as np

import pytest

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("verl")

from verl import DataProto

from mcpuniverse.rl.integrations.verl.fully_async.mcp_async_rollouter import (
    MCPFullyAsyncRollouter,
)


def test_ensure_env_pool_for_batch_reconciles_existing_pool():
    rollouter_cls = MCPFullyAsyncRollouter.__ray_metadata__.modified_class
    rollouter = rollouter_cls.__new__(rollouter_cls)
    rollouter._env_pool_init_lock = threading.Lock()

    events = []

    class _LoopManager:
        _env_pool = object()
        mcp_config = SimpleNamespace(
            mcp_transport="docker_pool",
            env_pool=SimpleNamespace(enabled=True),
            dispatcher=SimpleNamespace(max_init_agents=16),
        )

        def _parse_input_batch(self, batch):  # pylint: disable=unused-argument
            events.append("parse")
            return [{"instruction": "x"}]

        def ensure_env_pool(self, batch, max_parallel):
            events.append(("ensure", batch, max_parallel))

    rollouter.mcp_loop_manager = _LoopManager()
    batch = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    rollouter._ensure_env_pool_for_batch(batch)

    assert events == [
        "parse",
        ("ensure", [{"instruction": "x"}], 16),
    ]


# NOTE: the per-instance postprocess test for ``MCPLoopManager._postprocess_per_instance``
# now lives in ``tests/rl/test_mcp_loop_manager_postprocess.py``. The rollouter
# delegates to the loop manager rather than owning a duplicate implementation.
