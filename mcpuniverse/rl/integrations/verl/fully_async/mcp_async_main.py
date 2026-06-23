# pylint: disable=too-few-public-methods,no-value-for-parameter

"""
MCP Fully Async Training Entry Point.

Orchestrates MCPFullyAsyncRollouter and MCPFullyAsyncTrainer via a
MessageQueue and ParameterSynchronizer. Both run concurrently as Ray
actors, communicating through the queue.

Architecture:
    +--------------+    MessageQueue    +--------------+
    |  Rollouter   | ---- (push) ---->  |   Trainer    |
    | (rollout GPU)| <-- (weights) ---- | (train GPU)  |
    +--------------+  ParameterSync     +--------------+

    - Rollouter: runs inference engine (vLLM/SGLang) on rollout GPUs,
      generates MCP agent multi-turn trajectories, pushes to MessageQueue
    - Trainer: pulls rollout data from MessageQueue, runs PPO training (FSDP/Megatron),
      triggers NCCL weight broadcast back to Rollouter via ParameterSynchronizer
    - MessageQueue: Ray actor, data buffer from Rollouter to Trainer
    - ParameterSynchronizer: handles weight sync from Trainer to Rollouter

Training stops when Rollouter exhausts its data and closes the queue.
Trainer detects queue closure (None) and exits via TrainingStopException.

Usage:
    python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \\
        --config-path=config \\
        --config-name=mcp_fully_async

Based on veRL upstream's fully_async_main.py (Meituan contribution),
adapted for MCP agent training.
"""

import asyncio
import os
import socket
import threading
from pprint import pprint

import hydra
import ray
from omegaconf import DictConfig, OmegaConf, open_dict

from verl.experimental.fully_async_policy.message_queue import MessageQueue, MessageQueueClient
from verl.single_controller.ray import RayWorkerGroup
from verl.trainer.ppo.ray_trainer import ResourcePoolManager
from verl.trainer.ppo.utils import Role, need_reference_policy
from verl.utils import hf_processor, hf_tokenizer
from verl.utils.fs import copy_to_local

from ..mcp_batch_sizing import compute_mcp_batch_sizing, validate_mcp_batch_sizing
from ..utils import _LazyLogger, init_ray

from .mcp_async_rollouter import MCPFullyAsyncRollouter
from .mcp_async_trainer import MCPFullyAsyncTrainer
from .mcp_async_workers import MCPAsyncRolloutWorker, MCPDetachActorWorker
from .mcp_param_sync import MCPParameterSynchronizer

logger = _LazyLogger()

try:
    from verl.workers.fsdp_workers import CriticWorker as FSDPCriticWorker
    _HAS_VERL_FSDP_WORKERS = True
except ImportError:
    _HAS_VERL_FSDP_WORKERS = False

try:
    from verl.workers.megatron_workers import CriticWorker as MegatronCriticWorker
    from .mcp_megatron_async_workers import MCPMegatronAsyncRolloutWorker, MCPMegatronDetachActorWorker
    _HAS_VERL_MEGATRON_WORKERS = True
except ImportError:
    _HAS_VERL_MEGATRON_WORKERS = False

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def create_resource_pool_manager(config, roles: list) -> ResourcePoolManager:
    """Create GPU resource pool manager.

    In fully async mode, GPUs are split into two non-overlapping pools:
    - trainer_pool: shared by Actor (FSDP), Critic, RefPolicy
    - rollout_pool: dedicated to inference engine (vLLM/SGLang)

    This separation is the key difference from hybrid mode (shared GPUs).
    """
    resource_pool_spec = {}
    mapping = {}

    training_roles = {Role.Actor, Role.ActorRollout, Role.Critic, Role.RefPolicy, Role.RewardModel}
    if any(role in roles for role in training_roles):
        assert config.trainer.n_gpus_per_node > 0
        assert config.trainer.nnodes > 0
        # e.g. n_gpus_per_node=4, nnodes=2 -> trainer_pool = [4, 4] (8 GPUs total)
        trainer_pool = [config.trainer.n_gpus_per_node] * config.trainer.nnodes
        resource_pool_spec["trainer_pool"] = trainer_pool
        for role in training_roles:
            if role in roles:
                mapping[role] = "trainer_pool"

    if Role.Rollout in roles:
        assert config.rollout.n_gpus_per_node > 0
        assert config.rollout.nnodes > 0
        rollout_pool = [config.rollout.n_gpus_per_node] * config.rollout.nnodes
        resource_pool_spec["rollout_pool"] = rollout_pool
        mapping[Role.Rollout] = "rollout_pool"

    return ResourcePoolManager(resource_pool_spec=resource_pool_spec, mapping=mapping)


