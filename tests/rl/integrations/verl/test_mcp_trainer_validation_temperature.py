"""Tests for hybrid MCP trainer validation temperature overrides."""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from omegaconf import OmegaConf

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("tensordict")
pytest.importorskip("verl")

import torch
from tensordict import TensorDict
from verl import DataProto

from mcpuniverse.rl.integrations.verl.hybrid.mcp_trainer import (
    _AsyncTrackingBackend,
    MCPPPOTrainer,
    _normalize_hybrid_rollout_lifecycle_config,
    _normalize_mcp_dataloader_config,
    _wrap_slow_tracking_backends,
)
from mcpuniverse.rl.integrations.verl.mcp_batch_sizing import (
    ExcessivePaddingException,
    get_max_pad_ratio,
)


def _trainer(config, manager):
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.async_rollout_mode = True
    trainer.async_rollout_manager = manager
    return trainer


def test_validation_temperature_updates_plain_dict_loop_manager_config():
    config = OmegaConf.create({
        "mcp_agent": {
            "llm_config": {"temperature": 0.7},
            "val_llm_config": {"temperature": 0.0},
        },
    })
    manager = SimpleNamespace(
        mcp_config=SimpleNamespace(llm_config={"temperature": 0.7}),
        _llm_config_base={"temperature": 0.7},
    )
    trainer = _trainer(config, manager)

    state = trainer._set_val_temperature()

    assert config.mcp_agent.llm_config.temperature == 0.0
    assert manager.mcp_config.llm_config["temperature"] == 0.0
    assert manager._llm_config_base["temperature"] == 0.0

    trainer._restore_temperature(state)

    assert config.mcp_agent.llm_config.temperature == 0.7
    assert manager.mcp_config.llm_config["temperature"] == 0.7
    assert manager._llm_config_base["temperature"] == 0.7


def test_validation_temperature_restore_removes_missing_training_temperature():
    config = OmegaConf.create({
        "mcp_agent": {
            "llm_config": {},
            "val_llm_config": {"temperature": 0.0},
        },
    })
    manager = SimpleNamespace(
        mcp_config=SimpleNamespace(llm_config={}),
        _llm_config_base={},
    )
    trainer = _trainer(config, manager)

    state = trainer._set_val_temperature()

    assert config.mcp_agent.llm_config.temperature == 0.0
    assert manager.mcp_config.llm_config["temperature"] == 0.0
    assert manager._llm_config_base["temperature"] == 0.0

    trainer._restore_temperature(state)

    assert "temperature" not in config.mcp_agent.llm_config
    assert "temperature" not in manager.mcp_config.llm_config
    assert "temperature" not in manager._llm_config_base


def test_mcp_rollout_batch_balance_skips_by_default():
    config = OmegaConf.create({
        "trainer": {"balance_batch": True},
        "mcp_agent": {},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.actor_dp_size = 2
    trainer.alignment_unit = 1
    trainer._balance_batch = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("MCP rollout batch balancing should be opt-in")
        )
    )
    batch = SimpleNamespace(batch={"attention_mask": torch.ones((4, 8), dtype=torch.long)})
    metrics = {}

    trainer._maybe_balance_rollout_batch(batch, metrics)

    assert metrics["balance_batch/skipped_mcp_rollout"] == 1.0


