"""Tests for mcpuniverse.rl.runner module."""

import asyncio
import importlib.util
from types import SimpleNamespace

import pytest

from mcpuniverse.rl.runner import (
    RolloutOutput,
    RolloutEngine,
    rollout_batch_result_to_output,
)
from mcpuniverse.rl.core.rollout import (
    build_rollout_dispatcher_config,
    build_rollout_trajectories,
    build_rollout_instance_data,
    collect_rollout_batch_result,
    create_rollout_trajectory,
    dispatch_rollout_trajectories,
    materialize_rollout_samples,
    prepare_mcp_servers_for_sample,
    run_rollout_trajectories,
    run_tokenized_rollout_batch,
)
from mcpuniverse.rl.core.config import GeneratorConfig, RolloutConfig, ServerConfig
from mcpuniverse.rl.core.types import (
    RolloutBatchResult,
    RolloutSample,
    TokenizedRolloutBatch,
    TrajectoryResult,
)


# RolloutEngine defaults to token rollout mode, which forces the async_vllm
# engine and therefore needs vllm installed. Skip the engine-construction tests
# when vllm is unavailable (e.g. CPU-only CI); the pure-helper tests still run.
_VLLM_AVAILABLE = importlib.util.find_spec("vllm") is not None
requires_vllm = pytest.mark.skipif(not _VLLM_AVAILABLE, reason="vllm not installed")


class _ListLike:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


def test_build_rollout_instance_data_prefers_instruction_over_question():
    assert build_rollout_instance_data({
        "instruction": "direct",
        "question": "fallback",
    })["instruction"] == "direct"
    assert build_rollout_instance_data({"question": "fallback"})["instruction"] == "fallback"


def test_materialize_rollout_samples_preserves_metadata():
    samples = [
        RolloutSample.from_mapping({
            "instance_id": "task-a",
            "question": "fallback",
            "dockerfile_path": "Dockerfile",
        }),
    ]

    assert materialize_rollout_samples(samples) == [
        {
            "instance_id": "task-a",
            "instruction": "fallback",
            "question": "fallback",
            "output_format": None,
            "mcp_servers": [],
            "evaluators": [],
            "env_pool": {},
            "dockerfile_path": "Dockerfile",
        }
    ]


def test_prepare_mcp_servers_for_sample_normalizes_listlike_and_sse_gateway():
    servers = prepare_mcp_servers_for_sample(
        {"mcp_servers": _ListLike([{"name": "yf"}, "browser"])},
        mcp_transport="sse",
        mcp_gateway_address="http://gateway",
    )

    assert servers == [
        {"name": "yf", "transport": "sse", "gateway_address": "http://gateway"},
        {"name": "browser", "transport": "sse", "gateway_address": "http://gateway"},
    ]


def test_prepare_mcp_servers_for_sample_handles_docker_pool_transport():
    servers = prepare_mcp_servers_for_sample(
        {"mcp_servers": [{"name": "yf"}, "browser"]},
        mcp_transport="docker_pool",
        env_pool_active=True,
    )

    assert servers == [
        {"name": "yf", "transport": "sse"},
        {"name": "browser", "transport": "sse"},
    ]


def test_prepare_mcp_servers_for_sample_uses_default_servers_when_requested():
    servers = prepare_mcp_servers_for_sample(
        {},
        default_servers=[ServerConfig(name="yf", tools=["get_price"])],
        use_default_servers=True,
    )

    assert servers == [
        {
            "name": "yf",
            "tools": ["get_price"],
            "permissions": None,
            "transport": "stdio",
        }
    ]


def test_build_rollout_dispatcher_config_preserves_runner_optional_fields():
    dispatcher = SimpleNamespace(
        max_init_agents=8,
        max_eval_parallel_agents=3,
        max_init_retries=2,
        init_retry_delay=0.5,
    )

    assert build_rollout_dispatcher_config(
        dispatcher,
        num_instances=4,
        num_trajectories=2,
        include_max_eval_parallel_agents=True,
    ) == {
        "max_init_agents": 8,
        "max_run_agents": None,
        "max_init_retries": 2,
        "init_retry_delay": 0.5,
        "exec_timeout": 300.0,
        "cleanup_timeout": 30.0,
        "num_instances": 4,
        "num_trajectories": 2,
        "max_eval_parallel_agents": 3,
    }


