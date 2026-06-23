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
        actor_rollout_ref.rollout.n=4
"""
# pylint: disable=import-outside-toplevel

import os
import socket
import sys

import hydra
import ray
from omegaconf import OmegaConf
from loguru import logger

from verl.trainer.ppo.ray_trainer import ResourcePoolManager, Role
from verl.trainer.main_ppo import create_rl_sampler
from verl.utils.device import is_cuda_available
from verl.utils.fs import copy_to_local
from verl.utils import hf_processor, hf_tokenizer

from .mcp_trainer import MCPPPOTrainer
from ..mcp_reward_manager import MCPRewardManager
from ..mcp_dataset import create_mcp_dataset, mcp_collate_fn
from ..mcp_batch_sizing import compute_mcp_batch_sizing, validate_mcp_batch_sizing
from ..utils import init_ray

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def _validate_megatron_5d_parallelism(config) -> None:
    """Validate Megatron 5D parallelism topology in hybrid mode.

    5D dimensions:
      - TP: tensor model parallel
      - EP: expert model parallel
      - CP: context parallel
      - PP: pipeline model parallel
      - DP: data parallel (derived from total GPUs / TP*EP*CP*PP)
    """
    # Prefer values under actor.megatron (required by current upstream veRL worker),
    # then fall back to legacy locations for compatibility.
    tp = OmegaConf.select(config, "actor_rollout_ref.actor.megatron.tensor_model_parallel_size", default=None)
    if tp is None:
        tp = OmegaConf.select(config, "actor_rollout_ref.model.tensor_model_parallel_size", default=None)
    if tp is None:
        tp = OmegaConf.select(config, "actor_rollout_ref.actor.tensor_model_parallel_size", default=1)
    pp = OmegaConf.select(config, "actor_rollout_ref.actor.megatron.pipeline_model_parallel_size", default=None)
    if pp is None:
        pp = OmegaConf.select(config, "actor_rollout_ref.model.pipeline_model_parallel_size", default=1)
    cp = OmegaConf.select(config, "actor_rollout_ref.actor.megatron.context_parallel_size", default=None)
    if cp is None:
        cp = OmegaConf.select(config, "actor_rollout_ref.model.context_parallel_size", default=1)
    ep = OmegaConf.select(config, "actor_rollout_ref.actor.megatron.expert_model_parallel_size", default=None)
    if ep is None:
        ep = OmegaConf.select(config, "actor_rollout_ref.model.expert_model_parallel_size", default=1)
    etp = OmegaConf.select(config, "actor_rollout_ref.actor.megatron.expert_tensor_parallel_size", default=None)
    if etp is None:
        etp = OmegaConf.select(config, "actor_rollout_ref.model.expert_tensor_parallel_size", default=tp)

    dims = {"tp": tp, "ep": ep, "etp": etp, "cp": cp, "pp": pp}
    for name, value in dims.items():
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"Megatron {name} must be a positive integer, got: {value!r}")

    total_gpus = int(config.trainer.n_gpus_per_node) * int(config.trainer.nnodes)
    # Megatron-Core has separate ordinary and expert DP groups:
    # - ordinary DP for dense/attention layers and actor PPO batch splitting:
    #   world / (TP * CP * PP)
    # - expert DP for MoE expert groups:
    #   world / (ETP * EP * PP)
    model_parallel_product = tp * cp * pp
    expert_parallel_product = etp * ep * pp
    if model_parallel_product > total_gpus:
        raise ValueError(
            f"Invalid Megatron topology: TP*CP*PP={model_parallel_product} exceeds total GPUs={total_gpus}"
        )
    if total_gpus % model_parallel_product != 0:
        raise ValueError(
            f"Invalid Megatron topology: total GPUs={total_gpus} is not divisible by TP*CP*PP={model_parallel_product}"
        )
    if expert_parallel_product > total_gpus:
        raise ValueError(
            f"Invalid Megatron topology: ETP*EP*PP={expert_parallel_product} exceeds total GPUs={total_gpus}"
        )
    if total_gpus % expert_parallel_product != 0:
        raise ValueError(
            f"Invalid Megatron topology: total GPUs={total_gpus} is not divisible by "
            f"ETP*EP*PP={expert_parallel_product}"
        )

    dp = total_gpus // model_parallel_product
    expert_dp = total_gpus // expert_parallel_product
    if int(config.trainer.n_gpus_per_node) % tp != 0:
        logger.warning(
            "trainer.n_gpus_per_node={} is not divisible by TP={}; "
            "this can hurt intra-node TP communication performance.",
            config.trainer.n_gpus_per_node, tp,
        )

    logger.info(
        "Megatron topology validated: TP={}, CP={}, PP={}, DP={}, ETP={}, EP={}, expert_DP={}, total_gpus={}",
        tp, cp, pp, dp, etp, ep, expert_dp, total_gpus,
    )


def _validate_mcp_hybrid_batch_sizing(config) -> None:
    """Validate MCP hybrid prompt/trajectory/local-DP batch sizing."""
    train_prompt_batch_size = OmegaConf.select(config, "data.train_batch_size", default=None)
    errors = validate_mcp_batch_sizing(
        config,
        require_batches=1,
        train_prompt_batch_size=train_prompt_batch_size,
    )
    if errors:
        raise ValueError("MCP hybrid batch sizing errors:\n" + "\n".join(f"  - {e}" for e in errors))

    sizing = compute_mcp_batch_sizing(config, require_batches=1)
    logger.info(
        "MCP hybrid batch sizing validated: strategy={} ppo_prompt_mini_batch_size={} "
        "rollout_n={} global_trajectory_minibatch={} actor_dp={} "
        "local_actor_minibatch={} alignment_unit={} train_prompt_batch_size={}",
        sizing.strategy,
        sizing.ppo_prompt_mini_batch_size,
        sizing.rollout_n,
        sizing.global_trajectory_minibatch,
        sizing.dp,
        sizing.local_actor_minibatch,
        sizing.alignment_unit,
        train_prompt_batch_size,
    )


def _positive_int_config(config, key: str, default: int) -> int:
    value = OmegaConf.select(config, key, default=default)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer, got: {value!r}") from exc
    if value < 1:
        raise ValueError(f"{key} must be a positive integer, got: {value!r}")
    return value


def _task_runner_cpu_config(config) -> tuple[int, int]:
    """Resolve TaskRunner Ray CPU reservation + intra-process thread count.

    Called independently in the driver process (for Ray ``num_cpus``) and
    inside the TaskRunner Ray actor (for OMP / torch thread setup). The
    cross-process duplication is unavoidable because Ray serializes config
    by value into each actor; the per-process cost is two ``OmegaConf.select``
    reads, which is negligible.
    """
    num_cpus = _positive_int_config(config, "trainer.task_runner_num_cpus", 1)
    num_threads = _positive_int_config(config, "trainer.task_runner_num_threads", num_cpus)
    return num_cpus, num_threads


def _configure_task_runner_threads(config) -> None:
    """Keep CPU-bound postprocess work from running inside a 1-thread actor."""
    num_cpus, num_threads = _task_runner_cpu_config(config)
    thread_env_vars = (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    previous = {
        name: os.environ.get(name)
        for name in thread_env_vars
        if os.environ.get(name) not in (None, str(num_threads))
    }
    for name in thread_env_vars:
        os.environ[name] = str(num_threads)

    torch_threads = None
    torch_interop_threads = None
    try:
        import torch

        torch.set_num_threads(num_threads)
        try:
            torch.set_num_interop_threads(max(1, min(4, num_threads)))
        except RuntimeError as exc:
            logger.warning("Unable to set TaskRunner torch interop threads: {}", exc)
        torch_threads = torch.get_num_threads()
        torch_interop_threads = torch.get_num_interop_threads()
    except Exception as exc:  # pylint: disable=broad-exception-caught  # pragma: no cover
        logger.warning("Unable to configure TaskRunner torch CPU threads: {}", exc)

    logger.info(
        "TaskRunner CPU config: ray_num_cpus={}, env_threads={}, torch_num_threads={}, "
        "torch_interop_threads={}, overwritten_env={}",
        num_cpus,
        num_threads,
        torch_threads,
        torch_interop_threads,
        previous,
    )


def _configure_task_runner_logging(config) -> None:
    """Make TaskRunner logging non-blocking without dropping old log content."""
    enabled = bool(OmegaConf.select(config, "mcp_agent.async_taskrunner_logging", default=True))
    if not enabled:
        return

    level = os.environ.get("LOGURU_LEVEL", "INFO")
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    try:
        logger.remove()
    except ValueError:
        pass
    logger.add(
        sys.stderr,
        level=level,
        format=log_format,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    logger.info(
        "TaskRunner async logging enabled; log content is preserved but "
        "Ray stdout/stderr backpressure will not block rollout postprocess."
    )


def run_ppo(config) -> None:
    """Initialize Ray cluster and run distributed PPO training."""
    # Use shared init_ray with tiktoken cache cleanup controlled by config
    clean_tiktoken = config.get("mcp_agent", {}).get("clean_tiktoken_cache", False)
    init_ray(config, clean_tiktoken_cache=clean_tiktoken)

    # Create TaskRunner for distributed training
    num_cpus, _ = _task_runner_cpu_config(config)
    task_runner_options: dict = {"num_cpus": num_cpus}
    if (
        is_cuda_available
        and config.trainer.get("profile_steps") is not None
        and len(config.trainer.get("profile_steps", [])) > 0
    ):
        nsight_options = OmegaConf.to_container(config.trainer.controller_nsight_options)
        task_runner_options["runtime_env"] = {"nsight": nsight_options}
    logger.info("Launching TaskRunner with Ray options: {}", task_runner_options)
    runner = TaskRunner.options(**task_runner_options).remote()

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

    def run(self, config):  # pylint: disable=too-many-locals,too-many-statements
        """Execute the main PPO training workflow."""
        from pprint import pprint

        # Newer Megatron-Core asserts NVTE_* env vars are unset so it can
        # configure them via --attention-backend.  Remove them in every Ray
        # worker regardless of how the node's shell was configured.
        for _nvte_var in ("NVTE_FLASH_ATTN", "NVTE_FUSED_ATTN", "NVTE_UNFUSED_ATTN"):
            os.environ.pop(_nvte_var, None)

        _configure_task_runner_logging(config)
        _configure_task_runner_threads(config)

        logger.info(f"MCP TaskRunner hostname: {socket.gethostname()}, PID: {os.getpid()}")
        pprint(OmegaConf.to_container(config, resolve=True))
        OmegaConf.resolve(config)

        # MCP config validation
        mcp_cfg = config.get("mcp_agent", {})
        if mcp_cfg:
            rollout_n = config.actor_rollout_ref.rollout.get("n", 1)
            logger.info("MCP Agent config:")
            logger.info(f"  - Agent mode: {mcp_cfg.get('agent_mode', 'react_train')}")
            logger.info(
                f"  - Rollout trajectories: {rollout_n} "
                "(actor_rollout_ref.rollout.n, synced to mcp_agent.num_trajectories)"
            )
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
        strategy = config.actor_rollout_ref.actor.strategy
        if strategy in {"fsdp", "fsdp2"}:
            if config.critic.enable:
                assert config.critic.strategy in {"fsdp", "fsdp2"}, (
                    "When actor uses FSDP in hybrid mode, critic.strategy must "
                    "be 'fsdp' or 'fsdp2'."
                )
            from verl.single_controller.ray import RayWorkerGroup
            from verl.workers.fsdp_workers import CriticWorker
            from .mcp_workers import (
                MCPHybridFSDPActorRolloutRefWorker,
                MCPHybridFSDPAsyncActorRolloutRefWorker,
            )
            actor_rollout_cls = (
                MCPHybridFSDPAsyncActorRolloutRefWorker
                if config.actor_rollout_ref.rollout.mode == "async"
                else MCPHybridFSDPActorRolloutRefWorker
            )
            critic_worker_cls = CriticWorker
            ray_worker_group_cls = RayWorkerGroup

        elif strategy == "megatron":
            if config.critic.enable:
                assert config.critic.strategy == "megatron", (
                    "When actor uses Megatron in hybrid mode, critic.strategy must be 'megatron'."
                )
            _validate_megatron_5d_parallelism(config)
            from verl.single_controller.ray import RayWorkerGroup
            try:
                from verl.workers.megatron_workers import CriticWorker
                from .mcp_workers import (
                    MCPHybridMegatronActorRolloutRefWorker,
                    MCPHybridMegatronAsyncActorRolloutRefWorker,
                )
            except ImportError as exc:
                raise ImportError(
                    "Megatron workers are not available in current veRL installation. "
                    "Please install veRL with Megatron support."
                ) from exc
            actor_rollout_cls = (
                MCPHybridMegatronAsyncActorRolloutRefWorker
                if config.actor_rollout_ref.rollout.mode == "async"
                else MCPHybridMegatronActorRolloutRefWorker
            )
            critic_worker_cls = CriticWorker
            ray_worker_group_cls = RayWorkerGroup
        else:
            raise NotImplementedError(
                f"Strategy {strategy!r} not supported. "
                "MCP currently supports 'fsdp', 'fsdp2', and 'megatron' in hybrid mode."
            )
        _validate_mcp_hybrid_batch_sizing(config)

        # Resource pool (hybrid mode: single pool for all roles)
        global_pool_id = "global_pool"
        resource_pool_spec = {
            global_pool_id: [config.trainer.n_gpus_per_node] * config.trainer.nnodes,
        }

        role_worker_mapping = {
            Role.ActorRollout: ray.remote(actor_rollout_cls),
        }

        mapping = {
            Role.ActorRollout: global_pool_id,
        }

        # Only spin up a critic worker for value-based PPO; GRPO and other
        # critic-less algorithms (the MCP default) skip this to avoid the
        # extra Ray actor.
        if config.critic.enable:
            role_worker_mapping[Role.Critic] = ray.remote(critic_worker_cls)
            mapping[Role.Critic] = global_pool_id

        # Reward model
        if config.reward_model.enable:
            if config.reward_model.strategy in {"fsdp", "fsdp2"}:
                from verl.workers.fsdp_workers import RewardModelWorker  # pylint: disable=no-name-in-module
            elif config.reward_model.strategy == "megatron":
                try:
                    from verl.workers.megatron_workers import RewardModelWorker
                except ImportError as exc:
                    raise ImportError(
                        "Megatron RewardModelWorker is not available in current veRL installation."
                    ) from exc
            else:
                raise NotImplementedError(
                    f"Reward model strategy {config.reward_model.strategy!r} not supported. "
                    "MCP currently supports 'fsdp', 'fsdp2', and 'megatron'."
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

        # MCP training requires JSON datasets (parquet / list-of-files inputs are
        # not supported; the per-row prompt + MCP task metadata is JSON-only).
        train_files = config.data.train_files
        val_files = config.data.val_files
        for label, path in (("train_files", train_files), ("val_files", val_files)):
            if not isinstance(path, str) or not path.endswith(".json"):
                raise ValueError(
                    f"MCP hybrid training requires a single JSON file for "
                    f"data.{label}, got {path!r}. Multi-file lists and "
                    f"parquet/HF datasets are not supported."
                )

        train_dataset = create_mcp_dataset(
            train_files, config.data, tokenizer, processor, is_train=True,
        )
        val_dataset = create_mcp_dataset(
            val_files, config.data, tokenizer, processor, is_train=False,
        )
        collate_fn = mcp_collate_fn

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
