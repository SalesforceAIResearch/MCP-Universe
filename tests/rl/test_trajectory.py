"""Tests for mcpuniverse.rl.core.trajectory module."""

import asyncio

import mcpuniverse.rl.core.types as rl_types
from mcpuniverse.rl.core.config import TrajectoryConfig
from mcpuniverse.rl.core.trajectory import Trajectory
from mcpuniverse.rl.core.types import (
    TrajectoryResult,
    TrajectoryStep,
    TraceData,
    TokenData,
)


class _CleanupAgent:
    def __init__(self, events):
        self.events = events

    async def cleanup(self):
        self.events.append("agent_cleanup")


class _AgentResponse:
    def __init__(self, response):
        self._response = response

    def get_response(self):
        return self._response


class _ExecutableCleanupAgent(_CleanupAgent):
    async def execute(self, **_kwargs):
        self.events.append("execute")
        return _AgentResponse("answer")


class _InitializableCleanupAgent(_CleanupAgent):
    async def initialize(self, mcp_servers=None):
        self.events.append(("initialize", mcp_servers or []))


class _FlakyInitializableExecutableAgent(_ExecutableCleanupAgent):
    def __init__(self, events):
        super().__init__(events)
        self.initialize_calls = 0

    async def initialize(self, mcp_servers=None):
        self.initialize_calls += 1
        self.events.append(("initialize", self.initialize_calls, mcp_servers or []))
        if self.initialize_calls == 1:
            raise RuntimeError("init failed")


class _CancelledCleanupAgent(_CleanupAgent):
    async def cleanup(self):
        self.events.append("agent_cleanup")
        raise asyncio.CancelledError()


class _RuntimeReleaseAgent(_CleanupAgent):
    def __init__(self, events):
        super().__init__(events)
        self.released = False

    def release_runtime_references(self):
        self.events.append("agent_release_refs")
        self.released = True


class _CloseLLM:
    def __init__(self, events):
        self.events = events

    async def close(self):
        self.events.append("llm_close")


class _EvalResult:
    passed = True


class _Evaluator:
    def __init__(self, events):
        self.events = events

    async def evaluate(self, _response):
        self.events.append("evaluate")
        return _EvalResult()


class TestTrajectoryStep:
    """Tests for TrajectoryStep dataclass."""

    def test_basic_creation(self):
        step = TrajectoryStep(step_type="thought", content="Let me think...")
        assert step.step_type == "thought"
        assert step.content == "Let me think..."
        assert step.metadata == {}

    def test_with_metadata(self):
        step = TrajectoryStep(
            step_type="action",
            content='{"tool": "calculator", "args": {"a": 1}}',
            metadata={"tool_name": "calculator", "duration_ms": 150},
        )
        assert step.step_type == "action"
        assert step.metadata["tool_name"] == "calculator"
        assert step.metadata["duration_ms"] == 150

    def test_step_types(self):
        for stype in ["thought", "action", "action_input", "result", "answer", "error"]:
            step = TrajectoryStep(step_type=stype, content="test")
            assert step.step_type == stype

    def test_to_dict(self):
        step = TrajectoryStep(
            step_type="answer",
            content="The answer is 42",
            metadata={"confidence": 0.95},
        )
        if hasattr(step, "to_dict"):
            d = step.to_dict()
            assert d["type"] == "answer"
            assert d["content"] == "The answer is 42"


