"""
Main PPO entry point for MCP Agent training with VERL (Hybrid Mode).

This file only supports hybrid mode where actor and rollout share the same GPUs.
For fully async mode, use mcp_async_main.py instead.

Usage:
    python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \\
        --config-path /path/to/config \\
        --config-name mcp_trainer

    # Or with Hydra overrides
    python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \\
        trainer.total_epochs=5 \\
        mcp_agent.num_trajectories=4
"""
# pylint: disable=import-outside-toplevel

import os
import socket

import hydra
import ray
from omegaconf import OmegaConf
from loguru import logger

from verl.trainer.ppo.ray_trainer import ResourcePoolManager, Role
from verl.trainer.main_ppo import create_rl_dataset, create_rl_sampler
from verl.utils.device import is_cuda_available
from verl.utils.fs import copy_to_local
from verl.utils import hf_processor, hf_tokenizer

from .mcp_trainer import MCPPPOTrainer
from ..mcp_reward_manager import MCPRewardManager
from ..mcp_dataset import create_mcp_dataset, mcp_collate_fn
from ..utils import init_ray

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def run_ppo(config) -> None:
    """Initialize Ray cluster and run distributed PPO training."""
    # Use shared init_ray with tiktoken cache cleanup controlled by config
    clean_tiktoken = config.get("mcp_agent", {}).get("clean_tiktoken_cache", False)
    init_ray(config, clean_tiktoken_cache=clean_tiktoken)

    # Create TaskRunner for distributed training
    if (
        is_cuda_available
        and config.trainer.get("profile_steps") is not None
        and len(config.trainer.get("profile_steps", [])) > 0
    ):
        nsight_options = OmegaConf.to_container(config.trainer.controller_nsight_options)
        runner = TaskRunner.options(runtime_env={"nsight": nsight_options}).remote()
    else:
        runner = TaskRunner.remote()

    task = runner.run.remote(config)
    try:
        ray.get(task)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down...")
        ray.cancel(task)
        raise

    # veRL 0.7+ moved ray_init under ray_kwargs; support both layouts
    if hasattr(config, "ray_init"):
        ray_cfg = config.ray_init
    elif hasattr(config, "ray_kwargs") and hasattr(config.ray_kwargs, "ray_init"):
        ray_cfg = config.ray_kwargs.ray_init
    else:
        ray_cfg = {}
    timeline_json_file = ray_cfg.get("timeline_json_file", None) if hasattr(ray_cfg, "get") else None
    if timeline_json_file:
        ray.timeline(filename=timeline_json_file)