def create_role_worker_mapping(config):
    """Create Role -> Worker class mapping.

    Worker classes under FSDP strategy:
    - MCPDetachActorWorker: extends upstream DetachActorWorker for FSDP training.
      "Detach" = actor and rollout on separate GPUs (vs hybrid = shared GPUs).
    - MCPAsyncRolloutWorker: extends upstream DetachAsyncRolloutWorker, overrides
      sync_rollout_weights() to push NCCL-received weights to inference engine
      via ServerAdapter.update_weights() (CUDA IPC).
    - FSDPCriticWorker: upstream CriticWorker, no MCP customization needed.

    Worker classes under Megatron strategy:
    - MCPMegatronDetachActorWorker: extends Megatron DetachActorWorker with
      Bridge-based weight conversion (mcore -> HF format) and debug logging.
    - MCPMegatronAsyncRolloutWorker: extends Megatron DetachAsyncRolloutWorker,
      same streaming ServerAdapter.update_weights() pattern as FSDP version.
    - MegatronCriticWorker: upstream Megatron CriticWorker, no MCP customization.
    """
    strategy = config.actor_rollout_ref.actor.get("strategy", "fsdp2")

    if strategy in {"fsdp", "fsdp2"}:
        if _HAS_VERL_FSDP_WORKERS:
            logger.info("Using veRL fully_async_policy FSDP workers + MCPAsyncRolloutWorker + MCPDetachActorWorker")
            actor_cls = MCPDetachActorWorker
            rollout_cls = MCPAsyncRolloutWorker
            critic_cls = FSDPCriticWorker
        else:
            raise ImportError(
                "Could not import FSDP worker classes. "
                "Make sure veRL fully_async_policy is available."
            )

    elif strategy == "megatron":
        if _HAS_VERL_MEGATRON_WORKERS:
            logger.info("Using veRL fully_async_policy Megatron workers + MCPMegatronAsyncRolloutWorker")
            actor_cls = MCPMegatronDetachActorWorker
            rollout_cls = MCPMegatronAsyncRolloutWorker
            critic_cls = MegatronCriticWorker
        else:
            raise ImportError(
                "Could not import Megatron worker classes. "
                "Make sure veRL is installed with Megatron support "
                "(megatron-core, transformer-engine, apex)."
            )

    else:
        raise NotImplementedError(
            f"Strategy {strategy!r} not supported. "
            f"MCP fully async supports 'fsdp', 'fsdp2', and 'megatron'."
        )

    role_worker_mapping = {
        Role.Actor: ray.remote(actor_cls),
        Role.Rollout: ray.remote(rollout_cls),
        Role.Critic: ray.remote(critic_cls),
    }

    # Reference policy: frozen copy of initial weights, used for KL penalty
    if need_reference_policy(config):
        role_worker_mapping[Role.RefPolicy] = ray.remote(actor_cls)

    return role_worker_mapping, RayWorkerGroup