class TestTrajectoryResult:
    """Tests for TrajectoryResult dataclass."""

    def test_basic_creation(self):
        result = TrajectoryResult(
            instance_id="task_001",
            trajectory_id=0,
            response="The answer is 4",
            reward=1.0,
            finish_reason="completed",
        )
        assert result.instance_id == "task_001"
        assert result.trajectory_id == 0
        assert result.response == "The answer is 4"
        assert result.reward == 1.0
        assert result.finish_reason == "completed"

    def test_default_fields(self):
        result = TrajectoryResult(
            instance_id="t1",
            trajectory_id=0,
            response="ok",
            reward=0.5,
            finish_reason="done",
        )
        assert result.error is None
        assert result.trace_id is None
        # TraceData defaults
        assert result.trace.records == []
        assert result.trace.full_text == ""
        assert result.trace.prompt_text == ""
        assert result.trace.output_text == ""
        assert result.trace.output_segments == []
        assert result.num_steps == 0
        assert result.num_tool_calls == 0
        assert result.running_time == 0.0
        assert result.rollout_mode == "text"
        assert result.verifier_pass_rate == 0.0
        assert result.verifier_passed == 0
        assert result.verifier_total == 0
        # TokenData defaults
        assert result.tokens.ids == []
        assert result.tokens.segments == []
        assert result.tokens.trainable_mask == []

    def test_types_are_reexported_from_trajectory(self):
        assert TrajectoryResult is rl_types.TrajectoryResult
        assert TrajectoryStep is rl_types.TrajectoryStep
        assert TraceData is rl_types.TraceData
        assert TokenData is rl_types.TokenData

    def test_with_all_fields(self):
        result = TrajectoryResult(
            instance_id="task_002",
            trajectory_id=1,
            response="Weather is sunny",
            reward=0.8,
            finish_reason="max_iterations",
            error=None,
            trace_id="trace_123",
            trace=TraceData(
                full_text="<|start|>system...",
                prompt_text="System prompt",
                output_text="Assistant response",
                output_segments=[
                    {"role": "assistant", "content": "sunny", "trainable": True},
                ],
            ),
            num_steps=3,
            num_tool_calls=1,
            running_time=2.5,
            rollout_mode="token",
            tokens=TokenData(
                ids=[1, 2, 3, 4, 5],
                trainable_mask=[False, False, True, True, True],
            ),
            verifier_pass_rate=0.75,
            verifier_passed=3,
            verifier_total=4,
        )
        assert result.num_steps == 3
        assert result.num_tool_calls == 1
        assert result.running_time == 2.5
        assert result.rollout_mode == "token"
        assert len(result.tokens.ids) == 5
        assert len(result.tokens.trainable_mask) == 5
        assert result.verifier_pass_rate == 0.75
        assert result.verifier_passed == 3
        assert result.verifier_total == 4

    def test_with_error(self):
        result = TrajectoryResult(
            instance_id="t3",
            trajectory_id=0,
            response="",
            reward=0.0,
            finish_reason="error",
            error="Timeout during tool call",
        )
        assert result.error == "Timeout during tool call"
        assert result.reward == 0.0

    def test_to_dict(self):
        result = TrajectoryResult(
            instance_id="t4",
            trajectory_id=0,
            response="Hello",
            reward=1.0,
            finish_reason="completed",
            num_steps=2,
            num_tool_calls=0,
            verifier_pass_rate=1.0,
            verifier_passed=2,
            verifier_total=2,
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["instance_id"] == "t4"
        assert d["response"] == "Hello"
        assert d["reward"] == 1.0
        assert d["num_steps"] == 2
        assert d["verifier_pass_rate"] == 1.0
        assert d["verifier_passed"] == 2
        assert d["verifier_total"] == 2

    def test_to_rollout_record_overrides_dispatcher_keys(self):
        result = TrajectoryResult(
            instance_id="result-id",
            trajectory_id=99,
            response="Hello",
            reward=1.0,
            finish_reason="completed",
        )

        record = result.to_rollout_record(instance_id="map-id", trajectory_id=0)

        assert record["instance_id"] == "map-id"
        assert record["trajectory_id"] == 0
        assert record["response"] == "Hello"
        assert record["reward"] == 1.0

    def test_to_dict_flattens_sub_dataclasses(self):
        result = TrajectoryResult(
            instance_id="t_flat",
            trajectory_id=0,
            response="ok",
            reward=1.0,
            finish_reason="done",
            trace=TraceData(
                full_text="full",
                prompt_text="prompt",
                output_text="output",
            ),
            rollout_mode="token",
            tokens=TokenData(
                ids=[1, 2, 3],
                trainable_mask=[False, True, True],
            ),
        )
        d = result.to_dict()
        # to_dict() flattens TraceData and TokenData for backward compat
        assert d["full_trace_text"] == "full"
        assert d["prompt_text"] == "prompt"
        assert d["output_text"] == "output"
        assert d["token_ids"] == [1, 2, 3]
        assert d["trainable_mask"] == [False, True, True]

    def test_get_training_text(self):
        result = TrajectoryResult(
            instance_id="t5",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="done",
            trace=TraceData(
                prompt_text="prompt part",
                output_text="output part",
            ),
        )
        text = result.get_training_text()
        assert isinstance(text, str)

    def test_get_training_tokens(self):
        result = TrajectoryResult(
            instance_id="t6",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="done",
            tokens=TokenData(
                ids=[10, 20, 30],
                trainable_mask=[False, True, True],
                segments=[{"type": "prompt"}, {"type": "output"}, {"type": "output"}],
            ),
        )
        tokens = result.get_training_tokens()
        assert isinstance(tokens, dict)
        assert "token_ids" in tokens
        assert "trainable_mask" in tokens


class TestTrajectoryLifecycle:
    """Tests for post-evaluation cleanup lifecycle."""

    def test_new_lifecycle_names_are_available(self):
        events = []
        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={},
            agent=_InitializableCleanupAgent(events),
            mcp_servers=[],
        )

        asyncio.run(traj.initialize())

        assert events == [("initialize", [])]

    def test_cleanup_trajectory_runs_hook_and_release_once(self):
        events = []

        async def cleanup_hook(**_kwargs):
            events.append("cleanup_hook")

        async def release_env():
            events.append("release_env")

        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={},
            agent=_CleanupAgent(events),
            mcp_servers=[],
            cleanup_hook=cleanup_hook,
            release_env=release_env,
        )

        asyncio.run(traj.cleanup())
        asyncio.run(traj.cleanup())

        assert events == ["agent_cleanup", "cleanup_hook", "release_env"]

    def test_generate_releases_agent_runtime_before_full_cleanup_hook(self):
        """Agent runtime (MCP clients) is closed in ``generate``'s finally block
        so MCP sessions don't linger during eval. The env itself stays alive
        until ``cleanup`` because evaluators may query live state
        (postgres rows, notion docs, docker container files, ...).
        """
        events = []

        async def cleanup_hook(**_kwargs):
            events.append("cleanup_hook")

        async def release_env():
            events.append("release_env")

        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={"instruction": "q"},
            agent=_ExecutableCleanupAgent(events),
            mcp_servers=[],
            cleanup_hook=cleanup_hook,
            release_env=release_env,
        )

        asyncio.run(traj.generate())

        assert traj.result is not None
        assert traj.result.response == "answer"
        # ``generate`` runs the agent and closes MCP clients, but leaves the
        # env alive so eval can use it.
        assert events == ["execute", "agent_cleanup"]

        asyncio.run(traj.cleanup())
        asyncio.run(traj.cleanup())

        # ``cleanup`` runs the user hook first, then releases env.
        assert events == ["execute", "agent_cleanup", "cleanup_hook", "release_env"]

    def test_init_retry_resets_cleanup_gates_for_successful_attempt(self):
        events = []

        async def acquire_env():
            events.append("acquire_env")
            return "http://gateway"

        async def release_env():
            events.append("release_env")

        async def cleanup_hook(**_kwargs):
            events.append("cleanup_hook")

        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={"instruction": "q"},
            agent=_FlakyInitializableExecutableAgent(events),
            mcp_servers=[{"name": "yf"}],
            acquire_env=acquire_env,
            release_env=release_env,
            cleanup_hook=cleanup_hook,
        )

        try:
            asyncio.run(traj.initialize())
        except RuntimeError:
            pass
        else:
            raise AssertionError("first init attempt should fail")

        asyncio.run(traj.cleanup())
        asyncio.run(traj.initialize())
        asyncio.run(traj.generate())
        asyncio.run(traj.cleanup())

        # cleanup order: agent_cleanup -> cleanup_hook -> release_env
        # (env is released last so eval can query live state — see dispatcher
        # eval_worker for the prod justification).
        assert events == [
            "acquire_env",
            ("initialize", 1, [{
                "name": "yf",
                "transport": "sse",
                "gateway_address": "http://gateway",
            }]),
            "agent_cleanup",
            "cleanup_hook",
            "release_env",
            "acquire_env",
            ("initialize", 2, [{
                "name": "yf",
                "transport": "sse",
                "gateway_address": "http://gateway",
            }]),
            "execute",
            "agent_cleanup",
            "cleanup_hook",
            "release_env",
        ]

    def test_cleanup_trajectory_releases_env_after_inner_cancel(self):
        events = []

        async def cleanup_hook(**_kwargs):
            events.append("cleanup_hook")

        async def release_env():
            events.append("release_env")

        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={},
            agent=_CancelledCleanupAgent(events),
            mcp_servers=[],
            cleanup_hook=cleanup_hook,
            release_env=release_env,
        )

        asyncio.run(traj.cleanup())

        assert events == ["agent_cleanup", "cleanup_hook", "release_env"]

    def test_before_evaluate_hook_runs_before_evaluators(self):
        events = []

        async def before_evaluate_hook(**_kwargs):
            events.append("before_evaluate")

        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={},
            agent=_CleanupAgent(events),
            mcp_servers=[],
            evaluators=[_Evaluator(events)],
            before_evaluate_hook=before_evaluate_hook,
        )
        traj.response = "answer"
        traj.result = TrajectoryResult(
            instance_id="task",
            trajectory_id=0,
            response="answer",
            reward=0.0,
            finish_reason="stop",
        )

        asyncio.run(traj.evaluate())

        assert events == ["before_evaluate", "evaluate"]
        assert traj.result.reward == 1.0

    def test_cleanup_trajectory_releases_env_but_keeps_runtime_refs(self):
        events = []
        agent = _RuntimeReleaseAgent(events)
        llm = _CloseLLM(events)
        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={"instruction": "q"},
            agent=agent,
            mcp_servers=[{"name": "server"}],
            llm=llm,
        )
        traj.result = TrajectoryResult(
            instance_id="task",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="stop",
        )

        asyncio.run(traj.cleanup())

        assert events == ["agent_cleanup"]
        assert not agent.released
        assert traj.result is not None
        assert traj.agent is agent
        assert traj.llm is llm
        assert traj.data == {"instruction": "q"}

    def test_cleanup_trajectory_keeps_tito_llm_until_close(self):
        events = []
        llm = _CloseLLM(events)
        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={"instruction": "q"},
            agent=_CleanupAgent(events),
            mcp_servers=[],
            llm=llm,
        )
        traj._tito_llm = llm

        asyncio.run(traj.cleanup())

        assert events == ["agent_cleanup"]
        assert traj.llm is llm
        assert traj._tito_llm is llm

        asyncio.run(traj.close(clear_result=True, clear_inputs=True))

        assert events == ["agent_cleanup", "llm_close"]
        assert traj.llm is None
        assert traj._tito_llm is None

    def test_close_clears_materialized_result_and_inputs(self):
        events = []
        traj = Trajectory(
            cfg=TrajectoryConfig(instance_id="task", trajectory_id=0),
            data={"instruction": "q"},
            agent=_RuntimeReleaseAgent(events),
            mcp_servers=[{"name": "server"}],
            llm=_CloseLLM(events),
        )
        traj.result = TrajectoryResult(
            instance_id="task",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="stop",
        )

        asyncio.run(traj.close(clear_result=True, clear_inputs=True))

        assert events == ["agent_cleanup", "llm_close", "agent_release_refs"]
        assert traj.result is None
        assert traj.data is None
        assert traj.agent is None
        assert traj.mcp_servers == []
