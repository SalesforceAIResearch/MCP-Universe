"""Tests for MCPLoopManager explicit cleanup lifecycle."""

import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from omegaconf import OmegaConf

pytest.importorskip("verl")

from verl import DataProto

from mcpuniverse.rl.integrations.verl.mcp_loop_manager import MCPLoopManager
from mcpuniverse.rl.core.env_pool_runtime import MCPEnvPoolRuntime
from mcpuniverse.rl.core.types import RolloutSample, TokenizedRolloutBatch


class _TraceLogger:
    def __init__(self, events):
        self.events = events

    def close(self):
        self.events.append("trace_logger_close")


class _ListLike:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


def _manager_for_lifecycle_test(events):
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = False
    # The runtime owns the env_pool state; set a sentinel "pool alive"
    # so the manager's lifecycle checks see an active pool.
    manager._env_pool_runtime = MCPEnvPoolRuntime(None, env_pool=object())
    manager._trace_logger = _TraceLogger(events)
    manager.llms = ["llm"]
    manager._rollout_servers = ["server"]

    async def cleanup_env_pool():
        events.append("cleanup_env_pool")
        manager._env_pool_runtime.env_pool = None

    manager._cleanup_env_pool = cleanup_env_pool
    return manager


def test_close_cleans_env_pool_and_local_resources_once():
    events = []
    manager = _manager_for_lifecycle_test(events)

    asyncio.run(manager.close())
    asyncio.run(manager.close())

    assert events == ["cleanup_env_pool", "trace_logger_close"]
    assert manager._closed is True
    assert manager._env_pool_runtime.env_pool is None
    assert manager._trace_logger is None
    assert manager.llms == []
    assert manager._rollout_servers == []


def test_shutdown_uses_run_async_safely_for_sync_callers():
    events = []
    manager = _manager_for_lifecycle_test(events)

    def run_async_safely(coro):
        events.append("run_async_safely")
        return asyncio.run(coro)

    manager._run_async_safely = run_async_safely

    manager.shutdown()
    manager.shutdown()

    assert events == ["run_async_safely", "cleanup_env_pool", "trace_logger_close"]
    assert manager._closed is True


def test_parse_input_batch_uses_shared_dataproto_adapter():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    prompts = DataProto(
        batch=None,
        non_tensor_batch={
            "instance_id": np.array(["a", "b"], dtype=object),
            "instruction": np.array(["do a", "do b"], dtype=object),
            "dockerfile_path": np.array(["Dockerfile.a", "Dockerfile.b"], dtype=object),
        },
        meta_info={},
    )

    samples = manager._parse_input_batch(prompts)

    assert all(isinstance(sample, RolloutSample) for sample in samples)
    assert [sample.to_dict() for sample in samples] == [
        {
            "instance_id": "a",
            "instruction": "do a",
            "question": "",
            "output_format": None,
            "mcp_servers": [],
            "evaluators": [],
            "env_pool": {},
            "dockerfile_path": "Dockerfile.a",
        },
        {
            "instance_id": "b",
            "instruction": "do b",
            "question": "",
            "output_format": None,
            "mcp_servers": [],
            "evaluators": [],
            "env_pool": {},
            "dockerfile_path": "Dockerfile.b",
        },
    ]


def test_parse_input_batch_rejects_inconsistent_non_tensor_lengths():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    prompts = SimpleNamespace(
        non_tensor_batch={
            "instance_id": np.array(["a", "b"], dtype=object),
            "instruction": np.array(["do a"], dtype=object),
        },
    )

    try:
        manager._parse_input_batch(prompts)
    except ValueError as exc:
        assert "Inconsistent batch sizes" in str(exc)
    else:
        raise AssertionError("expected inconsistent non_tensor_batch lengths to fail")


def test_prepare_mcp_servers_uses_shared_runner_helper_for_sse():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager.mcp_config = SimpleNamespace(
        mcp_transport="sse",
        mcp_gateway_address="http://gateway",
    )

    servers = manager._prepare_mcp_servers({
        "mcp_servers": _ListLike([{"name": "yf"}, "browser"]),
    })

    assert servers == [
        {"name": "yf", "transport": "sse", "gateway_address": "http://gateway"},
        {"name": "browser", "transport": "sse", "gateway_address": "http://gateway"},
    ]


