# pylint: disable=super-init-not-called,invalid-overridden-method,arguments-renamed,too-many-lines

"""
MCP Fully Async Rollouter for VERL Integration.

Producer in fully async training: generates MCP agent trajectories in batches
via MCPLoopManager and pushes them into a MessageQueue for the Trainer consumer.
Same code path as hybrid mode (one generate_sequences() call per batch), but
decoupled from training via queue backpressure.

Weight sync: orchestrator calls pause() -> NCCL broadcast -> resume().
pause() waits for in-flight generation via _generation_idle fence.
"""

# pylint: disable=import-outside-toplevel

import asyncio
import functools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pprint import pformat
from typing import Optional

import numpy as np
import ray
import torch
from ray import ObjectRef
from torch.utils.data import DataLoader

from verl import DataProto
from verl.experimental.fully_async_policy.detach_utils import ValidateMetrics
from verl.experimental.fully_async_policy.message_queue import MessageQueueClient
from verl.experimental.separation.ray_trainer import SeparateRayPPOTrainer
from verl.single_controller.ray import RayClassWithInitArgs, RayWorkerGroup
from verl.trainer.main_ppo import create_rl_dataset, create_rl_sampler
from verl.trainer.ppo.ray_trainer import ResourcePoolManager
from verl.trainer.ppo.utils import Role, WorkerType
from verl.utils.checkpoint.checkpoint_manager import find_latest_ckpt_path
from verl.utils.dataset.rl_dataset import collate_fn as verl_collate_fn
from verl.utils.debug import marked_timer
from verl.utils.fs import local_mkdir_safe
from verl.utils.tracking import ValidationGenerationsLogger

from ..mcp_dataset import MCPDataset, create_mcp_dataset, mcp_collate_fn
from ..mcp_loop_manager import MCPLoopManager
from ..mcp_reward_manager import MCPRewardManager
from ..utils import _LazyLogger, compute_validation_reward_metrics

from .mcp_async_data import MCP_BATCH_END_SENTINEL, MCPRolloutSample
from ..mcp_batch_sizing import compute_mcp_batch_sizing

logger = _LazyLogger()