@ray.remote(num_cpus=1)
class TaskRunner:  # pylint: disable=too-few-public-methods
    """Ray remote class for executing distributed PPO training tasks."""

    def run(self, config):
        """Execute the main PPO training workflow."""
        from pprint import pprint

        logger.info(f"MCP TaskRunner hostname: {socket.gethostname()}, PID: {os.getpid()}")
        pprint(OmegaConf.to_container(config, resolve=True))
        OmegaConf.resolve(config)

        # MCP config validation
        mcp_cfg = config.get("mcp_agent", {})
        if mcp_cfg:
            logger.info("MCP Agent config:")
            logger.info(f"  - Agent mode: {mcp_cfg.get('agent_mode', 'react_train')}")
            logger.info(f"  - Num trajectories: {mcp_cfg.get('num_trajectories', 1)}")
            logger.info(f"  - Max iterations: {mcp_cfg.get('max_iterations', 10)}")
            logger.info(f"  - MCP servers: {mcp_cfg.get('mcp_servers', [])}")

        # Load model
        logger.info(f"Loading model from: {config.actor_rollout_ref.model.path}")
        local_path = copy_to_local(
            config.actor_rollout_ref.model.path,
            use_shm=config.actor_rollout_ref.model.get("use_shm", False),
            verbose=True,
        )

        # Initialize tokenizer and processor
        trust_remote_code = config.data.get("trust_remote_code", False)
        tokenizer = hf_tokenizer(local_path, trust_remote_code=trust_remote_code)
        processor = hf_processor(local_path, trust_remote_code=trust_remote_code, use_fast=True)

        # Worker classes based on strategy (hybrid mode only)
        if config.actor_rollout_ref.actor.strategy in {"fsdp", "fsdp2"}:
            assert config.critic.strategy in {"fsdp", "fsdp2"}
            from verl.single_controller.ray import RayWorkerGroup
            from verl.workers.fsdp_workers import (
                ActorRolloutRefWorker,
                AsyncActorRolloutRefWorker,
                CriticWorker
            )
            actor_rollout_cls = (
                AsyncActorRolloutRefWorker
                if config.actor_rollout_ref.rollout.mode == "async"
                else ActorRolloutRefWorker
            )
            ray_worker_group_cls = RayWorkerGroup

        else:
            raise NotImplementedError(
                f"Strategy {config.actor_rollout_ref.actor.strategy!r} not supported. "
                f"MCP currently supports 'fsdp' and 'fsdp2' only."
            )

        # Resource pool (hybrid mode: single pool for all roles)
        global_pool_id = "global_pool"
        resource_pool_spec = {
            global_pool_id: [config.trainer.n_gpus_per_node] * config.trainer.nnodes,
        }

        role_worker_mapping = {
            Role.ActorRollout: ray.remote(actor_rollout_cls),
            Role.Critic: ray.remote(CriticWorker),
        }

        mapping = {
            Role.ActorRollout: global_pool_id,
            Role.Critic: global_pool_id,
        }

        # Reward model
        if config.reward_model.enable:
            if config.reward_model.strategy in {"fsdp", "fsdp2"}:
                from verl.workers.fsdp_workers import RewardModelWorker  # pylint: disable=no-name-in-module
            else:
                raise NotImplementedError(
                    f"Reward model strategy {config.reward_model.strategy!r} not supported. "
                    f"MCP currently supports 'fsdp' and 'fsdp2' only."
                )
            role_worker_mapping[Role.RewardModel] = ray.remote(RewardModelWorker)
            mapping[Role.RewardModel] = global_pool_id

        # Reference policy
        if config.algorithm.use_kl_in_reward or config.actor_rollout_ref.actor.use_kl_loss:
            role_worker_mapping[Role.RefPolicy] = ray.remote(actor_rollout_cls)
            mapping[Role.RefPolicy] = global_pool_id

        # Create reward managers
        reward_fn = MCPRewardManager(
            tokenizer,
            num_examine=0,
            **config.reward_model.get("reward_kwargs", {})
        )
        val_reward_fn = MCPRewardManager(
            tokenizer,
            num_examine=1,
            **config.reward_model.get("reward_kwargs", {})
        )

        resource_pool_manager = ResourcePoolManager(
            resource_pool_spec=resource_pool_spec,
            mapping=mapping
        )

        # Create datasets - use MCPDataset for JSON files
        train_files = config.data.train_files
        val_files = config.data.val_files

        if train_files.endswith(".json"):
            train_dataset = create_mcp_dataset(train_files, config.data, tokenizer, processor, is_train=True)
            val_dataset = create_mcp_dataset(val_files, config.data, tokenizer, processor, is_train=False)
            collate_fn = mcp_collate_fn
        else:
            from verl.utils.dataset.rl_dataset import collate_fn
            train_dataset = create_rl_dataset(train_files, config.data, tokenizer, processor, is_train=True)
            val_dataset = create_rl_dataset(val_files, config.data, tokenizer, processor, is_train=False)

        train_sampler = create_rl_sampler(config.data, train_dataset)

        # Initialize trainer
        trainer = MCPPPOTrainer(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            reward_fn=reward_fn,
            val_reward_fn=val_reward_fn,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            collate_fn=collate_fn,
            train_sampler=train_sampler,
            device_name=config.trainer.device,
        )

        trainer.init_workers()
        trainer.fit()


@hydra.main(config_path=CONFIG_DIR, config_name="mcp_trainer", version_base=None)
def main(config):
    """Main entry point with Hydra configuration."""
    run_ppo(config)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