def test_run_mcp_rollout_uses_shared_rollout_shell(monkeypatch):
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager.val_num_trajectories = 1
    manager.num_trajectories = 1
    manager.max_iterations = 5
    manager.formatter_type = "harmony"
    manager.rollout_mode = "token"
    manager.mcp_manager = object()
    manager.tokenizer = "tokenizer"
    manager._trace_logger = "trace"
    manager.mcp_config = SimpleNamespace(
        agent_mode="agent-mode",
        agent_config={"max_iterations": 5},
        dispatcher=SimpleNamespace(
            max_init_agents=1,
            max_init_retries=2,
            init_retry_delay=0.1,
            init_timeout=30,
            exec_timeout=300.0,
            cleanup_timeout=30.0,
        ),
    )
    manager._prepare_mcp_servers = lambda _instance: [{"name": "yf"}]
    manager._prepare_evaluators = lambda _instance: ["ev"]
    manager._create_llm_for_trajectory = lambda _val_mode: "llm"
    manager._build_env_callbacks = lambda *_args: ("acquire", "release")

    calls = []

    async def fake_run_tokenized_rollout_batch(samples, **kwargs):
        calls.append(("run_tokenized", samples, kwargs))
        return TokenizedRolloutBatch(
            prompt_ids=[[1]],
            response_ids=[[2]],
            response_mask=[[1]],
            rewards=[1.0],
            group_ids=["task-a"],
            metrics={"num_collected": 1, "num_trajectories": 1},
        )

    monkeypatch.setattr(
        "mcpuniverse.rl.integrations.verl.mcp_loop_manager.run_tokenized_rollout_batch",
        fake_run_tokenized_rollout_batch,
    )

    output = asyncio.run(manager._run_mcp_rollout([
        RolloutSample.from_mapping({"instance_id": "task-a", "question": "answer"}),
    ]))

    assert isinstance(output, TokenizedRolloutBatch)
    assert output.rewards == [1.0]
    assert calls[0][0] == "run_tokenized"
    assert all(isinstance(sample, RolloutSample) for sample in calls[0][1])
    shell_kwargs = calls[0][2]
    assert shell_kwargs["dispatcher_cfg"] == {
        "max_init_agents": 1,
        "max_run_agents": None,
        "num_instances": 1,
        "num_trajectories": 1,
        "max_init_retries": 2,
        "init_retry_delay": 0.1,
        "init_timeout": 30,
        "exec_timeout": 300.0,
        "cleanup_timeout": 30.0,
    }
    assert shell_kwargs["mcp_manager"] is manager.mcp_manager
    assert shell_kwargs["agent_mode"] == "agent-mode"
    assert shell_kwargs["max_iterations"] == 5
    assert shell_kwargs["formatter_type"] == "harmony"
    assert shell_kwargs["rollout_mode"] == "token"
    assert shell_kwargs["agent_config"] == {"max_iterations": 5}
    assert shell_kwargs["val_mode"] is False
    assert shell_kwargs["tokenizer"] == "tokenizer"
    assert shell_kwargs["trace_logger"] == "trace"
    assert shell_kwargs["get_mcp_servers"] is manager._prepare_mcp_servers
    assert shell_kwargs["get_evaluators"] is manager._prepare_evaluators
    assert shell_kwargs["create_llm_for_trajectory"] is manager._create_llm_for_trajectory
    assert shell_kwargs["build_env_callbacks"] is manager._build_env_callbacks
    assert shell_kwargs["attach_tito_llm"] is True
    assert shell_kwargs["tokenize_trajectory_fn"].__func__ is manager._tokenize_result.__func__


def test_fully_async_mode_skips_background_prewarm():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = False
    manager._is_async_mode = True
    manager._env_pool_runtime = MCPEnvPoolRuntime(
        None, is_async_mode=True, env_pool=object(),
    )

    def fail_get_fallback_loop():
        raise AssertionError("fully async must not schedule background prewarm")

    manager._get_fallback_loop = fail_get_fallback_loop

    manager._start_background_prewarm([{"dockerfile_path": "Dockerfile"}], 1)

    assert manager._env_pool_runtime.prewarm_future is None
    manager._closed = True