# max_concurrency=100: allow many concurrent Ray async method calls
# (pause/resume/stop/update_param_version) without blocking each other.
@ray.remote(num_cpus=10, max_concurrency=100)
class MCPFullyAsyncRollouter(SeparateRayPPOTrainer):  # pylint: disable=too-many-instance-attributes
    # Inherits SeparateRayPPOTrainer for resource pool and worker group init,
    # but does not use its training logic - Rollouter only does inference.
    """Batch-based MCP sample generator for fully async training.

    Generates training samples in batches via MCPLoopManager (same code path
    as hybrid mode) and pushes them into a MessageQueue for the trainer.

    Unlike the per-instance streaming approach, each batch goes through ONE
    ``generate_sequences()`` call with ONE dispatcher, giving the same
    concurrency behavior as hybrid mode (``max_init_agents`` concurrent
    trajectory runs, no Docker env pool contention).

    The "async" benefit comes from decoupling rollout and training via the
    queue: the trainer can process previous results while the rollouter
    generates the next batch.
    """

    def __init__(  # pylint: disable=too-many-statements
        self,
        config,
        tokenizer,
        role_worker_mapping: dict[Role, WorkerType],
        resource_pool_manager: ResourcePoolManager,
        ray_worker_group_cls: RayWorkerGroup = RayWorkerGroup,
        processor=None,
        device_name=None,
    ):
        self.tokenizer = tokenizer
        self.processor = processor
        self.config = config
        self.hybrid_engine = config.actor_rollout_ref.hybrid_engine
        assert not self.hybrid_engine, "Fully async mode requires hybrid_engine=False"

        self.role_worker_mapping = role_worker_mapping
        self.resource_pool_manager = resource_pool_manager
        self.use_reference_policy = False
        self.use_rm = False
        self.use_critic = False
        self.ray_worker_group_cls = ray_worker_group_cls
        self.device_name = device_name if device_name else self.config.trainer.device

        self.validation_generations_logger = ValidationGenerationsLogger(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
        )

        self.ref_in_actor = False
        self.kl_ctrl_in_reward = False
        self.use_prefix_grouper = self.config.actor_rollout_ref.actor.get("use_prefix_grouper", False)
        self.use_legacy_worker_impl = config.trainer.get("use_legacy_worker_impl", "auto")

        # Auto-select dataset type by file extension (.json -> MCP, other -> standard RL)
        logger.info("Creating MCP datasets...")
        train_files = config.data.get("train_files", "")
        val_files = config.data.get("val_files", "")

        if train_files and train_files.endswith(".json"):
            train_dataset = create_mcp_dataset(
                train_files, config.data, tokenizer, processor, is_train=True,
            )
            val_dataset = (
                create_mcp_dataset(val_files, config.data, tokenizer, processor, is_train=False)
                if val_files else None
            )
            collate_fn = mcp_collate_fn
        else:
            train_dataset = create_rl_dataset(config.data.train_files, config.data, tokenizer, processor)
            val_dataset = create_rl_dataset(config.data.val_files, config.data, tokenizer, processor)
            collate_fn = verl_collate_fn

        train_sampler = create_rl_sampler(config.data, train_dataset)

        self._validate_config()

        if not self.config.async_training.get("use_trainer_do_validate", False):
            logger.info("Rollouter will handle validation")
        logger.info("train_dataset: {}, val_dataset: {}",
                     len(train_dataset), len(val_dataset) if val_dataset else 0)

        self._create_dataloader(train_dataset, val_dataset, collate_fn, train_sampler)

        self.total_rollout_steps = len(self.train_dataloader) * self.config.trainer.total_epochs
        if self.config.rollout.get("total_rollout_steps") is not None:
            self.total_rollout_steps = min(
                self.config.rollout.total_rollout_steps, self.total_rollout_steps,
            )
        logger.info("Total rollout steps: {}", self.total_rollout_steps)
        self.total_train_steps = None  # computed in set_max_required_tasks()

        self.message_queue_client = None
        self.rollout_wg = None
        self.actor_rollout_wg = None
        self.mcp_loop_manager = None
        self.rollout_replicas = None

        # Backpressure: staleness_threshold controls how far ahead rollouter can run
        self.staleness_threshold: float = config.async_training.get("staleness_threshold", 1)
        # Single source of truth for batch sizing - see MCPBatchSizing docstring.
        # ``self.<field>`` mirrors stay for backward compat with older launcher
        # code / log greps; new code should prefer ``self.batch_sizing.<field>``.
        self.batch_sizing = compute_mcp_batch_sizing(config)
        self.require_batches = self.batch_sizing.require_batches
        self.required_tasks = self.batch_sizing.required_tasks
        self.required_trajectories = self.batch_sizing.required_trajectories
        self.global_trajectory_minibatch = self.batch_sizing.global_trajectory_minibatch
        self.local_actor_minibatch = self.batch_sizing.local_actor_minibatch
        self.alignment_unit = self.batch_sizing.alignment_unit
        self.actor_dp_size = self.batch_sizing.dp
        self.max_required_queue_items = None  # computed in set_max_required_tasks()
        self.max_queue_size = None
        logger.info("Async queue sizing: {}", self.batch_sizing.describe())

        self._trajectories_per_queue_item = self.batch_sizing.rollout_n  # updated in _create_dataloader

        # Counters with unit-explicit names. One MCPRolloutSample == one
        # queue item; a queue item carries up to ``rollout.n`` trajectories.
        self.current_param_version = 0
        self.total_generated_queue_items = 0      # pushed to MQ since process start
        self.stale_queue_items = 0                # in MQ produced under older param_version
        self.dropped_stale_queue_items = 0        # rejected by MQ (backpressure)
        self.failed_rollout_batches = 0           # continuous generation exceptions
        self.global_steps = 1

        self.idle_start_time = None
        self.version_start_time = None

        # Concurrency control
        self.paused = False
        self.running = True
        self.monitor_loop_trigger = True
        self.dataloader_lock = asyncio.Lock()
        self.lock = asyncio.Lock()
        self.condition = asyncio.Condition(self.lock)

        # Fence: pause() awaits this to ensure in-flight generation completes before NCCL sync
        self._generation_idle = asyncio.Event()
        self._generation_idle.set()

        # Blocking generate_sequences() runs in executor to keep Ray event loop responsive
        mcp_cfg = config.get("mcp_agent", {})
        self.max_init_agents = mcp_cfg.get("max_init_agents", 16)
        self.rollout_executor = ThreadPoolExecutor(max_workers=1)
        self.validate_executor = ThreadPoolExecutor(max_workers=1)
        self._env_pool_init_lock = threading.Lock()
        self._shutdown_done = False
        self.parallel_validate_and_rollout = config.async_training.get(
            "parallel_validate_and_rollout", False,
        )
        self.validate_task = None

        # The rollouter runs ONE continuous worker pool (no per-batch
        # barrier) - instances stream out as they finish. _main_loop is the Ray
        # actor loop the MQ pushes run on (captured in fit()).
        self._main_loop = None
        self._continuous_pipeline = None

    async def set_message_queue_client(self, message_queue_client: MessageQueueClient):
        """Set message queue client."""
        async with self.lock:
            self.message_queue_client = message_queue_client

    async def set_max_required_tasks(self):
        """Compute derived backpressure limits (in queue-item units)."""
        async with self.lock:
            trig = self.config.async_training.trigger_parameter_sync_step
            queue_items_per_train_step = max(
                1,
                -(-self.required_trajectories // max(1, self._trajectories_per_queue_item)),
            )
            self.max_required_queue_items = int(
                queue_items_per_train_step
                * (self.staleness_threshold + 1)
                * trig
            )
            self.max_queue_size = self.max_required_queue_items

            configured_steps = self.config.async_training.get("total_train_steps", None)
            if configured_steps:
                self.total_train_steps = configured_steps
            else:
                self.total_train_steps = int(
                    self.total_rollout_steps
                    / (queue_items_per_train_step * trig)
                )

            logger.info(
                "required_tasks: {} required_trajectories: {} "
                "trajectories_per_queue_item: {} "
                "queue_items_per_train_step: {} max_queue_size: {} "
                "total_train_steps: {} (configured={})",
                self.required_tasks, self.required_trajectories,
                self._trajectories_per_queue_item,
                queue_items_per_train_step, self.max_queue_size,
                self.total_train_steps, configured_steps,
            )

    def get_rollout_wg(self):
        """Get rollout worker group."""
        return self.rollout_wg

    def get_max_queue_size(self):
        """Get maximum queue size for backpressure control."""
        return self.max_queue_size

    def get_total_train_steps(self):
        """Get total training steps derived from rollout steps."""
        return self.total_train_steps

    def _validate_config(self):
        """Validate async training configuration."""
        if not hasattr(self.config, "async_training"):
            raise ValueError("[MCPAsyncRollouter] Missing async_training configuration")

    def _create_dataloader(self, train_dataset, val_dataset, collate_fn, train_sampler):
        """Create train and validation dataloaders."""
        mcp_cfg = self.config.get("mcp_agent", {})
        max_parallel = mcp_cfg.get("max_init_agents", 16)
        rollout_n = self.config.actor_rollout_ref.rollout.get("n", 1)
        # Default: ceil(max_parallel / n) to fill dispatcher concurrency slots
        default_batch_size = max(1, -(-max_parallel // max(1, rollout_n)))
        rollout_batch_size = self.config.data.get("gen_batch_size", default_batch_size) or default_batch_size
        self.rollout_batch_size = rollout_batch_size
        self._trajectories_per_queue_item = rollout_batch_size * rollout_n

        val_batch_size = self.config.data.get("val_batch_size", rollout_batch_size) or rollout_batch_size
        num_workers = self.config.data.get(
            "dataloader_num_workers",
            self.config.data.get("num_workers", 8),
        )
        if isinstance(train_dataset, MCPDataset) and int(num_workers or 0) != 0:
            logger.warning(
                "MCP JSON dataset is already loaded in memory; setting rollout "
                "DataLoader num_workers=0 to avoid slow worker fork in the "
                "fully async rollouter. The launch config is unchanged."
            )
            num_workers = 0

        logger.info(
            "Rollout batch_size={} (instances), n={} (trajectories/instance), "
            "total_per_batch={}, max_init_agents={}",
            rollout_batch_size, rollout_n,
            rollout_batch_size * rollout_n, max_parallel,
        )

        self.train_dataloader = DataLoader(
            dataset=train_dataset,
            batch_size=rollout_batch_size,
            sampler=train_sampler,
            collate_fn=collate_fn,
            drop_last=True,
            num_workers=num_workers,
        )

        if val_dataset is not None:
            self.val_dataloader = DataLoader(
                dataset=val_dataset,
                batch_size=val_batch_size,
                shuffle=False,
                collate_fn=collate_fn,
                drop_last=False,
                num_workers=num_workers,
            )
        else:
            self.val_dataloader = None

    # ==================== Worker initialization ====================
    # Rollouter only creates Rollout workers (no Actor/Critic/RefPolicy);
    # training is handled by the Trainer.

    def _create_actor_rollout_classes(self):
        """Create only rollout worker class (rollouter does not train)."""
        for role in [Role.Rollout]:
            resource_pool = self.resource_pool_manager.get_resource_pool(role)
            role_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[role],
                config=self.config.actor_rollout_ref,
                role=str(role),
            )
            self.resource_pool_to_cls[resource_pool][str(role)] = role_cls

    def _init_models(self):
        """Initialize rollout worker group (model weights + ServerAdapter)."""
        # rollout_wg contains DetachAsyncRolloutWorker with ServerAdapter (vLLM server client)
        self.rollout_wg = self.all_wg[str(Role.Rollout)]
        self.rollout_wg.init_model()
        # actor_rollout_wg aliases rollout_wg for upstream API compat (checkpoint, param_sync, etc.)
        self.actor_rollout_wg = self.rollout_wg

    async def _init_mcp_loop_manager(self):
        """Launch inference servers and initialize MCPLoopManager.

        Supports vLLM and SGLang backends. Inference servers run inside
        existing rollout worker processes; initial weights are dummy and
        synced via NCCL during orchestrator startup.
        """
        rollout_config = self.config.actor_rollout_ref.rollout
        model_config = self.config.actor_rollout_ref.model

        # Select inference backend: vLLM or SGLang
        rollout_name = rollout_config.get("name", "vllm")
        if rollout_name == "sglang":
            # pylint: disable-next=no-name-in-module
            from verl.experimental.fully_async_policy.sglang_rollout.sglang_async_server import (
                FullyAsyncSGLangReplica as ReplicaClass,
            )
        elif rollout_name == "vllm":
            # pylint: disable-next=no-name-in-module
            from verl.experimental.fully_async_policy.vllm_rollout.vllm_async_server import (
                FullyAsyncvLLMReplica as ReplicaClass,
            )
        else:
            raise ValueError(
                f"Unsupported rollout backend: {rollout_name!r}. "
                f"Supported values are 'vllm' and 'sglang'."
            )

        # GPUs per replica and total replicas.
        # e.g. tp=2, dp=1, pp=1 -> 2 GPUs per replica; 8 GPUs total -> 4 replicas
        tp_size = rollout_config.get("tensor_model_parallel_size", 1)
        dp_size = rollout_config.get("data_parallel_size", 1)
        pp_size = rollout_config.get("pipeline_model_parallel_size", 1)
        rollout_world_size = tp_size * dp_size * pp_size

        total_rollout_gpus = self.config.rollout.n_gpus_per_node * self.config.rollout.nnodes
        num_replicas = total_rollout_gpus // rollout_world_size

        logger.info(
            "Creating {} {} replicas (tp={}, total_gpus={})",
            num_replicas, rollout_name, tp_size, total_rollout_gpus,
        )

        rollout_replicas = [
            ReplicaClass(
                replica_rank=r,
                config=rollout_config,
                model_config=model_config,
                gpus_per_node=self.config.rollout.n_gpus_per_node,
            )
            for r in range(num_replicas)
        ]

        # init_hybrid() starts inference servers (vLLM AsyncLLM or SGLang) inside
        # existing rollout worker processes. Initial weights are loaded as dummy;
        # real weights arrive via NCCL broadcast during initial param sync.
        await asyncio.gather(*[
            replica.init_hybrid(self.rollout_wg)
            for replica in rollout_replicas
        ])

        # Collect server addresses from each replica for MCPLoopManager.
        # Text mode uses these as HTTP endpoints; TITO mode uses rollout_replicas directly.
        server_addresses = []
        for replica in rollout_replicas:
            addr = replica._server_address  # pylint: disable=protected-access
            server_addresses.append(addr)
            logger.info("{} replica: {}", rollout_name, addr)

        self.rollout_replicas = rollout_replicas

        # MCPLoopManager: manages the MCP agent tool-calling loop.
        # server_addresses tell it which inference servers to call.
        self.mcp_loop_manager = MCPLoopManager(
            config=self.config,
            worker_group=self.rollout_wg,
            server_addresses=server_addresses,
            rollout_replicas=rollout_replicas,
        )
        logger.info("MCPLoopManager initialized with {} backend", rollout_name)

    def _uses_docker_env_pool(self) -> bool:
        """Return whether this rollouter should initialize MCP docker_pool once."""
        if self.mcp_loop_manager is None:
            return False
        mcp_config = getattr(self.mcp_loop_manager, "mcp_config", None)
        if mcp_config is None or getattr(mcp_config, "mcp_transport", "stdio") != "docker_pool":
            return False

        env_pool_cfg = getattr(mcp_config, "env_pool", None)
        if env_pool_cfg is None:
            return False
        enabled = getattr(env_pool_cfg, "enabled", None)
        if enabled is None and isinstance(env_pool_cfg, dict):
            enabled = env_pool_cfg.get("enabled", False)
        return bool(enabled)

    def _ensure_env_pool_for_batch(self, batch: DataProto) -> None:
        """Reconcile docker_pool capacity before rollout/validation calls."""
        if not self._uses_docker_env_pool():
            return

        with self._env_pool_init_lock:
            max_parallel = self.mcp_loop_manager.mcp_config.dispatcher.max_init_agents
            parsed_batch = self.mcp_loop_manager._parse_input_batch(batch)  # pylint: disable=protected-access
            self.mcp_loop_manager.ensure_env_pool(parsed_batch, max_parallel)

    async def init_workers(self):
        """Initialize distributed workers."""
        self._init_resource_pools()
        self._create_worker_classes()
        self._init_worker_groups()
        self._init_models()

        # Free FSDP model shards on rollout workers (~5GB/GPU).
        # In async mode inference goes through the vLLM server, not the local FSDP
        # model, so these shards are wasted. Freeing them makes room for the
        # inference server and CUDA IPC weight sync buffers.
        self.rollout_wg.free_fsdp_model()

        await self._init_mcp_loop_manager()

    # ==================== Batch processing ====================

    def _batch_dict_to_dataproto(self, batch_dict: dict) -> DataProto:
        """Convert a collated batch dict to DataProto for generate_sequences."""
        non_tensor_batch = batch_dict.get("non_tensor_batch", batch_dict)

        # MCP dataset fields (system_prompt, tools, instance) are non-tensor;
        # generate_sequences requires numpy arrays
        np_batch = {}
        for key, val in non_tensor_batch.items():
            if isinstance(val, np.ndarray):
                np_batch[key] = val
            elif isinstance(val, list):
                np_batch[key] = np.array(val, dtype=object)
            else:
                np_batch[key] = val

        return DataProto(
            batch=None,
            non_tensor_batch=np_batch,
            meta_info={
                "eos_token_id": self.tokenizer.eos_token_id,
                "pad_token_id": self.tokenizer.pad_token_id,
            },
        )

    async def _push_stream_sample(self, data_proto: DataProto, instance_id, epoch: int) -> bool:
        """Push one instance's DataProto to the MQ (runs on the Ray actor loop)."""
        rollout_sample = MCPRolloutSample(
            data=data_proto,
            param_version=self.current_param_version,
            instance_id=f"stream_{epoch}_{self.global_steps}_{instance_id}",
            sample_id=f"sample_{epoch}_{self.global_steps}_{instance_id}",
            epoch=epoch,
            processing_time=0.0,
        )
        success = await self.message_queue_client.put_sample(
            sample=ray.cloudpickle.dumps(rollout_sample),
            param_version=rollout_sample.param_version,
        )
        if success:
            self.total_generated_queue_items += 1
            self.stale_queue_items += 1
        else:
            self.dropped_stale_queue_items += 1
        return success

    def _parse_batch_to_instances(self, batch_dict: dict) -> list[dict]:
        """Parse a collated batch dict into individual instance dicts."""
        if "non_tensor_batch" in batch_dict:
            non_tensor_batch = batch_dict["non_tensor_batch"]
        else:
            non_tensor_batch = batch_dict

        first_key = next(iter(non_tensor_batch.keys()))
        first_val = non_tensor_batch[first_key]
        batch_size = len(first_val) if isinstance(first_val, (list, np.ndarray)) else 1

        instances = []
        for i in range(batch_size):
            instance = {}
            for key, val in non_tensor_batch.items():
                if isinstance(val, (list, np.ndarray)):
                    instance[key] = val[i]
                else:
                    instance[key] = val
            instances.append(instance)

        return instances

    # ==================== continuous worker pool ====================

    async def _continuous_generation_main(self):  # pylint: disable=too-many-statements
        """Continuous worker pool - no per-batch barrier.

        Instances stream through ONE long-lived ``RolloutPipeline``; each is
        pushed to the MQ the moment its trajectories finish. Weight sync stops
        feeding and drains in-flight via ``pipe.quiesce()`` (the NCCL broadcast
        needs idle workers), syncs, then resumes. Everything runs on the Ray
        actor loop, so MQ pushes are direct (no cross-loop). NEEDS POD VALIDATION.
        """
        from mcpuniverse.rl.core.pipeline import RolloutPipeline  # local import
        from mcpuniverse.rl.core.rollout import build_rollout_dispatcher_config

        self._main_loop = asyncio.get_running_loop()
        lm = self.mcp_loop_manager
        num_traj = max(1, int(lm.num_trajectories or 1))

        # Init the env pool on THIS loop (continuous runs build+dispatch+pool here).
        # NOTE: _env_pool_active is a READ-ONLY property (true once the pool is
        # created), so we must NOT assign to it - _init_env_pool flips it.
        if self._uses_docker_env_pool() and not lm._env_pool_active:  # pylint: disable=protected-access
            max_parallel = lm.mcp_config.dispatcher.max_init_agents
            await lm._init_env_pool(max_parallel)  # pylint: disable=protected-access

        dispatcher_cfg = build_rollout_dispatcher_config(
            lm.mcp_config.dispatcher,
            num_instances=self.rollout_batch_size,
            num_trajectories=num_traj,
            include_init_timeout=True,
        )

        inst_trajs: dict = {}     # iid -> {tid: traj}
        epoch_box = [0]
        completed_box = [0]

        async def on_done(iid):
            trajs = inst_trajs.pop(iid, None)
            if not trajs:
                return
            # >=2 guard: GRPO needs >=2 trajectories WITH results in a group
            # (group-relative advantage = mean+std). Drop degenerate groups
            # instead of pushing a 0/1-sample group that would corrupt training.
            valid = sum(1 for t in trajs.values() if getattr(t, "result", None) is not None)
            if valid < 2:
                logger.warning(
                    "Dropping instance {}: only {}/{} trajectories have results (<2)",
                    iid, valid, len(trajs),
                )
                return
            pushed_any = False
            for data_proto in lm.build_instance_dataproto(iid, trajs, num_traj):
                if await self._push_stream_sample(data_proto, iid, epoch_box[0]):
                    pushed_any = True
            if pushed_any:
                completed_box[0] += 1
                # Periodic batch-end sentinel for trainer alignment.
                if completed_box[0] % max(1, self.rollout_batch_size) == 0:
                    await self.message_queue_client.put_sample(
                        sample=MCP_BATCH_END_SENTINEL,
                        param_version=self.current_param_version,
                    )

        pipe = RolloutPipeline(dispatcher_cfg, on_instance_complete=on_done)
        self._continuous_pipeline = pipe
        pipe.start()
        self._generation_idle.clear()  # generating
        max_env_inflight = max(1, self.max_init_agents)
        max_inflight = max_env_inflight * 2

        logger.info(
            "Continuous generation started: batch_size={}, num_traj={}, "
            "max_inflight={}, max_env_inflight={}",
            self.rollout_batch_size, num_traj, max_inflight, max_env_inflight,
        )
        try:  # pylint: disable=too-many-nested-blocks
            while self.running:
                for batch_dict in self.train_dataloader:
                    if not self.running:
                        break
                    # Weight-sync handshake: drain in-flight if paused.
                    await self._continuous_pause_check(pipe)
                    if not self.running:
                        break
                    # Queue backpressure (too far ahead of trainer).
                    while await self._should_pause_generation():
                        if not self.running:
                            break
                        # Service a weight-sync pause requested *while* we are
                        # backpressured. Without this the two pause mechanisms
                        # deadlock: the trainer's pause() blocks on
                        # _generation_idle (only set by the pause check below),
                        # but the pause check (top of the outer loop) is never
                        # reached because _should_pause_generation() stays True --
                        # the weight sync never runs, so update_param_version never
                        # resets stale_queue_items, so backpressure never clears.
                        # Draining here lets the sync proceed; after resume the
                        # param version bumps, stale_queue_items resets, and this
                        # loop re-evaluates on-policy. (No-op when not paused.)
                        await self._continuous_pause_check(pipe)
                        if not self.running:
                            break
                        if self.idle_start_time is None:
                            self.idle_start_time = time.time()
                        await asyncio.sleep(1.0)
                    if not self.running:
                        break
                    # Build + submit this batch's instances into the pipeline.
                    batch = self._batch_dict_to_dataproto(batch_dict)
                    parsed = lm._parse_input_batch(batch)  # pylint: disable=protected-access
                    trajectories, _ = lm.build_trajectories_for_instances(parsed)
                    for iid, inner in trajectories.items():
                        inst_trajs[iid] = inner
                        size = len(inner)
                        # Submit whole instance groups when capacity allows.
                        # This keeps GRPO groups compact while the pipeline's
                        # env/run credits maintain a bounded prefetch window.
                        group_need = min(size, max_inflight, max_env_inflight)
                        while self.running:
                            try:
                                await asyncio.wait_for(
                                    pipe.wait_for_capacity(
                                        max_total=max_inflight,
                                        max_env=max_env_inflight,
                                        need=group_need,
                                    ),
                                    timeout=1.0,
                                )
                                break
                            except asyncio.TimeoutError:
                                continue
                        if not self.running:
                            break
                        for tid, traj in inner.items():
                            while self.running:
                                try:
                                    await asyncio.wait_for(
                                        pipe.wait_for_capacity(
                                            max_total=max_inflight,
                                            max_env=max_env_inflight,
                                            need=1,
                                        ),
                                        timeout=1.0,
                                    )
                                    break
                                except asyncio.TimeoutError:
                                    continue
                            if not self.running:
                                break
                            await pipe.submit(iid, tid, traj, size)
                        if not self.running:
                            break
                    self.global_steps += 1
                epoch_box[0] += 1
                logger.info(
                    "Continuous epoch {} complete, {} steps", epoch_box[0], self.global_steps,
                )
        finally:
            self._generation_idle.set()
            try:
                await pipe.quiesce()
                await pipe.aclose()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Continuous pipeline close failed")
            self._continuous_pipeline = None
        logger.info("Continuous generation stopped after {} steps", self.global_steps)

    async def _continuous_pause_check(self, pipe) -> None:
        """Weight-sync handshake: when paused, stop feeding, drain in-flight,
        signal idle (so pause() can run the NCCL sync), then wait for resume."""
        async with self.lock:
            paused = self.paused
        if not paused:
            return
        if self.idle_start_time is None:
            self.idle_start_time = time.time()
        await pipe.quiesce()            # drain in-flight (NCCL needs idle workers)
        self._generation_idle.set()     # signal pause(): safe to sync now
        async with self.lock:
            while self.paused and self.running:
                await self.condition.wait()
        self._generation_idle.clear()   # resumed -> generating again

    async def shutdown(self):
        """Explicitly release rollout-side resources."""
        if self._shutdown_done:
            return
        self._shutdown_done = True

        async with self.lock:
            self.running = False
            self.paused = False
            self.condition.notify_all()

        if self.validate_task and not self.validate_task.done():
            self.validate_task.cancel()
            await asyncio.gather(self.validate_task, return_exceptions=True)
        self.validate_task = None

        await self._generation_idle.wait()

        if self.mcp_loop_manager is not None:
            close = getattr(self.mcp_loop_manager, "close", None)
            if callable(close):
                await close()
            self.mcp_loop_manager = None

        self.rollout_executor.shutdown(wait=False, cancel_futures=True)
        self.validate_executor.shutdown(wait=False, cancel_futures=True)

    async def fit(self):
        """Start the async rollouter - main entry point."""
        logger.info("Starting...")

        if self.message_queue_client is None:
            raise ValueError("MessageQueue client not set. Call set_message_queue_client() first.")

        # The loop the per-instance streaming push must run on (the Ray actor
        # event loop). The dispatch runs in the executor thread on a different
        # loop and schedules pushes here via run_coroutine_threadsafe.
        self._main_loop = asyncio.get_running_loop()

        async with self.lock:
            self.paused = False
            self.running = True

        # Two concurrent tasks: the continuous generation pool + periodic monitor.
        generation_task = asyncio.create_task(self._continuous_generation_main())
        monitor_task = asyncio.create_task(self._async_monitor_loop())

        # Surface a generation crash immediately: gather() below waits on the
        # never-ending monitor, so a swallowed exception in generation would
        # otherwise look like a silent hang (rollout produces nothing).
        def _surface_generation_crash(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.opt(exception=exc).error(
                    "Continuous generation task CRASHED - rollout produces nothing"
                )
        generation_task.add_done_callback(_surface_generation_crash)

        try:
            await asyncio.gather(generation_task, monitor_task, return_exceptions=True)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Task error: {}", e)
        finally:
            if not generation_task.done():
                generation_task.cancel()
            if not monitor_task.done():
                monitor_task.cancel()
            await asyncio.gather(generation_task, monitor_task, return_exceptions=True)

        # Send termination signal (None) so Trainer knows Rollouter has stopped
        await self.message_queue_client.put_sample(
            sample=None,
            param_version=self.current_param_version,
        )

        async with self.lock:
            self.running = False

        await self.shutdown()

        logger.info("fit completed")

    # ==================== Pause / Resume ====================
    # Called by orchestrator during weight sync:
    # pause() -> NCCL broadcast -> update_param_version() -> resume()

    async def pause(self):
        """Pause rollout generation for weight sync.

        After setting the paused flag, waits for any in-flight generation to
        finish (via ``_generation_idle``).  This ensures NCCL weight sync does
        not corrupt an inference that is still using the old weights.
        """
        logger.info("[Pause]")
        async with self.lock:
            self.paused = True
            self.monitor_loop_trigger = False
        # Wait for any in-flight generation to finish before returning,
        # so NCCL weight sync doesn't corrupt mid-inference.
        await self._generation_idle.wait()
        logger.info("[Pause] generation idle, safe to sync")

    async def resume(self, dependency_ref: ObjectRef = None):
        """Resume rollout generation after weight sync."""
        # dependency_ref: optional Ray ObjectRef to wait on before resuming
        if dependency_ref is not None:
            ray.get(dependency_ref)
        logger.info("[Resume]")
        async with self.lock:
            self.paused = False
            self.monitor_loop_trigger = True
            # Wake up _continuous_generation_main waiting on condition.wait()
            self.condition.notify_all()

    async def stop(self):
        """Signal the rollouter to stop after the current batch.

        Called by the orchestrator when the trainer has finished all its
        gradient updates.
        """
        logger.info("[Stop] Signaling rollouter to stop")
        async with self.lock:
            self.running = False
            self.paused = False
            self.condition.notify_all()

    async def update_param_version(
        self, version: int, validate: bool = False, global_steps: int = 0,
        use_trainer_do_validate: bool = False,
    ):
        """Update parameter version after weight sync."""
        async with self.lock:
            old_version = self.current_param_version
            self.current_param_version = version
            # Reset stale_queue_items to current queue size (all old-version data)
            self.stale_queue_items = await self.message_queue_client.get_queue_size()

            # Compute idle ratio: fraction of time rollouter spent waiting
            # (both weight-sync pause and queue backpressure).
            # High idle_ratio = rollouter waits for trainer (consider larger staleness_threshold)
            # Low idle_ratio = rollouter is the bottleneck
            timing_raw = {}
            idle_ratio = None
            if self.idle_start_time is not None and self.version_start_time is not None:
                rollout_active_time = self.idle_start_time - self.version_start_time
                rollout_version_time = time.time() - self.version_start_time
                idle_ratio = 1 - rollout_active_time / rollout_version_time
                timing_raw["rollouter/active_time"] = rollout_active_time
                timing_raw["rollouter/version_time"] = rollout_version_time
                timing_raw["rollouter/idle_ratio"] = idle_ratio
                self.idle_start_time = None
            logger.info(
                "update_param_version: {} -> {}, stale_queue_items={}, idle_ratio={}",
                old_version, version, self.stale_queue_items, idle_ratio,
            )

            # Determine if validation should run based on test_freq
            need_validate = (
                (
                    self.config.rollout.test_freq > 0
                    and self.current_param_version % self.config.rollout.test_freq == 0
                    and self.current_param_version > 0
                )
                or validate
            )

            data = None
            if not need_validate:
                # No validation needed; send timing info only
                data = ValidateMetrics(
                    timing_raw=timing_raw, metrics=None,
                    global_steps=global_steps, param_version=version,
                )
            elif not self.parallel_validate_and_rollout:
                # Synchronous validation: blocks until done
                data = self._validate_wrapper(timing_raw, version, global_steps, use_trainer_do_validate)

            if data is not None:
                await self.message_queue_client.put_validate(ray.cloudpickle.dumps(data))

            self.version_start_time = time.time()

        # Async validation: runs in separate executor, does not block generation
        if need_validate and self.parallel_validate_and_rollout:
            if self.validate_task and not self.validate_task.done():
                await self.validate_task
            self.validate_task = asyncio.create_task(
                self.do_validate_async(timing_raw, version, global_steps, use_trainer_do_validate)
            )

    # ==================== Validation ====================
    # Collect all val instances -> single generate_sequences() call ->
    # MCPRewardManager computes reward. Uses validation LLM config (temperature=0.0).

    def _validate_wrapper(self, timing_raw, version, global_steps=0, use_trainer_do_validate=False):
        """Run validation and return ValidateMetrics."""
        val_metrics = None
        with marked_timer("rollouter/validate_time", timing_raw, color="green"):
            val_metrics = self._validate(use_trainer_do_validate)
        return ValidateMetrics(
            timing_raw=timing_raw, metrics=val_metrics,
            global_steps=global_steps, param_version=version,
        )

    async def do_validate_async(self, timing_raw, version, global_steps=0, use_trainer_do_validate=False):
        """Run validation asynchronously in executor."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            self.validate_executor,
            functools.partial(
                self._validate_wrapper,
                timing_raw=timing_raw, version=version,
                global_steps=global_steps,
                use_trainer_do_validate=use_trainer_do_validate,
            ),
        )
        await self.message_queue_client.put_validate(ray.cloudpickle.dumps(data))

    def _validate(self, use_trainer_do_validate=False) -> Optional[dict]:  # pylint: disable=unused-argument
        """Run validation using MCPLoopManager.

        Collects all validation instances into a single batch and calls
        ``generate_sequences()`` - same code path as training rollout.
        """
        if self.val_dataloader is None:
            return {}

        val_num_trajectories = self.mcp_loop_manager.val_num_trajectories
        val_reward_fn = MCPRewardManager(self.tokenizer, num_examine=1)

        # Merge all validation instances into one large batch for efficiency
        all_instances: list = []
        for test_data in self.val_dataloader:
            instances = self._parse_batch_to_instances(
                test_data if "non_tensor_batch" not in test_data
                else test_data["non_tensor_batch"],
            )
            all_instances.extend(instances)

        if not all_instances:
            return {}

        logger.info(
            "[Validation] {} instances x {} trajectories = {} total",
            len(all_instances), val_num_trajectories,
            len(all_instances) * val_num_trajectories,
        )

        # Generate all validation trajectories in one call
        val_batch = self._batch_dict_to_dataproto({
            "non_tensor_batch": {
                key: [inst.get(key) for inst in all_instances]
                for key in all_instances[0].keys()
            },
        })
        # val_mode=True tells MCPLoopManager to use validation config (temperature=0.0)
        val_batch.meta_info.update({
            "do_sample": self.config.actor_rollout_ref.rollout.val_kwargs.do_sample,
            "validate": True,
            "val_mode": True,
        })
        self._ensure_env_pool_for_batch(val_batch)
        val_output = self.mcp_loop_manager.generate_sequences(
            val_batch, manage_pool=False,
        )

        # Empty val_output guard:
        # When upstream rollout returns 0 trajectories (env-pool failure /
        # all MCP servers unreachable), val_output.batch is None. Continuing
        # would crash with a NoneType error in reward_fn / np.array() / various
        # tensor ops and take the whole training run down. Return empty metrics
        # early so training continues instead of dying because validation failed.
        if val_output.batch is None or len(val_output) == 0:
            logger.warning(
                "[Validation] Empty val_output (batch={}, len={}). "
                "Likely cause: env-pool docker daemon unreachable or all MCP "
                "servers failed to initialize. Skipping validation metrics; "
                "training will continue but val/* metrics will be missing.",
                "None" if val_output.batch is None else "set",
                len(val_output),
            )
            return {}

        # Merge original fields (e.g. ground_truth) back into output, repeated
        # val_num_trajectories times per instance to align with generated trajectories
        for key in all_instances[0].keys():
            if key not in val_output.non_tensor_batch:
                vals = []
                for inst in all_instances:
                    vals.extend([inst.get(key)] * val_num_trajectories)
                val_output.non_tensor_batch[key] = np.array(vals, dtype=object)
        val_output.meta_info["validate"] = True

        result = val_reward_fn(val_output, return_dict=True)
        reward_tensor = result["reward_tensor"]
        scores = reward_tensor.sum(-1).cpu().tolist()
        rollout_metrics = val_output.meta_info.get("rollout_metrics", {})
        num_requested = int(
            rollout_metrics.get("num_trajectories")
            or rollout_metrics.get("num_requested")
            or len(all_instances) * val_num_trajectories
        )

        # Aggregate validation metrics
        metric_dict = compute_validation_reward_metrics(
            scores, num_requested=num_requested, prefix="val",
        )
        if metric_dict:
            logger.info(
                "[Validation] success_rate={:.2%}, mean_reward={:.4f}, "
                "num_samples={}, collected={}, missing={}",
                metric_dict["val/success_rate"],
                metric_dict["val/mean_reward"],
                metric_dict["val/num_samples"],
                metric_dict["val/num_collected"],
                metric_dict["val/num_missing"],
            )

        return metric_dict

    # ==================== Monitor & Statistics ====================

    async def _async_monitor_loop(self):
        """Periodic monitoring: stats logging and rollout recovery."""
        last_stats_time = time.time()
        stats_interval = 60.0
        check_interval = 10.0

        while True:
            async with self.lock:
                if not self.running:
                    break
            await asyncio.sleep(check_interval)

            current_time = time.time()
            if current_time - last_stats_time >= stats_interval:
                stats = await self.get_statistics()
                logger.info("[Monitor] {}", pformat(stats))
                last_stats_time = current_time

            # Safety net: if backpressure has cleared but main loop is still paused,
            # proactively wake it up (guards against lost resume() notifications)
            if self.monitor_loop_trigger:
                if not await self._should_pause_generation():
                    async with self.lock:
                        self.paused = False
                        self.condition.notify_all()

    async def _should_pause_generation(self) -> bool:
        """Check if generation should be paused (queue backpressure)."""
        queue_stats = self.message_queue_client.get_statistics_sync()
        queue_size = queue_stats["queue_size"]

        # Condition 1: queue physically full (prevents OOM)
        if queue_size >= self.max_queue_size:
            return True

        # Condition 2: too many items generated under current version.
        # Even if queue is not full, producing more only creates staler data.
        if self.stale_queue_items >= self.max_required_queue_items:
            return True

        return False

    async def get_statistics(self) -> dict:
        """Get rollouter statistics with unit-explicit metric keys."""
        queue_stats = self.message_queue_client.get_statistics_sync()
        pipe = getattr(self, "_continuous_pipeline", None)
        pipe_stats = pipe.stats() if pipe is not None else {}

        env_pool_stats = {}
        runtime = getattr(self.mcp_loop_manager, "_env_pool_runtime", None)
        pool = getattr(runtime, "env_pool", None)
        if pool is not None:
            stats = pool.get_stats()
            env_pool_stats = {
                "env_pool/total_envs": stats.total_envs,
                "env_pool/ready_envs": stats.ready_envs,
                "env_pool/in_use_envs": stats.in_use_envs,
                "env_pool/error_envs": stats.error_envs,
                "env_pool/in_flight_provisions": getattr(pool, "_in_flight", 0),
                "env_pool/reuse_policy": getattr(pool, "reuse_policy", "cache"),
                "env_pool/max_pool_size": getattr(pool, "max_pool_size", 0),
                "env_pool/max_ready_envs": getattr(pool, "max_ready_envs", 0),
                "env_pool/max_ready_per_key": getattr(pool, "max_ready_per_key", 0),
            }

        return {
            "monitor/queue/mq_queue_size": queue_stats["queue_size"],
            "continuous/in_flight": pipe_stats.get("in_flight", 0),
            "continuous/env_inflight": pipe_stats.get("env_inflight", 0),
            "continuous/run_inflight": pipe_stats.get("run_inflight", 0),
            "continuous/env_queue_size": pipe_stats.get("env_queue_size", 0),
            "continuous/run_queue_size": pipe_stats.get("run_queue_size", 0),
            "continuous/eval_queue_size": pipe_stats.get("eval_queue_size", 0),
            "continuous/active_instances": pipe_stats.get("active_instances", 0),
            **env_pool_stats,
            "count/current_param_version": self.current_param_version,
            "count/total_generated_queue_items": self.total_generated_queue_items,
            "count/stale_queue_items": self.stale_queue_items,
            "count/dropped_stale_queue_items": self.dropped_stale_queue_items,
            "count/failed_rollout_batches": self.failed_rollout_batches,
            "count/global_steps": self.global_steps,
            "static/max_required_queue_items": self.max_required_queue_items,
            "static/required_tasks": self.required_tasks,
            "static/required_trajectories": self.required_trajectories,
            "static/global_trajectory_minibatch": self.global_trajectory_minibatch,
            "static/local_actor_minibatch": self.local_actor_minibatch,
            "static/alignment_unit": self.alignment_unit,
            "static/trajectories_per_queue_item": self._trajectories_per_queue_item,
            "static/staleness_threshold": self.staleness_threshold,
            "static/max_queue_size": self.max_queue_size,
            "static/rollout_batch_size": self.rollout_batch_size,
        }

    # ==================== Checkpoint ====================
    # Saves/restores DataLoader state for resume. Model weights are saved by Trainer.

    async def save_checkpoint(self, local_global_step_folder: str):
        """Save dataloader state to checkpoint."""
        local_mkdir_safe(local_global_step_folder)
        dataloader_local_path = os.path.join(local_global_step_folder, "data.pt")
        async with self.dataloader_lock:
            # Prefer StatefulDataLoader's state_dict; fall back to global_steps
            if hasattr(self.train_dataloader, "state_dict"):
                dataloader_state_dict = self.train_dataloader.state_dict()
            else:
                dataloader_state_dict = {"global_steps": self.global_steps}
        torch.save(dataloader_state_dict, dataloader_local_path)
        logger.info("Saved dataloader checkpoint to {}", dataloader_local_path)

    def load_checkpoint(self):
        """Load checkpoint including dataloader state."""
        if self.config.trainer.resume_mode == "disable":
            logger.info("Resume disabled, starting from scratch")
            return 0

        if self.config.trainer.default_hdfs_dir is not None:
            raise NotImplementedError("[MCPAsyncRollouter] HDFS resume not implemented")

        checkpoint_folder = self.config.trainer.default_local_dir
        if not os.path.isabs(checkpoint_folder):
            checkpoint_folder = os.path.join(os.getcwd(), checkpoint_folder)

        global_step_folder = find_latest_ckpt_path(checkpoint_folder)

        if self.config.trainer.resume_mode == "auto":
            if global_step_folder is None:
                logger.info("No checkpoint found, starting from scratch")
                return 0
        elif self.config.trainer.resume_mode == "resume_path":
            assert isinstance(self.config.trainer.resume_from_path, str)
            assert "global_step_" in self.config.trainer.resume_from_path
            global_step_folder = self.config.trainer.resume_from_path
            if not os.path.isabs(global_step_folder):
                global_step_folder = os.path.join(os.getcwd(), global_step_folder)
        else:
            raise ValueError(f"[MCPAsyncRollouter] Unknown resume_mode: {self.config.trainer.resume_mode}")

        logger.info("Loading checkpoint from: {}", global_step_folder)

        # Checkpoint folder names use current_param_version. Each synced
        # param version covers trigger_parameter_sync_step trainer updates,
        # and each trainer update consumes enough batch queue items to reach
        # required_trajectories.
        checkpoint_param_version = int(global_step_folder.split("global_step_")[-1])
        queue_items_per_train_step = max(
            1,
            -(-self.required_trajectories // max(1, self._trajectories_per_queue_item)),
        )
        trig = self.config.async_training.trigger_parameter_sync_step
        consumed_queue_items = checkpoint_param_version * queue_items_per_train_step * trig
        consumed_rollout_steps = consumed_queue_items
        self.global_steps = consumed_rollout_steps + 1
        logger.info(
            "Setting global_steps to {} from checkpoint_param_version={}, "
            "queue_items_per_train_step={}, trigger_parameter_sync_step={}, "
            "trajectories_per_queue_item={}",
            self.global_steps, checkpoint_param_version,
            queue_items_per_train_step, trig, self._trajectories_per_queue_item,
        )

        dataloader_local_path = os.path.join(global_step_folder, "data.pt")
        if os.path.exists(dataloader_local_path):
            dataloader_state_dict = torch.load(dataloader_local_path, weights_only=False)
            if hasattr(self.train_dataloader, "load_state_dict"):
                self.train_dataloader.load_state_dict(dataloader_state_dict)
            elif "global_steps" in dataloader_state_dict:
                self.global_steps = dataloader_state_dict["global_steps"]
            logger.info("Loaded dataloader state from {}", dataloader_local_path)
        else:
            logger.warning("No dataloader state at {}", dataloader_local_path)
