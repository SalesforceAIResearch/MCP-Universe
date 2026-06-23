"""Tests for fully async queue consumption semantics."""

from types import SimpleNamespace

import numpy as np
import pytest

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("ray")
pytest.importorskip("torch")
pytest.importorskip("tensordict")
pytest.importorskip("verl")

import ray
import torch
from omegaconf import OmegaConf
from tensordict import TensorDict
from verl import DataProto

from mcpuniverse.rl.integrations.verl.fully_async.mcp_async_data import (
    MCP_BATCH_END_SENTINEL,
    MCPRolloutSample,
)
from mcpuniverse.rl.integrations.verl.fully_async.mcp_async_trainer import (
    MCPFullyAsyncTrainer,
)
from mcpuniverse.rl.integrations.verl.mcp_batch_sizing import (
    ExcessivePaddingException,
    MCPBatchSizing,
)


class _Queue:
    def __init__(self, items):
        self.items = list(items)
        self.consumed = 0

    def get_sample_sync(self):
        if not self.items:
            return None
        item = self.items.pop(0)
        self.consumed += 1
        return item, len(self.items)


def _data_proto(uid: str, reward: float = 0.0, response_len: int = 2, rows: int = 1) -> DataProto:
    prompt = torch.full((rows, 1), 11, dtype=torch.long)
    response = torch.arange(21, 21 + response_len, dtype=torch.long).repeat(rows, 1)
    response_mask = torch.ones((rows, response_len), dtype=torch.long)
    input_ids = torch.cat([prompt, response], dim=1)
    attention_mask = torch.ones_like(input_ids)
    position_ids = torch.arange(input_ids.shape[-1], dtype=torch.long).repeat(rows, 1)

    batch = TensorDict(
        {
            "prompts": prompt,
            "responses": response,
            "response_mask": response_mask,
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
        },
        batch_size=rows,
    )
    return DataProto(
        batch=batch,
        non_tensor_batch={
            "rewards": np.array([reward] * rows, dtype=float),
            "uid": np.array([uid] * rows, dtype=object),
        },
        meta_info={"stable": "same"},
    )


def _sample(
    uid: str,
    *,
    data: DataProto | None = None,
    reward: float = 0.0,
    rows: int = 1,
) -> MCPRolloutSample:
    return MCPRolloutSample(
        data=_data_proto(uid, reward=reward, rows=rows) if data is None else data,
        param_version=3,
        instance_id=uid,
        sample_id=f"sample-{uid}",
        processing_time=1.5,
    )


def _serialized(sample: MCPRolloutSample) -> bytes:
    return ray.cloudpickle.dumps(sample)


def _trainer(
    *,
    required_tasks: int,
    required_trajectories: int | None = None,
    alignment_unit: int = 4,
    actor_dp_size: int = 1,
    partial_rollout: bool = False,
    global_trajectory_minibatch: int = 4,
    max_pad_ratio: float = 1.0,
):
    trainer_cls = MCPFullyAsyncTrainer.__ray_metadata__.modified_class
    trainer = trainer_cls.__new__(trainer_cls)
    resolved_required_trajectories = required_trajectories or required_tasks * 4
    trainer.required_tasks = required_tasks
    trainer.required_trajectories = resolved_required_trajectories
    trainer.global_trajectory_minibatch = global_trajectory_minibatch
    trainer.local_actor_minibatch = 2
    trainer.alignment_unit = alignment_unit
    trainer.actor_dp_size = actor_dp_size
    # Use real MCPBatchSizing so trainer can call ``self.batch_sizing.to_meta_info()``
    # in _get_samples_from_queue (mirrors production wiring).
    trainer.batch_sizing = MCPBatchSizing(
        strategy="fsdp2",
        ppo_prompt_mini_batch_size=1,
        rollout_n=1,
        require_batches=1,
        dp=actor_dp_size,
        required_tasks=required_tasks,
        global_trajectory_minibatch=global_trajectory_minibatch,
        required_trajectories=resolved_required_trajectories,
        local_actor_minibatch=2,
        alignment_unit=alignment_unit,
    )
    trainer.tokenizer = SimpleNamespace(pad_token_id=0)
    trainer._max_pad_ratio = max_pad_ratio
    trainer.config = OmegaConf.create({
        "async_training": {"partial_rollout": partial_rollout},
    })
    return trainer