def test_hybrid_background_prewarm_runs_on_owner_loop():
    """Background prewarm must reuse the loop that owns the env pool, not
    spawn a fresh ``asyncio.new_event_loop()`` in a daemon thread.

    Regression guard for `issues/solved/background_prewarm_event_loop_risk.md`:
    `EnvPoolManager`'s internal asyncio primitives (Lock, Queue) are bound to
    the loop active when the pool was constructed; running reconcile on a
    different loop triggers ``RuntimeError: <Lock> is bound to a different
    event loop`` or silent state corruption.
    """
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = False
    manager._is_async_mode = False

    events = []

    async def reconcile_env_pool(batch, max_parallel):
        await asyncio.sleep(0.01)
        events.append((asyncio.get_running_loop(), batch, max_parallel))

    # Simulate the persistent event loop that ``EnvPoolManager`` would have
    # been constructed on in production (mcp_loop_manager's fallback loop).
    owner_loop = asyncio.new_event_loop()
    owner_thread = threading.Thread(
        target=owner_loop.run_forever,
        daemon=True,
        name="test-owner-loop",
    )
    owner_thread.start()

    try:
        runtime = MCPEnvPoolRuntime(
            SimpleNamespace(env_pool=SimpleNamespace(enabled=True)),
            is_async_mode=False,
            env_pool=object(),
            owner_loop=owner_loop,
        )
        runtime.reconcile = reconcile_env_pool
        manager._env_pool_runtime = runtime

        batch = [{"dockerfile_path": "Dockerfile"}]
        manager._start_background_prewarm(batch, 2)
        asyncio.run(manager._await_background_prewarm())

        assert len(events) == 1
        assert events[0][1:] == (batch, 2)
        # Reconcile ran on the owner loop (NOT a freshly-created loop).
        assert events[0][0] is owner_loop
        # The owner loop is persistent: still alive after the prewarm finished.
        assert not owner_loop.is_closed()
        # The background prewarm future is cleared after it finishes.
        assert runtime.prewarm_future is None
    finally:
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        owner_thread.join(timeout=2)
        owner_loop.close()
        manager._closed = True


def test_hybrid_background_prewarm_skips_when_previous_still_running():
    """Submitting a second prewarm while one is in-flight must be a no-op so
    two reconciles never mutate the same pool concurrently.
    """
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = False
    manager._is_async_mode = False

    in_flight = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    async def reconcile_env_pool(_batch, _max_parallel):
        call_count["n"] += 1
        in_flight.set()
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    owner_loop = asyncio.new_event_loop()
    owner_thread = threading.Thread(
        target=owner_loop.run_forever,
        daemon=True,
        name="test-owner-loop-overlap",
    )
    owner_thread.start()

    try:
        runtime = MCPEnvPoolRuntime(
            SimpleNamespace(env_pool=SimpleNamespace(enabled=True)),
            is_async_mode=False,
            env_pool=object(),
            owner_loop=owner_loop,
        )
        runtime.reconcile = reconcile_env_pool
        manager._env_pool_runtime = runtime

        manager._start_background_prewarm([{"dockerfile_path": "A"}], 1)
        assert in_flight.wait(timeout=2), "first prewarm should start"

        # Second call while the first is still running: must be a no-op.
        manager._start_background_prewarm([{"dockerfile_path": "B"}], 1)
        assert call_count["n"] == 1

        # Let the first finish and await it.
        release.set()
        asyncio.run(manager._await_background_prewarm())
        assert call_count["n"] == 1
        assert runtime.prewarm_future is None
    finally:
        release.set()
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        owner_thread.join(timeout=2)
        owner_loop.close()
        manager._closed = True


def test_generate_sequences_manage_pool_false_skips_env_pool_lifecycle():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager._is_async_mode = True
    manager.mcp_config = SimpleNamespace(
        mcp_transport="docker_pool",
        env_pool=SimpleNamespace(enabled=True),
        dispatcher=SimpleNamespace(max_init_agents=2),
    )
    events = []

    async def rollout(batch, val_mode):
        events.append(("rollout", batch, val_mode))
        return "rollout-output"

    async def fail_lifecycle(*_args, **_kwargs):
        raise AssertionError("manage_pool=False must not run env-pool lifecycle")

    manager._parse_input_batch = lambda _prompts: [{"instruction": "x"}]
    manager._run_mcp_rollout = rollout
    manager._run_async_safely = lambda coro: asyncio.run(coro)
    manager._postprocess_per_instance = lambda output, val_mode=False: ["postprocessed", output]
    manager._trigger_periodic_cleanup = lambda: events.append(("periodic_cleanup",))
    manager._init_env_pool = fail_lifecycle
    manager._prewarm_env_pool = fail_lifecycle
    manager._reconcile_env_pool = fail_lifecycle
    manager._release_env_pool = fail_lifecycle
    manager._start_background_prewarm = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("manage_pool=False must not start prewarm")
        )
    )

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    result = manager.generate_sequences(prompts, manage_pool=False, per_instance=True)

    assert result == ["postprocessed", "rollout-output"]
    assert events == [("rollout", [{"instruction": "x"}], False), ("periodic_cleanup",)]