def test_mcp_rollout_batch_balance_skips_single_dp_even_when_enabled():
    config = OmegaConf.create({
        "trainer": {"balance_batch": True},
        "mcp_agent": {"balance_rollout_batch": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.actor_dp_size = 1
    trainer.alignment_unit = 1
    trainer._balance_batch = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("single-DP rollout batch balancing is a no-op")
        )
    )
    batch = SimpleNamespace(batch={"attention_mask": torch.ones((4, 8), dtype=torch.long)})
    metrics = {}

    trainer._maybe_balance_rollout_batch(batch, metrics)

    assert metrics["balance_batch/skipped_single_dp"] == 1.0


def test_mcp_rollout_batch_balance_can_be_enabled_for_multi_dp():
    config = OmegaConf.create({
        "trainer": {"balance_batch": True},
        "mcp_agent": {"balance_rollout_batch": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.actor_dp_size = 2
    trainer.alignment_unit = 1
    calls = []
    trainer._balance_batch = lambda batch, metrics: calls.append((batch, metrics))
    batch = SimpleNamespace(batch={"attention_mask": torch.ones((4, 8), dtype=torch.long)})
    metrics = {}

    trainer._maybe_balance_rollout_batch(batch, metrics)

    assert calls == [(batch, metrics)]


def _build_dummy_batch(num_rows: int) -> DataProto:
    """Minimal DataProto with the keys ``_pad_batch_for_training`` reads."""
    attention_mask = torch.ones((num_rows, 8), dtype=torch.long)
    tensordict = TensorDict({"attention_mask": attention_mask}, batch_size=num_rows)
    return DataProto(
        batch=tensordict,
        non_tensor_batch={
            "uid": np.array([f"task-{i}" for i in range(num_rows)], dtype=object),
        },
        meta_info={"global_token_num": [8] * num_rows},
    )


def test_pad_batch_for_training_is_noop_when_already_aligned():
    trainer = object.__new__(MCPPPOTrainer)
    trainer.global_trajectory_minibatch = 4
    trainer._max_pad_ratio = 0.5
    batch = _build_dummy_batch(8)
    metrics: dict = {}

    out = trainer._pad_batch_for_training(batch, metrics)

    assert out is batch
    assert metrics["batch_sizing/pad_size"] == 0.0
    assert metrics["batch_sizing/aligned_trajectories"] == 8.0
    assert metrics["batch_sizing/collected_trajectories"] == 8.0


def test_pad_batch_for_training_repeats_head_to_align_with_global_minibatch():
    trainer = object.__new__(MCPPPOTrainer)
    trainer.global_trajectory_minibatch = 4
    # 3 -> 4 is a 25% pad; allow it explicitly so this test covers the
    # success path rather than the threshold guard.
    trainer._max_pad_ratio = 0.5
    batch = _build_dummy_batch(3)
    metrics: dict = {}

    out = trainer._pad_batch_for_training(batch, metrics)

    assert len(out) == 4
    # veRL's pad_dataproto_to_divisor repeats the first ``pad_size`` rows.
    assert out.non_tensor_batch["uid"].tolist() == [
        "task-0", "task-1", "task-2", "task-0",
    ]
    # meta_info["global_token_num"] must also be padded so downstream loss
    # aggregation can iterate ``len(global_token_num) == batch_size``.
    assert out.meta_info["global_token_num"] == [8, 8, 8, 8]
    assert metrics["batch_sizing/pad_size"] == 1.0
    assert metrics["batch_sizing/aligned_trajectories"] == 4.0
    assert metrics["batch_sizing/pad_ratio"] == pytest.approx(0.25)


def test_pad_batch_for_training_rejects_empty_batch():
    trainer = object.__new__(MCPPPOTrainer)
    trainer.global_trajectory_minibatch = 4
    trainer._max_pad_ratio = 0.5
    batch = _build_dummy_batch(0)
    with pytest.raises(ValueError, match="empty training batch"):
        trainer._pad_batch_for_training(batch, {})


def test_pad_batch_for_training_raises_when_pad_ratio_exceeds_threshold():
    """Collecting 1 of 4 needs pad_size=3 → ratio 0.75; with default
    threshold 0.1, the trainer must refuse the step."""
    trainer = object.__new__(MCPPPOTrainer)
    trainer.global_trajectory_minibatch = 4
    trainer._max_pad_ratio = 0.1
    batch = _build_dummy_batch(1)
    metrics: dict = {}

    with pytest.raises(ExcessivePaddingException) as excinfo:
        trainer._pad_batch_for_training(batch, metrics)

    exc = excinfo.value
    assert exc.pad_size == 3
    assert exc.batch_size == 4
    assert exc.pad_ratio == pytest.approx(0.75)
    assert exc.threshold == pytest.approx(0.1)
    # Metrics should record the skip so it shows up in wandb / tensorboard.
    assert metrics["batch_sizing/skipped_excessive_pad"] == 1.0
    assert metrics["batch_sizing/pad_ratio"] == pytest.approx(0.75)


def test_pad_batch_for_training_within_threshold_does_not_raise():
    """4 of 5 collected needs pad_size=1 → ratio 0.20; lifting threshold
    to 0.25 must let the pad proceed without raising."""
    trainer = object.__new__(MCPPPOTrainer)
    trainer.global_trajectory_minibatch = 5
    trainer._max_pad_ratio = 0.25
    batch = _build_dummy_batch(4)
    metrics: dict = {}

    out = trainer._pad_batch_for_training(batch, metrics)

    assert len(out) == 5
    assert metrics["batch_sizing/pad_ratio"] == pytest.approx(0.20)
    assert "batch_sizing/skipped_excessive_pad" not in metrics


def test_get_max_pad_ratio_reads_yaml_with_default():
    cfg = OmegaConf.create({"mcp_agent": {"batch_sizing": {"max_pad_ratio": 0.05}}})
    assert get_max_pad_ratio(cfg) == pytest.approx(0.05)

    # Missing field → fall back to DEFAULT_MAX_PAD_RATIO=0.1.
    cfg_empty = OmegaConf.create({"mcp_agent": {}})
    assert get_max_pad_ratio(cfg_empty) == pytest.approx(0.1)

    # Out-of-range values clamp into [0, 1].
    cfg_negative = OmegaConf.create({"mcp_agent": {"batch_sizing": {"max_pad_ratio": -0.5}}})
    assert get_max_pad_ratio(cfg_negative) == 0.0
    cfg_huge = OmegaConf.create({"mcp_agent": {"batch_sizing": {"max_pad_ratio": 42.0}}})
    assert get_max_pad_ratio(cfg_huge) == 1.0


# NOTE: ``_validation_scores_from_batch`` is an aspirational helper that
# would let the trainer bypass ``val_reward_fn`` when the rollout already
# supplied per-trajectory rewards. It is currently not implemented on
# ``MCPPPOTrainer`` and has no production caller; the corresponding test
# has been removed until the helper is actually wired in.


def test_sleep_replicas_handoff_keeps_old_lifecycle_when_free_cache_engine_false():
    config = OmegaConf.create({
        "actor_rollout_ref": {"rollout": {"free_cache_engine": False}},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config

    class _CheckpointManager:
        calls = 0

        def sleep_replicas(self):
            self.calls += 1

    checkpoint_manager = _CheckpointManager()
    trainer.checkpoint_manager = checkpoint_manager

    trainer._sleep_replicas_after_rollout("training rollout")

    assert checkpoint_manager.calls == 1


def test_sleep_replicas_handoff_aborts_stale_vllm_requests_before_sleep():
    # vLLM + new key name; verifies the fast-path covers vllm backend.
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "rollout": {"name": "vllm", "free_cache_engine": True},
        },
        "mcp_agent": {"direct_rollout_sleep_handoff": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.async_rollout_mode = True
    events = []

    class _RemoteSleep:
        def remote(self):
            async def _sleep():
                events.append("server_sleep")
            return _sleep()

    class _Server:
        sleep = _RemoteSleep()

    class _Replica:
        servers = [_Server()]

        async def abort_all_requests(self):
            events.append("abort")
            return {"aborted_count": 1}

        async def sleep(self):
            events.append("replica_sleep")

    class _Manager:
        rollout_replicas = [_Replica()]

        @staticmethod
        def _run_async_safely(coro):
            return asyncio.run(coro)

    class _CheckpointManager:
        calls = 0

        def sleep_replicas(self):
            self.calls += 1

    checkpoint_manager = _CheckpointManager()
    trainer.async_rollout_manager = _Manager()
    trainer.checkpoint_manager = checkpoint_manager

    trainer._sleep_replicas_after_rollout("validation")

    assert events == ["abort", "server_sleep"]
    assert checkpoint_manager.calls == 0


def test_sleep_replicas_handoff_uses_checkpoint_replicas_when_manager_has_none():
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "rollout": {"name": "vllm", "free_cache_engine": True},
        },
        "mcp_agent": {"direct_rollout_sleep_handoff": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.async_rollout_mode = True
    events = []

    class _RemoteSleep:
        def remote(self):
            async def _sleep():
                events.append("server_sleep")
            return _sleep()

    class _Server:
        sleep = _RemoteSleep()

    class _Replica:
        servers = [_Server()]

        async def abort_all_requests(self):
            events.append("abort")
            return {"aborted_count": 1}

    class _Manager:
        rollout_replicas = []

        @staticmethod
        def _run_async_safely(coro):
            return asyncio.run(coro)

    class _CheckpointManager:
        calls = 0
        replicas = [_Replica()]

        def sleep_replicas(self):
            self.calls += 1

    checkpoint_manager = _CheckpointManager()
    trainer.async_rollout_manager = _Manager()
    trainer.checkpoint_manager = checkpoint_manager

    trainer._sleep_replicas_after_rollout("training rollout")

    assert events == ["abort", "server_sleep"]
    assert checkpoint_manager.calls == 0


def test_hybrid_tito_normalizes_free_cache_engine_for_old_lifecycle():
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": True,
            "rollout": {"name": "vllm", "free_cache_engine": False},
        },
        "mcp_agent": {"rollout_mode": "token"},
    })

    _normalize_hybrid_rollout_lifecycle_config(config)

    assert config.actor_rollout_ref.rollout.free_cache_engine is True
    # normalize writes the NEW key name (legacy key is read-only fallback)
    assert config.mcp_agent.direct_rollout_sleep_handoff is True


def test_hybrid_tito_respects_explicit_direct_sleep_handoff_false():
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": True,
            "rollout": {"name": "vllm", "free_cache_engine": False},
        },
        "mcp_agent": {
            "rollout_mode": "token",
            "direct_rollout_sleep_handoff": False,
        },
    })

    _normalize_hybrid_rollout_lifecycle_config(config)

    assert config.actor_rollout_ref.rollout.free_cache_engine is True
    assert config.mcp_agent.direct_rollout_sleep_handoff is False