def validate_async_config(config: DictConfig):
    """Validate fully async config.

    Key constraints:
    - hybrid_engine must be False (separate GPU pools required)
    - async_training and rollout config sections must exist
    - GPU counts must be specified for both trainer and rollout pools
    - Megatron: TP must divide n_gpus_per_node, TP*PP must not exceed total GPUs
    """
    errors = []

    if config.actor_rollout_ref.get("hybrid_engine", True):
        errors.append("actor_rollout_ref.hybrid_engine must be False")

    if not hasattr(config, "async_training"):
        errors.append("async_training config section is required")

    if not hasattr(config, "rollout"):
        errors.append("rollout config section is required")
    else:
        if not hasattr(config.rollout, "n_gpus_per_node"):
            errors.append("rollout.n_gpus_per_node is required")

    if not hasattr(config.trainer, "n_gpus_per_node"):
        errors.append("trainer.n_gpus_per_node is required")

    strategy = config.actor_rollout_ref.actor.get("strategy", "fsdp2")
    if strategy == "megatron":
        _validate_megatron_async_config(config, errors)
    if strategy in {"fsdp", "fsdp2", "megatron"}:
        errors.extend(validate_mcp_batch_sizing(config))

    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    logger.info("Async config validated (strategy={})", strategy)
    logger.info(f"  Training: {config.trainer.n_gpus_per_node} GPUs x {config.trainer.nnodes} nodes")
    logger.info(f"  Rollout:  {config.rollout.n_gpus_per_node} GPUs x {config.rollout.nnodes} nodes")
    sizing = compute_mcp_batch_sizing(config)
    logger.info("  Batch sizing: {}", sizing.describe())


def _validate_megatron_async_config(config: DictConfig, errors: list):
    """Validate Megatron-specific config for fully async mode."""
    megatron_cfg = config.actor_rollout_ref.actor.get("megatron", {})
    tp = megatron_cfg.get("tensor_model_parallel_size", 1)
    pp = megatron_cfg.get("pipeline_model_parallel_size", 1)
    ep = megatron_cfg.get("expert_model_parallel_size", 1)
    etp = megatron_cfg.get("expert_tensor_parallel_size", tp)
    cp = megatron_cfg.get("context_parallel_size", 1)

    for name, value in (
        ("tensor_model_parallel_size", tp),
        ("pipeline_model_parallel_size", pp),
        ("expert_model_parallel_size", ep),
        ("expert_tensor_parallel_size", etp),
        ("context_parallel_size", cp),
    ):
        if not isinstance(value, int) or value < 1:
            errors.append(f"Megatron {name} must be a positive integer, got: {value!r}")
            return

    trainer_gpus_per_node = config.trainer.n_gpus_per_node
    trainer_total_gpus = trainer_gpus_per_node * config.trainer.nnodes
    # Megatron-Core has two distinct DP concepts:
    # - ordinary DP for dense/attention layers and actor PPO batch splitting:
    #   world / (TP * CP * PP)
    # - expert DP for MoE expert groups:
    #   world / (ETP * EP * PP)
    # See megatron.core.parallel_state.initialize_model_parallel().
    model_parallel_product = tp * cp * pp
    expert_parallel_product = etp * ep * pp

    if trainer_gpus_per_node % tp != 0:
        errors.append(
            f"trainer.n_gpus_per_node ({trainer_gpus_per_node}) must be divisible by "
            f"Megatron TP ({tp}) for intra-node NVLink bandwidth"
        )

    if model_parallel_product > trainer_total_gpus:
        errors.append(
            f"Megatron TP*CP*PP ({model_parallel_product}) exceeds trainer total GPUs ({trainer_total_gpus})"
        )
    elif trainer_total_gpus % model_parallel_product != 0:
        errors.append(
            f"trainer total GPUs ({trainer_total_gpus}) must be divisible by "
            f"TP*CP*PP ({model_parallel_product})"
        )
    elif expert_parallel_product > trainer_total_gpus:
        errors.append(
            f"Megatron ETP*EP*PP ({expert_parallel_product}) exceeds trainer total GPUs ({trainer_total_gpus})"
        )
    elif trainer_total_gpus % expert_parallel_product != 0:
        errors.append(
            f"trainer total GPUs ({trainer_total_gpus}) must be divisible by "
            f"ETP*EP*PP ({expert_parallel_product})"
        )
    else:
        dp = trainer_total_gpus // model_parallel_product
        expert_dp = trainer_total_gpus // expert_parallel_product
        logger.info(
            "Megatron async topology: TP={}, PP={}, CP={}, DP={}, ETP={}, EP={}, expert_DP={}, trainer_gpus={}",
            tp, pp, cp, dp, etp, ep, expert_dp, trainer_total_gpus,
        )

    # moe_grouped_gemm=false breaks Bridge weight export to vLLM.
    override_cfg = megatron_cfg.get("override_transformer_config", {})
    moe_grouped_gemm = override_cfg.get("moe_grouped_gemm", None)
    if moe_grouped_gemm is False or str(moe_grouped_gemm).lower() == "false":
        errors.append(
            "moe_grouped_gemm must be true for Megatron async mode. "
            "Bridge weight export with moe_grouped_gemm=false produces HF weight "
            "names that vLLM silently skips, causing garbage generation. "
            "See Megatron_Issues/2026-04-01_moe_grouped_gemm_weight_sync.md"
        )

    # TP=1 with MoE causes OOM in actor backward - each GPU holds full
    # expert weights and unsharded activations.
    if tp == 1 and ep > 0:
        logger.warning(
            "TP=1 with MoE (EP={}) is prone to OOM in actor backward. "
            "Each GPU holds unsharded activations and Sequence Parallel "
            "cannot be enabled (requires TP>=2). Consider TP=2.",
            ep,
        )