def test_finalize_tokenized_rollout_strips_private_missing_results():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    tokenized = TokenizedRolloutBatch(
        prompt_ids=[[1, 2]],
        response_ids=[[3, 4]],
        response_mask=[[1, 1]],
        rewards=[1.0],
        metrics={
            "num_collected": 1,
            "num_trajectories": 2,
            "missing_results": ["instance-1"],
        },
    )

    result = manager._finalize_tokenized_rollout(
        tokenized,
        [{"instruction": "x"}],
        2,
    )

    assert result.prompt_ids == [[1, 2]]
    assert result.response_ids == [[3, 4]]
    assert result.response_mask == [[1, 1]]
    assert result.rewards == [1.0]
    assert result.metrics["num_collected"] == 1
    assert result.metrics["num_trajectories"] == 2
    assert "missing_results" not in result.metrics


def test_fully_async_docker_pool_manage_pool_true_reconciles_before_rollout():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager._is_async_mode = True
    # Pool starts uninitialized; init_env_pool callback below flips it on.
    manager._env_pool_runtime = MCPEnvPoolRuntime(None, is_async_mode=True)
    manager.mcp_config = SimpleNamespace(
        mcp_transport="docker_pool",
        env_pool=SimpleNamespace(enabled=True),
        dispatcher=SimpleNamespace(max_init_agents=2),
    )
    events = []

    async def init_env_pool(max_parallel):
        events.append(("init_env_pool", max_parallel))
        manager._env_pool_runtime.env_pool = object()

    async def rollout(batch, val_mode):
        events.append(("rollout", batch, val_mode))
        return "rollout-output"

    async def reconcile_env_pool(batch, max_parallel):
        events.append(("reconcile_env_pool", batch, max_parallel))

    async def fail_per_call_pool_lifecycle(*_args, **_kwargs):
        raise AssertionError("fully async must not run hybrid prewarm/release lifecycle")

    manager._parse_input_batch = lambda _prompts: [{"instruction": "x"}]
    manager._run_async_safely = lambda coro: asyncio.run(coro)
    manager._init_env_pool = init_env_pool
    manager._prewarm_env_pool = fail_per_call_pool_lifecycle
    manager._reconcile_env_pool = reconcile_env_pool
    manager._release_env_pool = fail_per_call_pool_lifecycle
    manager._run_mcp_rollout = rollout
    manager._postprocess_per_instance = lambda output, val_mode=False: ["postprocessed", output]
    manager._trigger_periodic_cleanup = lambda: events.append(("periodic_cleanup",))

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    result = manager.generate_sequences(prompts, manage_pool=True, per_instance=True)

    assert result == ["postprocessed", "rollout-output"]
    assert events == [
        ("init_env_pool", 2),
        ("reconcile_env_pool", [{"instruction": "x"}], 2),
        ("rollout", [{"instruction": "x"}], False),
        ("periodic_cleanup",),
    ]


def test_hybrid_validation_matches_legacy_release_and_prewarm_after_rollout():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager._is_async_mode = False
    # Pool is already active for this hybrid-validation scenario.
    manager._env_pool_runtime = MCPEnvPoolRuntime(
        None, is_async_mode=False, env_pool=object(),
    )
    manager._rollout_backend = "vllm"
    manager.config = OmegaConf.create({
        "actor_rollout_ref": {"rollout": {"free_cache_engine": True}},
    })
    manager.mcp_config = SimpleNamespace(
        mcp_transport="docker_pool",
        env_pool=SimpleNamespace(enabled=True),
        dispatcher=SimpleNamespace(max_init_agents=2),
    )
    events = []

    async def rollout(batch, val_mode):
        events.append(("rollout", batch, val_mode))
        return "rollout-output"

    async def await_background_prewarm():
        events.append(("await_background_prewarm",))

    async def reconcile_env_pool(batch, max_parallel):
        events.append(("reconcile_env_pool", batch, max_parallel))

    async def release_env_pool():
        events.append(("release_env_pool",))

    manager._parse_input_batch = lambda _prompts: [{"instruction": "x"}]
    manager._run_async_safely = lambda coro: asyncio.run(coro)
    manager._await_background_prewarm = await_background_prewarm
    manager._reconcile_env_pool = reconcile_env_pool
    manager._release_env_pool = release_env_pool
    manager._run_mcp_rollout = rollout
    manager._postprocess = lambda output: events.append(("postprocess", output)) or "postprocessed"
    manager._trigger_periodic_cleanup = lambda: events.append(("periodic_cleanup",))
    manager._start_background_prewarm = (
        lambda batch, max_parallel:
        events.append(("start_background_prewarm", batch, max_parallel))
    )

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={"val_mode": True},
    )

    result = manager.generate_sequences(prompts, manage_pool=True)

    assert result == "postprocessed"
    assert events == [
        ("await_background_prewarm",),
        ("reconcile_env_pool", [{"instruction": "x"}], 2),
        ("rollout", [{"instruction": "x"}], True),
        ("postprocess", "rollout-output"),
        ("release_env_pool",),
        ("start_background_prewarm", [{"instruction": "x"}], 2),
        ("periodic_cleanup",),
    ]