def test_hybrid_tito_legacy_direct_vllm_sleep_handoff_still_read():
    """Backwards-compat: legacy ``direct_vllm_sleep_handoff`` key is still
    honored (with a deprecation warning) so old configs/scripts keep working.
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": True,
            "rollout": {"name": "vllm", "free_cache_engine": False},
        },
        "mcp_agent": {
            "rollout_mode": "token",
            # legacy key set explicitly to False; normalize must not force it to True.
            "direct_vllm_sleep_handoff": False,
        },
    })

    _normalize_hybrid_rollout_lifecycle_config(config)

    assert config.actor_rollout_ref.rollout.free_cache_engine is True
    # legacy key passes through unchanged
    assert config.mcp_agent.direct_vllm_sleep_handoff is False
    # new key is NOT auto-set when legacy already has a value
    assert OmegaConf.select(config, "mcp_agent.direct_rollout_sleep_handoff") is None


def test_hybrid_tito_rejects_sglang_with_actionable_error():
    """Hybrid + SGLang is unsupported (veRL has no colocated SGLang worker).
    The normalize step hard-stops with a message pointing at fully_async.
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": True,
            "rollout": {"name": "sglang", "free_cache_engine": False},
        },
        "mcp_agent": {"rollout_mode": "token"},
    })

    with pytest.raises(RuntimeError) as exc_info:
        _normalize_hybrid_rollout_lifecycle_config(config)

    msg = str(exc_info.value)
    assert "Hybrid mode does not support SGLang" in msg
    assert "fully_async" in msg
    assert "start_multinode_async.sh" in msg


