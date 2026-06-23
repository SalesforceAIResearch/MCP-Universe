"""Tests for benchmark-owned trajectory lifecycle hooks."""

import asyncio

from mcpuniverse.benchmark.cleanups import CLEANUP_FUNCTIONS
from mcpuniverse.benchmark.prepares import PREPARE_FUNCTIONS
from mcpuniverse.benchmark.trajectory_hooks import build_trajectory_hooks


class _DummyConfig:
    def __init__(self, op_args=None):
        self.op_args = op_args or {}
        self.seen_context = None

    def set_environ_variables(self, context=None):
        self.seen_context = context


class _DummyEvaluator:
    def __init__(self, op_args=None):
        self._context = None
        self._config = _DummyConfig(op_args=op_args)


def test_hooks_run_prepare_evaluator_context_and_cleanup(monkeypatch):
    events = []

    async def prepare_func(context=None, category="", gateway_address="", gym_url="", **_kwargs):
        context.env["UNIT_VALUE"] = "from-context"
        events.append(("prepare", category, gateway_address, gym_url))

    async def cleanup_func(context=None, **_kwargs):
        events.append(("cleanup", context.env.get("UNIT_VALUE")))

    monkeypatch.setitem(PREPARE_FUNCTIONS, "unit_prepare", prepare_func)
    monkeypatch.setitem(CLEANUP_FUNCTIONS, ("unit", "unit_cleanup"), cleanup_func)

    instance = {
        "category": "unit-category",
        "prepares": [
            {
                "prepare_func": "unit_prepare",
                "prepare_args": {"gym_url": "http://old-gym"},
            }
        ],
        "cleanups": [
            {
                "server": "unit",
                "tool": "",
                "cleanup_func": "unit_cleanup",
                "cleanup_args": {},
            }
        ],
    }
    hooks = build_trajectory_hooks(instance)
    data = {"category": "unit-category", "mcp_servers": []}

    asyncio.run(hooks.prepare(data=data, gateway_address="http://gateway"))
    assert events == [("prepare", "unit-category", "http://gateway", "http://gateway")]

    evaluator = _DummyEvaluator()
    asyncio.run(
        hooks.before_evaluate(
            data=data,
            evaluators=[evaluator],
            gateway_address="http://gateway",
        )
    )
    assert evaluator._context.env["UNIT_VALUE"] == "from-context"
    assert evaluator._config.seen_context is evaluator._context

    asyncio.run(hooks.cleanup(data=data, trace_records=[]))
    assert events[-1] == ("cleanup", "from-context")