def test_build_rollout_dispatcher_config_propagates_exec_and_cleanup_timeout_overrides():
    """``exec_timeout`` / ``cleanup_timeout`` are first-class knobs and are
    always plumbed through; missing them on the source config falls back to
    dispatcher defaults (300 / 30)."""
    dispatcher = SimpleNamespace(
        max_init_agents=8,
        max_init_retries=2,
        init_retry_delay=0.5,
        exec_timeout=900.0,
        cleanup_timeout=60.0,
    )

    cfg = build_rollout_dispatcher_config(
        dispatcher,
        num_instances=4,
        num_trajectories=2,
    )
    assert cfg["exec_timeout"] == 900.0
    assert cfg["cleanup_timeout"] == 60.0


def test_build_rollout_dispatcher_config_preserves_verl_init_timeout_default():
    dispatcher = {
        "max_init_agents": 8,
        "max_init_retries": 2,
        "init_retry_delay": 0.5,
    }

    assert build_rollout_dispatcher_config(
        dispatcher,
        num_instances=4,
        num_trajectories=2,
        include_init_timeout=True,
    ) == {
        "max_init_agents": 8,
        "max_run_agents": None,
        "max_init_retries": 2,
        "init_retry_delay": 0.5,
        "exec_timeout": 300.0,
        "cleanup_timeout": 30.0,
        "num_instances": 4,
        "num_trajectories": 2,
        "init_timeout": 300,
    }