def _inject_total_training_steps(config: DictConfig, total_train_steps: int):
    """Inject total_training_steps into optimizer configs before worker init.

    Megatron's OptimizerParamScheduler requires lr_decay_steps > 0. When
    lr_decay_steps is not explicitly set, it falls back to total_training_steps
    from the optimizer config. The standard veRL PPO trainer sets this in
    _setup_data(), but fully async mode has no dataloader on the trainer side.
    """
    if total_train_steps is None or total_train_steps <= 0:
        total_train_steps = 100_000
        logger.warning(
            "total_train_steps is not set or invalid; using fallback={} "
            "for Megatron optimizer scheduler. Set trainer.total_training_steps "
            "or async_training.total_train_steps to override.",
            total_train_steps,
        )

    try:
        OmegaConf.set_struct(config, True)
        with open_dict(config):
            if OmegaConf.select(config, "actor_rollout_ref.actor.optim"):
                config.actor_rollout_ref.actor.optim.total_training_steps = total_train_steps
                logger.info(
                    "Injected actor optim total_training_steps={}",
                    total_train_steps,
                )
            if OmegaConf.select(config, "critic.optim"):
                config.critic.optim.total_training_steps = total_train_steps
                logger.info(
                    "Injected critic optim total_training_steps={}",
                    total_train_steps,
                )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Could not inject total_training_steps into config: {}. "
            "If using Megatron, the optimizer scheduler may fail.", e,
        )