def test_hybrid_tito_normalize_skips_sglang_when_hybrid_engine_off():
    """If ``hybrid_engine=False`` (fully_async config accidentally loaded by
    the hybrid trainer), the SGLang hard-stop must NOT trigger — fully_async
    handles SGLang correctly via separate GPU pools.
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": False,
            "rollout": {"name": "sglang", "free_cache_engine": False},
        },
        "mcp_agent": {"rollout_mode": "token"},
    })

    # Should NOT raise — hybrid_engine=False means we're not actually colocating.
    _normalize_hybrid_rollout_lifecycle_config(config)


def test_hybrid_tito_normalize_skips_unknown_backend():
    """Other rollout backends (e.g. trtllm, future engines) are unaffected
    by MCP's vLLM/SGLang-specific lifecycle normalization.
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "hybrid_engine": True,
            "rollout": {"name": "trtllm", "free_cache_engine": False},
        },
        "mcp_agent": {"rollout_mode": "token"},
    })

    _normalize_hybrid_rollout_lifecycle_config(config)

    # No normalization happens for unknown backends.
    assert config.actor_rollout_ref.rollout.free_cache_engine is False
    assert OmegaConf.select(config, "mcp_agent.direct_rollout_sleep_handoff") is None
    assert OmegaConf.select(config, "mcp_agent.suspend_rollout_workers_during_postprocess") is None