def test_create_rollout_trajectory_builds_config_data_and_tito_attachment(monkeypatch):
    captured = {}

    def fake_create_trajectory(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("mcpuniverse.rl.core.rollout.create_trajectory", fake_create_trajectory)

    llm = object()
    traj = create_rollout_trajectory(
        instance={"instance_id": "task-a", "question": "answer me"},
        instance_id="task-a",
        trajectory_id=3,
        llm=llm,
        mcp_manager=object(),
        mcp_servers=[{"name": "yf"}],
        agent_mode=RolloutConfig().agent_mode,
        max_iterations=7,
        formatter_type="harmony",
        rollout_mode="token",
        agent_config={"max_iterations": 7},
        evaluators=["ev"],
        val_mode=True,
        tokenizer="tokenizer",
        acquire_env="acquire",
        release_env="release",
        trace_logger="trace",
        trajectory_config_kwargs={"mcp_gateway_address": "http://gateway"},
        attach_tito_llm=True,
    )

    cfg = captured["cfg"]
    assert cfg.instance_id == "task-a"
    assert cfg.trajectory_id == 3
    assert cfg.max_iterations == 7
    assert cfg.formatter_type == "harmony"
    assert cfg.rollout_mode == "token"
    assert cfg.mcp_gateway_address == "http://gateway"
    assert captured["data"]["instruction"] == "answer me"
    assert captured["mcp_servers"] == [{"name": "yf"}]
    assert captured["evaluators"] == ["ev"]
    assert captured["tokenizer"] == "tokenizer"
    assert traj._tito_llm is llm


def test_build_rollout_trajectories_uses_callbacks(monkeypatch):
    captured = []

    def fake_create_trajectory(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(result=None)

    monkeypatch.setattr("mcpuniverse.rl.core.rollout.create_trajectory", fake_create_trajectory)

    trajectories = build_rollout_trajectories(
        [{"instance_id": "task-a", "question": "answer"}],
        num_trajectories=2,
        mcp_manager=object(),
        agent_mode=RolloutConfig().agent_mode,
        max_iterations=5,
        formatter_type="harmony",
        rollout_mode="token",
        agent_config={"max_iterations": 5},
        val_mode=True,
        tokenizer="tokenizer",
        trace_logger="trace",
        get_mcp_servers=lambda _instance: [{"name": "yf"}],
        get_evaluators=lambda _instance: ["ev"],
        create_llm_for_trajectory=lambda _val_mode: "llm",
        build_env_callbacks=lambda *_args: ("acquire", "release"),
        attach_tito_llm=True,
    )

    assert sorted(trajectories["task-a"].keys()) == [0, 1]
    assert len(captured) == 2
    assert captured[0]["cfg"].trajectory_id == 0
    assert captured[1]["cfg"].trajectory_id == 1
    assert captured[0]["data"]["instruction"] == "answer"
    assert captured[0]["mcp_servers"] == [{"name": "yf"}]
    assert captured[0]["evaluators"] == ["ev"]
    assert captured[0]["tokenizer"] == "tokenizer"
    assert trajectories["task-a"][0]._tito_llm == "llm"


def test_run_rollout_trajectories_dispatches_built_trajectories(monkeypatch):
    calls = []

    def fake_create_trajectory(**kwargs):
        return SimpleNamespace(cfg=kwargs["cfg"], result=None)

    async def fake_dispatch(trajectories, *, dispatcher_cfg):
        calls.append((dispatcher_cfg, trajectories))

    monkeypatch.setattr("mcpuniverse.rl.core.rollout.create_trajectory", fake_create_trajectory)
    monkeypatch.setattr("mcpuniverse.rl.core.rollout.dispatch_rollout_trajectories", fake_dispatch)

    trajectories = asyncio.run(run_rollout_trajectories(
        [{"instance_id": "task-a", "instruction": "answer"}],
        dispatcher_cfg={"num_instances": 1, "num_trajectories": 1},
        num_trajectories=1,
        mcp_manager=object(),
        agent_mode=RolloutConfig().agent_mode,
        max_iterations=5,
        formatter_type="harmony",
        rollout_mode="text",
        get_mcp_servers=lambda _instance: [],
        get_evaluators=lambda _instance: [],
        create_llm_for_trajectory=lambda _val_mode: "llm",
    ))

    assert calls == [({"num_instances": 1, "num_trajectories": 1}, trajectories)]
    assert trajectories["task-a"][0].cfg.instance_id == "task-a"


def test_run_tokenized_rollout_batch_accepts_rollout_samples(monkeypatch):
    calls = []

    def fake_create_trajectory(**kwargs):
        result = SimpleNamespace(reward=1.0)
        return SimpleNamespace(cfg=kwargs["cfg"], result=result)

    async def fake_dispatch(trajectories, *, dispatcher_cfg):
        calls.append((dispatcher_cfg, trajectories))

    monkeypatch.setattr("mcpuniverse.rl.core.rollout.create_trajectory", fake_create_trajectory)
    monkeypatch.setattr("mcpuniverse.rl.core.rollout.dispatch_rollout_trajectories", fake_dispatch)

    tokenized = asyncio.run(run_tokenized_rollout_batch(
        [RolloutSample.from_mapping({"instance_id": "task-a", "question": "answer"})],
        dispatcher_cfg={"num_instances": 1, "num_trajectories": 1},
        num_trajectories=1,
        mcp_manager=object(),
        agent_mode=RolloutConfig().agent_mode,
        max_iterations=5,
        formatter_type="harmony",
        rollout_mode="token",
        get_mcp_servers=lambda _instance: [],
        get_evaluators=lambda _instance: [],
        create_llm_for_trajectory=lambda _val_mode: "llm",
        tokenize_trajectory_fn=lambda *_args: ([11], [21, 22], [1, 1]),
    ))

    assert isinstance(tokenized, TokenizedRolloutBatch)
    assert tokenized.prompt_ids == [[11]]
    assert tokenized.response_ids == [[21, 22]]
    assert tokenized.response_mask == [[1, 1]]
    assert tokenized.rewards == [1.0]
    assert tokenized.group_ids == ["task-a"]
    assert calls[0][0] == {"num_instances": 1, "num_trajectories": 1}


def test_dispatch_rollout_trajectories_uses_configured_dispatcher(monkeypatch):
    calls = []

    class _FakePipeline:
        def __init__(self, cfg, *, on_instance_complete=None):
            self._cfg = cfg

        async def run_batch(self, trajectories):
            calls.append((self._cfg, trajectories))

    trajectories = {"task-a": {0: SimpleNamespace()}}
    monkeypatch.setattr("mcpuniverse.rl.core.rollout.RolloutPipeline", _FakePipeline)

    asyncio.run(dispatch_rollout_trajectories(
        trajectories,
        dispatcher_cfg={"num_instances": 1, "num_trajectories": 1},
    ))

    assert calls == [({"num_instances": 1, "num_trajectories": 1}, trajectories)]


def test_collect_rollout_batch_result_returns_neutral_result():
    first = TrajectoryResult(
        instance_id="task-a",
        trajectory_id=0,
        response="ok",
        reward=1.0,
        finish_reason="stop",
        num_tool_calls=2,
    )
    second = TrajectoryResult(
        instance_id="task-b",
        trajectory_id=0,
        response="bad",
        reward=0.0,
        finish_reason="error",
        error="failed",
    )
    trajectories = {
        "task-a": {0: SimpleNamespace(result=first)},
        "task-b": {0: SimpleNamespace(result=second)},
    }

    result = collect_rollout_batch_result(trajectories)

    assert isinstance(result, RolloutBatchResult)
    assert result.trajectories == [first, second]
    assert result.metrics["rollout_metrics/num_instances"] == 2
    assert result.metrics["rollout_metrics/num_trajectories"] == 2
    assert result.metrics["rollout_metrics/total_reward"] == 1.0
    assert result.metrics["rollout_metrics/error_rate"] == 0.5


def test_rollout_batch_result_to_output_preserves_legacy_shape():
    result = RolloutBatchResult(
        trajectories=[
            TrajectoryResult(
                instance_id="task-a",
                trajectory_id=0,
                response="ok",
                reward=1.0,
                finish_reason="stop",
            )
        ],
        metrics={"rollout_metrics/num_trajectories": 1},
    )

    output = rollout_batch_result_to_output(result)

    assert isinstance(output, RolloutOutput)
    assert output.responses == ["ok"]
    assert output.rewards == [1.0]
    assert output.finish_reasons == ["stop"]
    assert output.trajectories == [
        {
            "instance_id": "task-a",
            "trajectory_id": 0,
            "response": "ok",
            "reward": 1.0,
            "finish_reason": "stop",
            "error": None,
            "trace_id": None,
            "trace_records": [],
            "full_trace_text": "",
            "prompt_text": "",
            "output_text": "",
            "output_segments": [],
            "num_steps": 0,
            "num_tool_calls": 0,
            "running_time": 0.0,
            "rollout_mode": "text",
            "verifier_pass_rate": 0.0,
            "verifier_passed": 0,
            "verifier_total": 0,
        }
    ]
    assert output.rollout_metrics == {"rollout_metrics/num_trajectories": 1}


class TestRolloutOutput:
    """Tests for RolloutOutput dataclass."""

    def test_default_creation(self):
        out = RolloutOutput()
        assert out.responses == []
        assert out.rewards == []
        assert out.finish_reasons == []
        assert out.trajectories == []
        assert out.rollout_metrics == {}

    def test_with_data(self):
        out = RolloutOutput(
            responses=["Answer 1", "Answer 2"],
            rewards=[1.0, 0.5],
            finish_reasons=["completed", "max_iterations"],
            rollout_metrics={"success_rate": 0.5, "mean_reward": 0.75},
        )
        assert len(out.responses) == 2
        assert out.rewards[0] == 1.0
        assert out.rollout_metrics["success_rate"] == 0.5

    def test_to_dict(self):
        out = RolloutOutput(
            responses=["Hello"],
            rewards=[1.0],
            finish_reasons=["completed"],
            rollout_metrics={"mean_steps": 3.0},
        )
        d = out.to_dict()
        assert isinstance(d, dict)
        assert d["responses"] == ["Hello"]
        assert d["rewards"] == [1.0]
        assert d["rollout_metrics"]["mean_steps"] == 3.0

    def test_get_trajectory_texts(self):
        out = RolloutOutput(
            responses=["Resp1", "Resp2"],
            trajectories=[
                {"full_trace_text": "trace1"},
                {"full_trace_text": "trace2"},
            ],
        )
        texts = out.get_trajectory_texts()
        assert isinstance(texts, list)

    def test_get_all_steps(self):
        out = RolloutOutput(
            responses=["R1"],
            trajectories=[{"steps": [{"type": "thought", "content": "think"}]}],
        )
        steps = out.get_all_steps()
        assert isinstance(steps, list)

    def test_get_all_messages(self):
        out = RolloutOutput(
            responses=["R1"],
            trajectories=[{"messages": [{"role": "user", "content": "hi"}]}],
        )
        messages = out.get_all_messages()
        assert isinstance(messages, list)


class TestRolloutEngine:
    """Tests for RolloutEngine class."""

    @requires_vllm
    def test_engine_creation(self):
        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
        )
        engine = RolloutEngine(config)
        assert engine is not None

    def test_engine_update_model_endpoint(self):
        # Use text mode explicitly: the default rollout_mode is "token", which
        # auto-switches vllm_local -> async_vllm and would then require a
        # model_path/model_name field unrelated to what this test exercises.
        config = RolloutConfig(
            llm_type="vllm_local",
            llm_config={"base_url": "http://localhost:8000/v1"},
            rollout_mode="text",
        )
        engine = RolloutEngine(config)
        engine.update_model_endpoint("http://localhost:9000/v1")

        endpoint = engine.get_model_endpoint()
        assert "9000" in endpoint

    @requires_vllm
    def test_engine_update_llm_config(self):
        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
        )
        engine = RolloutEngine(config)
        engine.update_llm_config(temperature=0.5)
        # Should not raise

    @requires_vllm
    def test_initialize_trajectories_uses_shared_builder_inputs(
        self,
        monkeypatch,
    ):
        captured = []

        def fake_create_trajectory(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace()

        monkeypatch.setattr(
            "mcpuniverse.rl.core.rollout.create_trajectory",
            fake_create_trajectory,
        )

        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
            generator=GeneratorConfig(num_trajectories=2),
        )
        engine = RolloutEngine(config)
        engine._initialize_trajectories([
            {
                "instance_id": "sample",
                "instruction": "answer",
                "mcp_servers": [],
                "evaluators": [{"func": "raw"}],
            }
        ])

        assert len(captured) == 2
        assert captured[0]["cfg"].instance_id == "sample"
        assert captured[0]["cfg"].trajectory_id == 0
        assert captured[1]["cfg"].trajectory_id == 1
        assert captured[0]["data"]["instruction"] == "answer"
        assert captured[0]["mcp_servers"] == []
        assert len(captured[0]["evaluators"]) == 1
        assert captured[0]["evaluators"] is captured[1]["evaluators"]

    @requires_vllm
    def test_env_pool_provision_uses_current_pool_api(self):
        calls = []

        class FakePool:
            max_pool_size = 8

            async def provision(self, num_envs, config, parallel, reuse_existing):
                calls.append((num_envs, config, parallel, reuse_existing))
                return []

            def get_stats(self):
                return {}

        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
            use_sample_servers=True,
            generator=GeneratorConfig(num_trajectories=1),
        )
        engine = RolloutEngine(config)
        engine._env_pool = FakePool()

        asyncio.run(engine._provision_env_pool(num_envs=4, config="cfg"))

        assert calls == [(4, "cfg", True, config.env_pool.reuse_existing)]

    @requires_vllm
    def test_run_dispatches_and_postprocesses_with_current_api(self, monkeypatch):
        calls = []

        class _FakePipeline:
            def __init__(self, cfg, *, on_instance_complete=None):
                self._cfg = cfg

            async def run_batch(self, trajectories):
                calls.append(("dispatch", self._cfg, trajectories))

        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
            generator=GeneratorConfig(num_trajectories=1),
        )
        engine = RolloutEngine(config)
        engine._initialize_trajectories = (
            lambda _batch, _val_mode: setattr(engine, "trajectories", {"task": {}})
        )
        engine._collect_batch_result = lambda: RolloutBatchResult(metrics={"ok": 1})
        monkeypatch.setattr("mcpuniverse.rl.core.rollout.RolloutPipeline", _FakePipeline)

        output = asyncio.run(engine.run([{"instruction": "x"}]))

        assert output.rollout_metrics == {"ok": 1}
        assert len(calls) == 1
        assert calls[0][0] == "dispatch"
        assert calls[0][1]["num_instances"] == 1
        assert calls[0][1]["num_trajectories"] == 1
        assert calls[0][1]["max_eval_parallel_agents"] == config.dispatcher.max_eval_parallel_agents

    @requires_vllm
    def test_run_batch_result_returns_neutral_result(self, monkeypatch):
        calls = []

        class _FakePipeline:
            def __init__(self, cfg, *, on_instance_complete=None):
                self._cfg = cfg

            async def run_batch(self, trajectories):
                calls.append(("dispatch", self._cfg, trajectories))

        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
            generator=GeneratorConfig(num_trajectories=1),
        )
        engine = RolloutEngine(config)
        engine._initialize_trajectories = (
            lambda _batch, _val_mode: setattr(engine, "trajectories", {"task": {}})
        )
        engine._collect_batch_result = lambda: RolloutBatchResult(metrics={"neutral": True})
        monkeypatch.setattr("mcpuniverse.rl.core.rollout.RolloutPipeline", _FakePipeline)

        result = asyncio.run(engine.run_batch_result([{"instruction": "x"}]))

        assert isinstance(result, RolloutBatchResult)
        assert result.metrics == {"neutral": True}
        assert len(calls) == 1