@ray.remote(num_cpus=1)
class MCPAsyncTaskRunner:
    """Lightweight Ray actor that orchestrates all training components.

    Responsibilities:
    1. Load model/tokenizer
    2. Create Rollouter and Trainer (each on its own GPU pool)
    3. Create MessageQueue (Rollouter -> Trainer data channel)
    4. Create ParameterSynchronizer (Trainer -> Rollouter weight sync)
    5. Run initial weight sync (ensure inference engine has training weights)
    6. Launch Rollouter.fit() and Trainer.fit() concurrently, wait for completion
    """

    def __init__(self):
        self.running = False
        self.components = {}
        self.shutdown_event = threading.Event()

    def run(self, config):
        """Entry point: initialize all components, then start training loop."""
        logger.info("[MCP ASYNC MAIN] Starting fully async MCP PPO training...")
        self._initialize_components(config)
        self._run_training_loop()

    def _initialize_components(self, config) -> None:
        """Initialize all training components in dependency order."""
        logger.info(f"[MCP ASYNC MAIN] hostname={socket.gethostname()}, PID={os.getpid()}")
        pprint(OmegaConf.to_container(config, resolve=True))
        OmegaConf.resolve(config)

        # -- 1. Load model and tokenizer -----------------------------------
        # copy_to_local: pull from remote storage (S3/HDFS) to local/shared memory
        logger.info("[MCP ASYNC MAIN] Loading model and tokenizer...")
        local_path = copy_to_local(
            config.actor_rollout_ref.model.path,
            use_shm=config.actor_rollout_ref.model.get("use_shm", False),
        )
        trust_remote_code = config.data.get("trust_remote_code", False)
        tokenizer = hf_tokenizer(local_path, trust_remote_code=trust_remote_code)
        processor = hf_processor(local_path, trust_remote_code=trust_remote_code, use_fast=True)

        self.components["tokenizer"] = tokenizer
        self.components["processor"] = processor
        self.components["config"] = config

        # -- 2. Create worker mapping --------------------------------------
        # Select worker classes based on strategy (fsdp/fsdp2/megatron), wrap with ray.remote()
        logger.info("[MCP ASYNC MAIN] Creating worker mapping...")
        role_worker_mapping, ray_worker_group_cls = create_role_worker_mapping(config)
        self.components["role_worker_mapping"] = role_worker_mapping
        self.components["ray_worker_group_cls"] = ray_worker_group_cls

        # -- 3. Create Rollouter and Trainer -------------------------------
        # Created sequentially to avoid GPU resource contention
        logger.info("[MCP ASYNC MAIN] Creating rollouter...")
        self._create_rollouter(config)

        # -- 3.5. Inject total_training_steps into optimizer configs -------
        # Megatron's OptimizerParamScheduler requires lr_decay_steps > 0.
        # When lr_decay_steps is null, it falls back to total_training_steps.
        # The standard veRL PPO trainer sets this in _setup_data() before
        # worker init, but fully async mode has no dataloader on the trainer
        # side. We fetch the estimate from the rollouter and inject it before
        # the trainer builds the Megatron optimizer.
        total_train_steps = ray.get(self.components["rollouter"].get_total_train_steps.remote())
        logger.info(f"[MCP ASYNC MAIN] total_train_steps={total_train_steps}")
        _inject_total_training_steps(config, total_train_steps)

        logger.info("[MCP ASYNC MAIN] Creating trainer...")
        self._create_trainer(config)

        # -- 4. Sync total_train_steps (for tqdm progress bar) -------------
        ray.get(self.components["trainer"].set_total_train_steps.remote(total_train_steps))

        # -- 5. Create MessageQueue ----------------------------------------
        # Shared data buffer: Rollouter pushes rollout DataProto, Trainer pulls.
        # max_queue_size caps the buffer to prevent memory issues if Rollouter
        # produces faster than Trainer consumes.
        max_queue_size = ray.get(self.components["rollouter"].get_max_queue_size.remote())
        logger.info(f"[MCP ASYNC MAIN] Creating MessageQueue, max_queue_size={max_queue_size}")
        message_queue = MessageQueue.remote(config, max_queue_size)
        message_queue_client = MessageQueueClient(message_queue)
        # message_queue: Ray actor (the actual queue process)
        # message_queue_client: client wrapper with push()/pop()/clear_queue()
        self.components["message_queue"] = message_queue
        self.components["message_queue_client"] = message_queue_client

        # Inject the same client into both Rollouter (producer) and Trainer (consumer)
        ray.get(self.components["rollouter"].set_message_queue_client.remote(message_queue_client))
        ray.get(self.components["trainer"].set_message_queue_client.remote(message_queue_client))

        # -- 6. Create MCPParameterSynchronizer ----------------------------
        # Handles post-training weight sync:
        #   Actor (FSDP/Megatron) -> NCCL broadcast -> MCP*RolloutWorker -> ServerAdapter -> inference engine
        #
        # Why MCPParameterSynchronizer instead of upstream ParameterSynchronizer:
        # Upstream has the actual NCCL sync code commented out (sync_weights is a no-op).
        # This is because upstream's sync_rollout_weights() calls get_inference_model()
        # which fails on ServerAdapter (no local engine). MCP*RolloutWorker bypasses
        # this by using ServerAdapter.update_weights() (CUDA IPC), so we can safely
        # re-enable the NCCL sync calls. This is strategy-agnostic.
        logger.info("[MCP ASYNC MAIN] Setting up MCPParameterSynchronizer...")
        param_synchronizer = MCPParameterSynchronizer.remote(
            config=config,
            trainer=self.components["trainer"],
            rollouter=self.components["rollouter"],
            mq=message_queue_client,
        )
        ray.get(self.components["trainer"].set_parameter_synchronizer.remote(param_synchronizer))
        self.components["param_synchronizer"] = param_synchronizer

        # -- 7. Load checkpoint + initial weight sync ----------------------
        # Before training starts, ensure inference engine weights match training side.
        # - load_checkpoint: resume from previous checkpoint if available
        # - sync_weights: NCCL broadcast trainer weights to all rollout workers
        # - wait_last_valid: if val_before_train=True, wait for validation to finish
        val_before_train = config.trainer.get("val_before_train", True)
        param_version = ray.get(self.components["trainer"].load_checkpoint.remote())
        ray.get(self.components["rollouter"].load_checkpoint.remote())
        use_trainer_do_validate = config.async_training.get("use_trainer_do_validate", False)
        ray.get(
            param_synchronizer.sync_weights.remote(
                version=param_version,
                validate=val_before_train,
                use_trainer_do_validate=use_trainer_do_validate,
            )
        )
        ray.get(param_synchronizer.wait_last_valid.remote())

        logger.info("[MCP ASYNC MAIN] All components initialized")

    def _create_rollouter(self, config) -> None:
        """Create Rollouter (Ray actor on rollout GPU pool).

        MCPFullyAsyncRollouter runs the inference engine and MCP agent loop:
        dataset prompts -> MCP agent multi-turn dialogue -> trajectory collection -> queue push
        """
        rollouter = MCPFullyAsyncRollouter.remote(
            config=config,
            tokenizer=self.components["tokenizer"],
            role_worker_mapping={Role.Rollout: self.components["role_worker_mapping"][Role.Rollout]},
            resource_pool_manager=create_resource_pool_manager(config, roles=[Role.Rollout]),
            ray_worker_group_cls=self.components["ray_worker_group_cls"],
            processor=self.components["processor"],
            device_name=config.trainer.device,
        )

        ray.get(rollouter.init_workers.remote())
        ray.get(rollouter.set_max_required_tasks.remote())

        self.components["rollouter"] = rollouter
        logger.info("[MCP ASYNC MAIN] Rollouter created and initialized")

    def _create_trainer(self, config) -> None:
        """Create Trainer (Ray actor on trainer GPU pool).

        MCPFullyAsyncTrainer manages Actor (FSDP), Critic, RefPolicy training:
        pull from MessageQueue -> PPO update -> trigger weight sync
        """
        # All roles except Rollout belong to the Trainer
        trainer_role_mapping = {
            role: worker_cls
            for role, worker_cls in self.components["role_worker_mapping"].items()
            if role != Role.Rollout
        }

        trainer = MCPFullyAsyncTrainer.remote(
            config=config,
            tokenizer=self.components["tokenizer"],
            role_worker_mapping=trainer_role_mapping,
            resource_pool_manager=create_resource_pool_manager(
                config, roles=list(trainer_role_mapping.keys()),
            ),
            ray_worker_group_cls=self.components["ray_worker_group_cls"],
            processor=self.components["processor"],
            device_name=config.trainer.device,
        )

        ray.get(trainer.init_workers.remote())
        self.components["trainer"] = trainer
        logger.info("[MCP ASYNC MAIN] Trainer created and initialized")

    def _run_training_loop(self):
        """Run Rollouter and Trainer concurrently, wait for completion.

        Normal flow:
        1. Both rollouter.fit() and trainer.fit() launch concurrently
        2. ray.wait() blocks until either one completes
        3. Rollouter exhausts data -> pushes None to queue -> rollouter.fit() returns first
           -> Trainer pulls None -> TrainingStopException -> trainer.fit() returns
        4. If Trainer finishes first (atypical), explicitly stop Rollouter
        5. On error: cancel the other component and re-raise
        """
        self.running = True

        logger.info("[MCP ASYNC MAIN] Starting Rollouter and Trainer...")
        rollouter_future = self.components["rollouter"].fit.remote()
        trainer_future = self.components["trainer"].fit.remote()

        futures = [rollouter_future, trainer_future]

        try:
            while futures:
                done_futures, remaining_futures = ray.wait(
                    futures, num_returns=1, timeout=None,
                )

                for future in done_futures:
                    try:
                        ray.get(future)
                    except Exception as e:
                        logger.error(f"[MCP ASYNC MAIN] Component failed: {e}")
                        for remaining in remaining_futures:
                            ray.cancel(remaining)
                        raise

                    # If Trainer finishes before Rollouter (atypical), tell Rollouter to stop
                    if future is trainer_future and remaining_futures:
                        logger.info("[MCP ASYNC MAIN] Trainer finished, stopping rollouter")
                        ray.get(self.components["rollouter"].stop.remote())

                futures = remaining_futures

        except Exception as e:
            logger.error(f"[MCP ASYNC MAIN] Training failed: {e}")
            for future in futures:
                ray.cancel(future)
            raise
        finally:
            rollouter = self.components.get("rollouter")
            if rollouter is not None:
                try:
                    ray.get(rollouter.shutdown.remote())
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning("[MCP ASYNC MAIN] Rollouter shutdown failed: {}", exc)
            asyncio.run(self.components["message_queue_client"].clear_queue())
            logger.info("[MCP ASYNC MAIN] Training completed")


