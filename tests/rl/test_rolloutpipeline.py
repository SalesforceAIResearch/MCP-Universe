"""Tests for the unified ``mcpuniverse.rl.core.pipeline.RolloutPipeline``.

Covers both drive modes over the one engine:
* :meth:`RolloutPipeline.run_batch` — the batch dispatcher (init -> run -> eval
  3-stage flow, drain to completion);
* streaming — ``start`` / ``submit`` / ``quiesce`` / ``aclose`` (the fully-async
  drive), including the weight-sync cycle (drain, then resume submitting).
"""

import asyncio
from types import SimpleNamespace

from mcpuniverse.rl.core.pipeline import RolloutPipeline


class _FakeTraj:
    """Minimal trajectory double for the init -> run -> eval flow.

    Implements the interface the pipeline drives (initialize_env -> connect ->
    generate -> evaluate) plus cleanup / _release_env, and records the ordered
    lifecycle events it sees.
    """

    def __init__(self, *, fail_env=False, fail_connect=False, result_none=False):
        self._fail_env = fail_env
        self._fail_connect = fail_connect
        self._result_none = result_none
        self.events = []
        self.result = None

    async def initialize_env(self):
        self.events.append("env")
        if self._fail_env:
            raise RuntimeError("env boom")

    async def connect(self):
        self.events.append("connect")
        if self._fail_connect:
            raise RuntimeError("connect boom")

    async def generate(self):
        self.events.append("generate")
        if not self._result_none:
            self.result = SimpleNamespace(reward=1.0)

    async def evaluate(self):
        self.events.append("evaluate")

    async def _release_env(self):
        self.events.append("release_env")

    async def cleanup(self):
        self.events.append("cleanup")


def _cfg(**overrides):
    base = {
        "max_init_agents": 2,
        "max_eval_parallel_agents": 2,
        "max_init_retries": 1,      # no retry loop in tests
        "init_retry_delay": 0,
        "init_timeout": 5,
        "exec_timeout": 5,
        "cleanup_timeout": 5,
    }
    base.update(overrides)
    return base


def _run_batch(trajectories, cfg=None):
    cfg = cfg or _cfg()
    pipe = RolloutPipeline(cfg, on_instance_complete=cfg.get("on_instance_complete"))
    asyncio.run(pipe.run_batch(trajectories))


class TestRunBatchStages:
    """Exercise the real init -> run -> eval flow via run_batch."""

    def test_happy_path_runs_all_stages_in_order(self):
        traj = _FakeTraj()
        _run_batch({"i": {0: traj}})
        # env -> connect -> generate -> evaluate, then env released via cleanup
        assert traj.events == ["env", "connect", "generate", "evaluate", "cleanup"]
        assert traj.result is not None

    def test_env_acquire_failure_skips_run_and_eval(self):
        traj = _FakeTraj(fail_env=True)
        _run_batch({"i": {0: traj}})
        assert "connect" not in traj.events
        assert "generate" not in traj.events
        assert "evaluate" not in traj.events
        # init worker must still release the (partial) container
        assert "cleanup" in traj.events

    def test_connect_failure_skips_generate_and_eval(self):
        traj = _FakeTraj(fail_connect=True)
        _run_batch({"i": {0: traj}})
        assert "env" in traj.events
        assert "connect" in traj.events
        assert "generate" not in traj.events
        assert "evaluate" not in traj.events
        assert "cleanup" in traj.events

    def test_result_none_is_not_handed_to_eval(self):
        traj = _FakeTraj(result_none=True)
        _run_batch({"i": {0: traj}})
        assert "generate" in traj.events
        assert "evaluate" not in traj.events
        assert "cleanup" in traj.events

    def test_multiple_trajectories_all_complete(self):
        trajs = {"i": {0: _FakeTraj(), 1: _FakeTraj()}, "j": {0: _FakeTraj()}}
        _run_batch(trajs)
        for inner in trajs.values():
            for traj in inner.values():
                assert traj.events == [
                    "env", "connect", "generate", "evaluate", "cleanup",
                ]

    def test_empty_trajectories_is_noop(self):
        _run_batch({})  # must not raise

    def test_serial_when_concurrency_is_one(self):
        # max_init=max_run=max_eval=1 == the old "sequential" debug dispatcher.
        trajs = {"i": {0: _FakeTraj(), 1: _FakeTraj()}}
        _run_batch(trajs, _cfg(max_init_agents=1, max_eval_parallel_agents=1,
                               max_run_agents=1))
        for traj in trajs["i"].values():
            assert traj.events == [
                "env", "connect", "generate", "evaluate", "cleanup",
            ]


class TestRunBatchStreamingCallback:
    """Per-instance completion callback (streaming output) via run_batch."""

    def test_fires_once_per_instance_after_all_trajectories(self):
        fired = []

        async def on_done(iid):
            for traj in trajs[iid].values():
                assert "cleanup" in traj.events
            fired.append(iid)

        trajs = {"i": {0: _FakeTraj(), 1: _FakeTraj()}, "j": {0: _FakeTraj()}}
        _run_batch(trajs, _cfg(on_instance_complete=on_done))
        assert sorted(fired) == ["i", "j"]

    def test_fires_even_when_some_trajectories_fail(self):
        fired = []

        async def on_done(iid):
            fired.append(iid)

        trajs = {
            "i": {
                0: _FakeTraj(),
                1: _FakeTraj(fail_env=True),
                2: _FakeTraj(fail_connect=True),
            }
        }
        _run_batch(trajs, _cfg(on_instance_complete=on_done))
        assert fired == ["i"]


class TestContinuousStreaming:
    """start / submit / quiesce / aclose — the fully-async drive."""

    def test_streams_instances_and_fires_callback_once_each(self):
        async def scenario():
            fired = []

            async def on_done(iid):
                for t in trajs[iid].values():
                    assert "cleanup" in t.events
                fired.append(iid)

            trajs = {
                "i": {0: _FakeTraj(), 1: _FakeTraj()},
                "j": {0: _FakeTraj()},
                "k": {0: _FakeTraj(fail_env=True), 1: _FakeTraj(fail_connect=True)},
            }
            pipe = RolloutPipeline(_cfg(max_init_agents=4, max_eval_parallel_agents=4),
                                   on_instance_complete=on_done)
            pipe.start()
            for iid, inner in trajs.items():
                size = len(inner)
                for tid, t in inner.items():
                    await pipe.submit(iid, tid, t, size)
            await pipe.quiesce()
            assert sorted(fired) == ["i", "j", "k"]
            assert pipe.in_flight == 0
            await pipe.aclose()

        asyncio.run(scenario())

    def test_quiesce_on_idle_returns_immediately(self):
        async def scenario():
            pipe = RolloutPipeline(_cfg())
            pipe.start()
            await pipe.quiesce()  # nothing in flight -> returns at once
            assert pipe.in_flight == 0
            await pipe.aclose()

        asyncio.run(scenario())

    def test_submit_after_quiesce_resumes(self):
        """Mimics the weight-sync cycle: drain, then keep streaming."""
        async def scenario():
            done = []

            async def on_done(iid):
                done.append(iid)

            pipe = RolloutPipeline(_cfg(), on_instance_complete=on_done)
            pipe.start()
            await pipe.submit("a", 0, _FakeTraj(), 1)
            await pipe.quiesce()           # "weight sync" point
            assert sorted(done) == ["a"]
            await pipe.submit("b", 0, _FakeTraj(), 1)  # resume submitting
            await pipe.quiesce()
            assert sorted(done) == ["a", "b"]
            await pipe.aclose()

        asyncio.run(scenario())
