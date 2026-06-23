"""Tests for MCP veRL prompt/trajectory batch sizing."""

import pytest
from omegaconf import OmegaConf

pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.mcp_batch_sizing import (
    compute_mcp_batch_sizing,
    validate_mcp_batch_sizing,
)


def _base_config(strategy="fsdp2", *, ppo=8, rollout_n=4, trainer_gpus=8):
    return OmegaConf.create({
        "trainer": {
            "n_gpus_per_node": trainer_gpus,
            "nnodes": 1,
        },
        "async_training": {
            "require_batches": 3,
        },
        "actor_rollout_ref": {
            "actor": {
                "strategy": strategy,
                "ppo_mini_batch_size": ppo,
                "ulysses_sequence_parallel_size": 1,
                "megatron": {
                    "tensor_model_parallel_size": 1,
                    "context_parallel_size": 1,
                    "pipeline_model_parallel_size": 1,
                },
            },
            "rollout": {
                "n": rollout_n,
            },
        },
        "data": {
            "train_batch_size": ppo,
        },
    })


def test_fsdp_sizing_uses_prompt_times_rollout_n():
    cfg = _base_config("fsdp2", ppo=8, rollout_n=4, trainer_gpus=8)

    sizing = compute_mcp_batch_sizing(cfg)

    assert sizing.ppo_prompt_mini_batch_size == 8
    assert sizing.rollout_n == 4
    assert sizing.required_tasks == 24
    assert sizing.global_trajectory_minibatch == 32
    assert sizing.required_trajectories == 96
    assert sizing.dp == 8
    assert sizing.local_actor_minibatch == 4
    assert sizing.alignment_unit == 32
    assert validate_mcp_batch_sizing(cfg) == []


def test_fsdp_sizing_accounts_for_ulysses_sequence_parallelism():
    cfg = _base_config("fsdp2", ppo=8, rollout_n=4, trainer_gpus=8)
    cfg.actor_rollout_ref.actor.ulysses_sequence_parallel_size = 2

    sizing = compute_mcp_batch_sizing(cfg)

    assert sizing.dp == 4
    assert sizing.local_actor_minibatch == 8
    assert validate_mcp_batch_sizing(cfg) == []


def test_megatron_sizing_uses_ordinary_dp_not_expert_dp():
    cfg = _base_config("megatron", ppo=6, rollout_n=12, trainer_gpus=16)
    cfg.actor_rollout_ref.actor.megatron.tensor_model_parallel_size = 2
    cfg.actor_rollout_ref.actor.megatron.context_parallel_size = 2
    cfg.actor_rollout_ref.actor.megatron.pipeline_model_parallel_size = 2
    cfg.actor_rollout_ref.actor.megatron.expert_model_parallel_size = 4
    cfg.actor_rollout_ref.actor.megatron.expert_tensor_parallel_size = 1

    sizing = compute_mcp_batch_sizing(cfg)

    assert sizing.dp == 2
    assert sizing.required_tasks == 18
    assert sizing.global_trajectory_minibatch == 72
    assert sizing.required_trajectories == 216
    assert sizing.local_actor_minibatch == 36
    assert validate_mcp_batch_sizing(cfg) == []


def test_megatron_sizing_supports_legacy_topology_locations():
    cfg = _base_config("megatron", ppo=4, rollout_n=4, trainer_gpus=8)
    del cfg.actor_rollout_ref.actor["megatron"]
    cfg.actor_rollout_ref.model = {
        "tensor_model_parallel_size": 2,
        "context_parallel_size": 1,
        "pipeline_model_parallel_size": 2,
    }

    sizing = compute_mcp_batch_sizing(cfg)

    assert sizing.dp == 2
    assert sizing.global_trajectory_minibatch == 16
    assert sizing.local_actor_minibatch == 8
    assert validate_mcp_batch_sizing(cfg) == []


def test_validation_rejects_global_minibatch_not_divisible_by_dp():
    cfg = _base_config("fsdp2", ppo=5, rollout_n=3, trainer_gpus=8)

    errors = validate_mcp_batch_sizing(cfg)

    assert len(errors) == 2
    assert "global_trajectory_minibatch=15" in errors[0]
    assert "local_actor_minibatch" in errors[1]


def test_hybrid_validation_rejects_unaligned_train_prompt_batch():
    cfg = _base_config("fsdp2", ppo=8, rollout_n=2, trainer_gpus=4)

    errors = validate_mcp_batch_sizing(
        cfg,
        require_batches=1,
        train_prompt_batch_size=12,
    )

    assert len(errors) == 1
    assert "train_trajectories=24" in errors[0]
    assert "alignment_unit=16" in errors[0]


def test_batch_sizing_uses_rollout_n_not_mcp_agent_num_trajectories():
    cfg = _base_config("fsdp2", ppo=8, rollout_n=2, trainer_gpus=4)
    cfg.mcp_agent = {"num_trajectories": 4}

    sizing = compute_mcp_batch_sizing(cfg)

    assert sizing.rollout_n == 2
    assert sizing.global_trajectory_minibatch == 16
    assert validate_mcp_batch_sizing(cfg) == []