def test_sleep_replicas_handoff_works_for_sglang_without_abort_all_requests():
    """SGLang's RolloutReplica.abort_all_requests is a TODO no-op (see
    verl/workers/rollout/replica.py:234). The MCP fast-path duck-types via
    ``getattr``; SGLang replicas without abort just skip the abort step and
    go straight to ``servers[i].sleep.remote()``.
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "rollout": {"name": "sglang", "free_cache_engine": True},
        },
        "mcp_agent": {"direct_rollout_sleep_handoff": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.async_rollout_mode = True
    events = []

    class _RemoteSleep:
        def remote(self):
            async def _sleep():
                events.append("server_sleep")
            return _sleep()

    class _Server:
        sleep = _RemoteSleep()

    class _Replica:
        servers = [_Server()]
        # NOTE: intentionally no abort_all_requests attribute — emulates
        # SGLang where the upstream replica doesn't implement abort.

        async def sleep(self):
            events.append("replica_sleep")

    class _Manager:
        rollout_replicas = [_Replica()]

        @staticmethod
        def _run_async_safely(coro):
            return asyncio.run(coro)

    class _CheckpointManager:
        calls = 0

        def sleep_replicas(self):
            self.calls += 1

    checkpoint_manager = _CheckpointManager()
    trainer.async_rollout_manager = _Manager()
    trainer.checkpoint_manager = checkpoint_manager

    trainer._sleep_replicas_after_rollout("training rollout")

    # No "abort" event — SGLang replica didn't expose the method.
    # Goes straight to server_sleep; checkpoint fallback is NOT invoked
    # (fast-path was taken successfully).
    assert events == ["server_sleep"]
    assert checkpoint_manager.calls == 0


def test_sleep_replicas_handoff_skipped_for_unknown_backend():
    """Backends outside _ROLLOUT_FAST_PATH_BACKENDS fall back to checkpoint
    manager (which knows how to drain + sleep that backend's own way).
    """
    config = OmegaConf.create({
        "actor_rollout_ref": {
            "rollout": {"name": "trtllm", "free_cache_engine": True},
        },
        "mcp_agent": {"direct_rollout_sleep_handoff": True},
    })
    trainer = object.__new__(MCPPPOTrainer)
    trainer.config = config
    trainer.async_rollout_mode = True

    class _Replica:
        servers = []

    class _Manager:
        rollout_replicas = [_Replica()]

        @staticmethod
        def _run_async_safely(coro):
            return asyncio.run(coro)

    class _CheckpointManager:
        calls = 0

        def sleep_replicas(self):
            self.calls += 1

    checkpoint_manager = _CheckpointManager()
    trainer.async_rollout_manager = _Manager()
    trainer.checkpoint_manager = checkpoint_manager

    trainer._sleep_replicas_after_rollout("training rollout")

    # Fast-path declined → checkpoint manager fallback called.
    assert checkpoint_manager.calls == 1


def test_mcp_json_dataloader_workers_forced_to_zero_in_memory():
    config = OmegaConf.create({
        "data": {
            "train_files": "/tmp/tasks.json",
            "dataloader_num_workers": 8,
        },
    })

    _normalize_mcp_dataloader_config(config)

    assert config.data.dataloader_num_workers == 0


def test_tracking_backends_wrapped_async():
    """Only network-bound backends (wandb / vemlp_wandb) get async-wrapped.

    Local console logging is fast and stays synchronous so it doesn't add
    a queue / thread for no benefit. The wrap targets are intentionally
    narrow — see ``_wrap_slow_tracking_backends``.
    """
    calls = []

    class _Backend:
        def __init__(self, name):
            self.name = name

        def log(self, data, step):
            calls.append((self.name, data, step))

        def finish(self, *args, **kwargs):
            calls.append((self.name, "finish", kwargs))

    console_backend = _Backend("console")
    wandb_backend = _Backend("wandb")
    tracking = SimpleNamespace(
        logger={
            "console": console_backend,
            "wandb": wandb_backend,
        }
    )
    config = OmegaConf.create({"mcp_agent": {}})

    _wrap_slow_tracking_backends(tracking, config)

    # Console is local — stays synchronous.
    assert tracking.logger["console"] is console_backend
    # wandb is network-bound — wrapped so logging cannot block training.
    assert isinstance(tracking.logger["wandb"], _AsyncTrackingBackend)

    for backend in tracking.logger.values():
        backend.log({"x": 1}, step=7)
        backend.finish(exit_code=0)

    assert ("console", {"x": 1}, 7) in calls
    assert ("wandb", {"x": 1}, 7) in calls
    assert ("console", "finish", {"exit_code": 0}) in calls
    assert ("wandb", "finish", {"exit_code": 0}) in calls