def run_mcp_async_ppo(config: DictConfig) -> None:
    """Initialize Ray cluster and start training.

    MCPAsyncTaskRunner itself is a Ray actor so the entire training flow
    runs under Ray's distributed scheduler.
    """
    clean_tiktoken = config.get("mcp_agent", {}).get("clean_tiktoken_cache", False)
    init_ray(config, clean_tiktoken_cache=clean_tiktoken)

    runner = MCPAsyncTaskRunner.remote()

    task = runner.run.remote(config)
    try:
        ray.get(task)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt, shutting down...")
        ray.cancel(task)
        raise

    # Optional: export Ray timeline for performance analysis
    timeline_json_file = OmegaConf.select(config, "ray_init.timeline_json_file", default=None)
    if timeline_json_file:
        ray.timeline(filename=timeline_json_file)


@hydra.main(config_path=CONFIG_DIR, config_name="mcp_fully_async", version_base=None)
def main(config: DictConfig):
    """CLI entry point: Hydra parses YAML config -> validate -> start training.

    Usage:
        python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \\
            --config-path=config --config-name=mcp_fully_async \\
            trainer.n_gpus_per_node=4 rollout.n_gpus_per_node=2
    """
    logger.info("=" * 70)
    logger.info("MCP PPO Training - Fully Async Mode")
    logger.info("=" * 70)

    validate_async_config(config)
    run_mcp_async_ppo(config)


if __name__ == "__main__":
    main()