def test_hybrid_generate_sequences_does_not_pause_rollout_replicas():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager._is_async_mode = False
    manager._rollout_backend = "vllm"
    manager.config = OmegaConf.create({})
    manager.mcp_config = SimpleNamespace(mcp_transport="stdio")
    events = []

    class _Replica:
        async def abort_all_requests(self):
            events.append("pause")
            return {"aborted_count": 0}

        async def resume_generation(self):
            events.append("resume")
            return None

    manager.rollout_replicas = [_Replica()]
    manager._parse_input_batch = lambda prompts: [{"instruction": "x"}]

    async def run_mcp_rollout(batch, val_mode):
        return ("rollout-output", batch, val_mode)

    manager._run_mcp_rollout = run_mcp_rollout
    manager._postprocess = lambda output: ("postprocessed", output)
    manager._trigger_periodic_cleanup = lambda: None
    manager._run_async_safely = lambda coro: asyncio.run(coro)

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    result = manager.generate_sequences(prompts, manage_pool=False)

    assert result == ("postprocessed", ("rollout-output", [{"instruction": "x"}], False))
    assert events == []


def test_hybrid_generate_sequences_never_sleeps_rollout_replicas_before_postprocess():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = False
    manager._is_async_mode = False
    manager.config = OmegaConf.create({
        "actor_rollout_ref": {"rollout": {"free_cache_engine": True}},
    })
    manager.mcp_config = SimpleNamespace(mcp_transport="stdio")
    events = []

    class _Replica:
        async def sleep(self):
            events.append("sleep")

    manager.rollout_replicas = [_Replica()]
    manager._parse_input_batch = lambda prompts: [{"instruction": "x"}]

    async def run_mcp_rollout(batch, val_mode):
        events.append(("rollout", batch, val_mode))
        return "rollout-output"

    manager._run_async_safely = lambda coro: asyncio.run(coro)
    manager._run_mcp_rollout = run_mcp_rollout

    def postprocess(output):
        events.append("postprocess")
        return DataProto(
            batch=None,
            non_tensor_batch={"uid": np.array([], dtype=object)},
            meta_info={"source": output},
        )

    manager._postprocess = postprocess
    manager._trigger_periodic_cleanup = lambda: events.append("cleanup")

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    result = manager.generate_sequences(prompts, manage_pool=False)

    assert result.meta_info["source"] == "rollout-output"
    assert events == [
        ("rollout", [{"instruction": "x"}], False),
        "postprocess",
        "cleanup",
    ]


def test_hybrid_generate_sequences_does_not_sleep_before_postprocess_by_default():
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager._is_async_mode = False
    manager.config = OmegaConf.create({
        "actor_rollout_ref": {"rollout": {"free_cache_engine": True}},
    })
    manager.mcp_config = SimpleNamespace(mcp_transport="stdio")
    events = []

    class _Replica:
        async def sleep(self):
            events.append("sleep")

    manager.rollout_replicas = [_Replica()]
    manager._parse_input_batch = lambda prompts: [{"instruction": "x"}]

    async def run_mcp_rollout(batch, val_mode):
        events.append(("rollout", batch, val_mode))
        return "rollout-output"

    manager._run_mcp_rollout = run_mcp_rollout
    manager._postprocess = lambda output: events.append(("postprocess", output)) or "postprocessed"
    manager._trigger_periodic_cleanup = lambda: events.append("cleanup")
    manager._run_async_safely = lambda coro: asyncio.run(coro)

    prompts = DataProto(
        batch=None,
        non_tensor_batch={"instruction": np.array(["x"], dtype=object)},
        meta_info={},
    )

    result = manager.generate_sequences(prompts, manage_pool=False)

    assert result == "postprocessed"
    assert events == [
        ("rollout", [{"instruction": "x"}], False),
        ("postprocess", "rollout-output"),
        "cleanup",
    ]