def test_queue_collection_is_task_based_and_allows_missing_trajectories():
    # global_trajectory_minibatch=1 turns _pad_batch_for_training into a no-op
    # so this test exercises pure queue/collection semantics.
    trainer = _trainer(
        required_tasks=2,
        required_trajectories=2,
        alignment_unit=1,
        global_trajectory_minibatch=1,
    )
    invalid_task = MCPRolloutSample(
        data=None,
        param_version=3,
        instance_id="failed-task",
        sample_id="sample-failed-task",
    )
    queue = _Queue([
        _serialized(invalid_task),
        _serialized(_sample("valid-task", reward=1.0)),
        _serialized(_sample("extra-task", reward=0.5)),
    ])
    trainer.message_queue_client = queue

    status, batch = trainer._get_samples_from_queue()

    assert status == 0
    assert queue.consumed == 2
    assert len(queue.items) == 1
    assert len(batch) == 1
    assert batch.non_tensor_batch["uid"].tolist() == ["valid-task"]
    assert batch.non_tensor_batch["rewards"].tolist() == [1.0]
    assert batch.meta_info["fully_async/task_items"] == 2
    assert batch.meta_info["fully_async/actual_trajectories"] == 1


def test_queue_collection_pads_tail_for_global_minibatch_alignment():
    """Collected 3 < ``global_trajectory_minibatch=4`` → pad to 4 via
    veRL's repeat-pad helper (first sample is duplicated to the tail)."""
    trainer = _trainer(
        required_tasks=3,
        required_trajectories=3,
        actor_dp_size=2,
        global_trajectory_minibatch=4,
        # 3 → 4 is a 25% pad; allow it explicitly for this test.
        max_pad_ratio=0.5,
    )
    queue = _Queue([
        _serialized(_sample("task-a", reward=0.25)),
        _serialized(_sample("task-b", reward=0.5)),
        _serialized(_sample("task-c", reward=0.75)),
    ])
    trainer.message_queue_client = queue

    status, batch = trainer._get_samples_from_queue()

    assert status == 0
    assert queue.consumed == 3
    assert len(batch) == 4
    # Pad-by-repeat copies real trajectories from the head; tail gets task-a back.
    assert batch.non_tensor_batch["uid"].tolist() == [
        "task-a", "task-b", "task-c", "task-a",
    ]
    assert batch.meta_info["fully_async/task_items"] == 3
    # actual_trajectories reflects the padded size that actor_wg actually trains on.
    assert batch.meta_info["fully_async/actual_trajectories"] == 4


def test_queue_collection_raises_when_pad_ratio_exceeds_threshold():
    """Collected 1 of 4 needs pad_size=3 → ratio 0.75; with explicit
    threshold 0.1, ``_get_samples_from_queue`` must raise so the outer
    fit loop can skip this step instead of taking a heavily-biased
    PPO update."""
    trainer = _trainer(
        required_tasks=1,
        required_trajectories=1,
        global_trajectory_minibatch=4,
        max_pad_ratio=0.1,
    )
    queue = _Queue([
        _serialized(_sample("task-a", reward=0.25)),
    ])
    trainer.message_queue_client = queue

    with pytest.raises(ExcessivePaddingException) as excinfo:
        trainer._get_samples_from_queue()

    exc = excinfo.value
    assert exc.pad_size == 3
    assert exc.batch_size == 4
    assert exc.pad_ratio == pytest.approx(0.75)


def test_batch_end_sentinel_accepts_aligned_partial_rollout_when_enabled():
    trainer = _trainer(
        required_tasks=4,
        required_trajectories=4,
        alignment_unit=4,
        partial_rollout=True,
    )
    queue = _Queue([
        _serialized(_sample("task-a", reward=0.25, rows=4)),
        MCP_BATCH_END_SENTINEL,
        _serialized(_sample("task-b", reward=0.5)),
    ])
    trainer.message_queue_client = queue

    status, batch = trainer._get_samples_from_queue()

    assert status == 0
    assert queue.consumed == 2
    assert len(queue.items) == 1
    assert len(batch) == 4
    assert batch.non_tensor_batch["uid"].tolist() == ["task-a"] * 4
    assert batch.meta_info["fully_async/task_items"] == 1


def test_batch_end_sentinel_is_ignored_when_partial_rollout_is_disabled():
    # global_trajectory_minibatch=1 turns _pad_batch_for_training into a no-op
    # so this test exercises pure sentinel-handling semantics, not padding.
    trainer = _trainer(
        required_tasks=2,
        required_trajectories=2,
        partial_rollout=False,
        global_trajectory_minibatch=1,
    )
    queue = _Queue([
        _serialized(_sample("task-a", reward=0.25)),
        MCP_BATCH_END_SENTINEL,
        _serialized(_sample("task-b", reward=0.5)),
    ])
    trainer.message_queue_client = queue

    status, batch = trainer._get_samples_from_queue()

    assert status == 0
    assert queue.consumed == 3
    assert len(batch) == 2
    assert batch.non_tensor_batch["uid"].tolist() == ["task-a", "task-b"]
