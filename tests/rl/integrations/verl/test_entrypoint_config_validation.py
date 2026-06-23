"""Entrypoint-level config validation tests for MCP veRL integrations."""

from functools import lru_cache

import pytest
from omegaconf import OmegaConf

# The validated entrypoints import the full veRL/torch stack (optional extras
# not present in minimal CI), so skip this module when they are unavailable.
pytest.importorskip("verl")
pytest.importorskip("torch")


@lru_cache(maxsize=1)
def _entrypoint_validators():
    from mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main import (
        validate_async_config,
    )
    from mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo import (
        _task_runner_cpu_config,
        _validate_mcp_hybrid_batch_sizing,
        _validate_megatron_5d_parallelism,
    )

    return (
        validate_async_config,
        _validate_mcp_hybrid_batch_sizing,
        _validate_megatron_5d_parallelism,
        _task_runner_cpu_config,
    )


def _base_config(
    strategy: str = "fsdp2",
    *,
    ppo: int = 8,
    rollout_n: int = 2,
    trainer_gpus: int = 4,
    require_batches: int = 2,
):
    return OmegaConf.create({
        "trainer": {
            "n_gpus_per_node": trainer_gpus,
            "nnodes": 1,
        },
        "rollout": {
            "n_gpus_per_node": 1,
            "nnodes": 1,
        },
        "async_training": {
            "require_batches": require_batches,
        },
        "actor_rollout_ref": {
            "hybrid_engine": False,
            "actor": {
                "strategy": strategy,
                "ppo_mini_batch_size": ppo,
                "ulysses_sequence_parallel_size": 1,
                "megatron": {
                    "tensor_model_parallel_size": 1,
                    "context_parallel_size": 1,
                    "pipeline_model_parallel_size": 1,
                    "expert_model_parallel_size": 1,
                    "expert_tensor_parallel_size": 1,
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


def test_fully_async_entrypoint_accepts_valid_fsdp_config():
    validate_async_config, _, _, _ = _entrypoint_validators()

    validate_async_config(_base_config())


def test_fully_async_entrypoint_rejects_hybrid_engine():
    validate_async_config, _, _, _ = _entrypoint_validators()
    config = _base_config()
    config.actor_rollout_ref.hybrid_engine = True

    with pytest.raises(ValueError, match="hybrid_engine must be False"):
        validate_async_config(config)


def test_fully_async_entrypoint_rejects_unaligned_fsdp_batch_sizing():
    validate_async_config, _, _, _ = _entrypoint_validators()
    config = _base_config(ppo=5, rollout_n=3, trainer_gpus=8)

    with pytest.raises(ValueError, match="global_trajectory_minibatch=15"):
        validate_async_config(config)


def test_fully_async_entrypoint_rejects_megatron_moe_grouped_gemm_false():
    validate_async_config, _, _, _ = _entrypoint_validators()
    config = _base_config(strategy="megatron", ppo=4, rollout_n=2, trainer_gpus=8)
    config.actor_rollout_ref.actor.megatron.tensor_model_parallel_size = 2
    config.actor_rollout_ref.actor.megatron.override_transformer_config = {
        "moe_grouped_gemm": False,
    }

    with pytest.raises(ValueError, match="moe_grouped_gemm must be true"):
        validate_async_config(config)


def test_hybrid_entrypoint_accepts_valid_batch_sizing():
    _, validate_hybrid_batch_sizing, _, _ = _entrypoint_validators()

    validate_hybrid_batch_sizing(_base_config())


def test_hybrid_entrypoint_rejects_unaligned_train_batch_sizing():
    _, validate_hybrid_batch_sizing, _, _ = _entrypoint_validators()
    config = _base_config(ppo=8, rollout_n=2, trainer_gpus=4)
    config.data.train_batch_size = 12

    with pytest.raises(ValueError, match="train_trajectories=24"):
        validate_hybrid_batch_sizing(config)


def test_hybrid_entrypoint_rejects_invalid_megatron_topology():
    _, _, validate_megatron_topology, _ = _entrypoint_validators()
    config = _base_config(strategy="megatron", ppo=4, rollout_n=2, trainer_gpus=8)
    config.actor_rollout_ref.actor.megatron.tensor_model_parallel_size = 3

    with pytest.raises(ValueError, match=r"TP\*CP\*PP=3"):
        validate_megatron_topology(config)


def test_hybrid_task_runner_cpu_config_defaults_threads_to_cpus():
    _, _, _, task_runner_cpu_config = _entrypoint_validators()
    config = _base_config()
    config.trainer.task_runner_num_cpus = 8

    assert task_runner_cpu_config(config) == (8, 8)


def test_hybrid_task_runner_cpu_config_rejects_invalid_values():
    _, _, _, task_runner_cpu_config = _entrypoint_validators()
    config = _base_config()
    config.trainer.task_runner_num_cpus = 0

    with pytest.raises(ValueError, match="trainer.task_runner_num_cpus"):
        task_runner_cpu_config(config)
