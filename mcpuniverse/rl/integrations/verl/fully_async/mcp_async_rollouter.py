# pylint: disable=super-init-not-called,invalid-overridden-method,arguments-renamed

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

from ..mcp_dataset import create_mcp_dataset, mcp_collate_fn
from ..mcp_loop_manager import MCPLoopManager
from ..mcp_reward_manager import MCPRewardManager
from ..utils import _LazyLogger

from .mcp_async_data import MCPRolloutSample

logger = _LazyLogger()


# max_concurrency=100: allow many concurrent Ray async method calls
# (pause/resume/stop/update_param_version) without blocking each other.
@ray.remote(num_cpus=10, max_concurrency=100)
class MCPFullyAsyncRollouter(SeparateRayPPOTrainer):  # pylint: disable=too-many-instance-attributes
    # Inherits SeparateRayPPOTrainer for resource pool and worker group init,
    # but does not use its training logic — Rollouter only does inference.
    """Batch-based MCP sample generator for fully async training.

    Generates training samples in batches via MCPLoopManager (same code path
    as hybrid mode) and pushes them into a MessageQueue for the trainer.

    Unlike the per-instance streaming approach, each batch goes through ONE
    ``generate_sequences()`` call with ONE dispatcher, giving the same
    concurrency behavior as hybrid mode (``max_parallel_agents`` concurrent
    trajectory runs, no Docker env pool contention).

    The "async" benefit comes from decoupling rollout and training via the
    queue: the trainer can process previous results while the rollouter
    generates the next batch.
    """

    def __init__(
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
        self.total_train_steps = None  # computed in set_max_required_samples()

        self.message_queue_client = None
        self.rollout_wg = None
        self.actor_rollout_wg = None
        self.mcp_loop_manager = None
        self.rollout_replicas = None

        # Backpressure: staleness_threshold controls how far ahead rollouter can run
        self.staleness_threshold: float = config.async_training.get("staleness_threshold", 1)
        self.require_batches = config.async_training.require_batches
        self.required_samples = (
            config.actor_rollout_ref.actor.ppo_mini_batch_size * self.require_batches
        )
        self.max_required_samples = None  # computed in set_max_required_samples()
        self.max_queue_size = None

        rollout_n = config.actor_rollout_ref.rollout.get("n", 1)
        self._trajectories_per_queue_item = rollout_n  # updated in _create_dataloader

        # Counters
        self.current_param_version = 0
        self.total_generated_samples = 0
        self.staleness_samples = 0
        self.dropped_stale_samples = 0
        self.failed_sample_count = 0
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
        self.max_parallel_agents = mcp_cfg.get("max_parallel_agents", 16)
        self.rollout_executor = ThreadPoolExecutor(max_workers=1)
        self.validate_executor = ThreadPoolExecutor(max_workers=1)
        self.parallel_validate_and_rollout = config.async_training.get(
            "parallel_validate_and_rollout", False,
        )
        self.validate_task = None

    async def set_message_queue_client(self, message_queue_client: MessageQueueClient):
        """Set message queue client."""
        async with self.lock:
            self.message_queue_client = message_queue_client

    async def set_max_required_samples(self):
        """Compute derived backpressure limits (in queue-item units)."""
        async with self.lock:
            trig = self.config.async_training.trigger_parameter_sync_step
            queue_items_per_train_step = max(1, -(-self.required_samples // self._trajectories_per_queue_item))
            self.max_required_samples = int(
                queue_items_per_train_step
                * (self.staleness_threshold + 1)
                * trig
            )
            self.max_queue_size = self.max_required_samples

            configured_steps = self.config.async_training.get("total_train_steps", None)
            if configured_steps:
                self.total_train_steps = configured_steps
            else:
                self.total_train_steps = int(
                    self.total_rollout_steps
                    / (queue_items_per_train_step * trig)
                )

            logger.info(
                "required_samples(trajectories): {} trajectories_per_queue_item: {} "
                "queue_items_per_train_step: {} max_queue_size: {} "
                "total_train_steps: {} (configured={})",
                self.required_samples, self._trajectories_per_queue_item,
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
        max_parallel = mcp_cfg.get("max_parallel_agents", 16)
        rollout_n = self.config.actor_rollout_ref.rollout.get("n", 1)
        # Default: ceil(max_parallel / n) to fill dispatcher concurrency slots
        default_batch_size = max(1, -(-max_parallel // max(1, rollout_n)))
        rollout_batch_size = self.config.data.get("gen_batch_size", default_batch_size) or default_batch_size
        self.rollout_batch_size = rollout_batch_size
        self._trajectories_per_queue_item = rollout_batch_size * rollout_n

        val_batch_size = self.config.data.get("val_batch_size", rollout_batch_size) or rollout_batch_size
        num_workers = self.config.data.get("num_workers", 8)

        logger.info(
            "Rollout batch_size={} (instances), n={} (trajectories/instance), "
            "total_per_batch={}, max_parallel_agents={}",
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
            from verl.experimental.fully_async_policy.sglang_rollout.sglang_async_server import (  # pylint: disable=no-name-in-module
                FullyAsyncSGLangReplica as ReplicaClass,
            )
        elif rollout_name == "vllm":
            from verl.experimental.fully_async_policy.vllm_rollout.vllm_async_server import (  # pylint: disable=no-name-in-module
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

    def _run_rollout_batch_sync(self, batch_dict: dict) -> DataProto:
        """Generate trajectories for a batch (blocking).

        Same code path as hybrid mode: one ``generate_sequences()`` call,
        one dispatcher, ``max_parallel_agents`` concurrent trajectories.
        """
        batch = self._batch_dict_to_dataproto(batch_dict)
        # Blocking call: runs its own asyncio loop for the MCP agent tool-calling loop.
        # All instances in the batch share one dispatcher, capped at max_parallel_agents.
        result = self.mcp_loop_manager.generate_sequences(batch)
        return result

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

    # ==================== Main loop ====================

    async def _batch_generation_main(self):
        """Main batch-based generation loop.

        Iterates the dataset for total_epochs, generating trajectories via
        ``generate_sequences()`` one batch at a time and pushing results to the
        MessageQueue.  Exits when all epochs are exhausted or when ``stop()``
        sets ``self.running = False``.

        Each batch goes through: running check -> pause check (weight sync) ->
        backpressure check (queue full) -> generate -> push to queue.
        """
        logger.info(
            "Starting batch generation: batch_size={}, max_parallel_agents={}",
            self.rollout_batch_size, self.max_parallel_agents,
        )

        epoch = 0
        while self.running:
            for batch_dict in self.train_dataloader:

                # ---- Running check ----
                if not self.running:
                    logger.info("Stop signal received at step {}", self.global_steps)
                    return

                # ---- Pause check ----
                # Wait if paused for weight sync. Record idle_start_time on first
                # entry to measure how long the rollouter is idle (for idle_ratio).
                async with self.lock:
                    while self.paused and self.running:
                        if self.idle_start_time is None:
                            self.idle_start_time = time.time()
                        await self.condition.wait()
                if not self.running:
                    return

                # ---- Queue backpressure ----
                # If queue is full or too many stale samples, wait for Trainer to
                # consume. Also counts toward idle time for idle_ratio.
                # idle_start_time check is inside the loop so it gets re-set after
                # update_param_version() resets it mid-loop for the new version.
                while await self._should_pause_generation():
                    if not self.running:
                        return
                    if self.idle_start_time is None:
                        self.idle_start_time = time.time()
                    await asyncio.sleep(1.0)

                # ---- Generate (blocking, in executor thread) ----
                # clear() fence: signals pause() that generation is in progress
                self._generation_idle.clear()
                start_time = time.time()
                loop = asyncio.get_running_loop()

                try:
                    # Run blocking generate_sequences() in executor thread so
                    # the Ray async actor event loop remains responsive to control calls
                    result = await loop.run_in_executor(
                        self.rollout_executor,
                        functools.partial(self._run_rollout_batch_sync, batch_dict),
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    self.failed_sample_count += 1
                    logger.exception("Batch generation failed at step {}", self.global_steps)
                    continue
                finally:
                    # set() fence: generation done, safe to proceed with NCCL weight sync
                    self._generation_idle.set()

                processing_time = time.time() - start_time

                # ---- Push to message queue ----
                # Wrap result in MCPRolloutSample with param_version for staleness tracking
                rollout_sample = MCPRolloutSample(
                    data=result,
                    param_version=self.current_param_version,
                    instance_id=f"batch_{epoch}_{self.global_steps}",
                    sample_id=f"sample_{epoch}_{self.global_steps}",
                    epoch=epoch,
                    processing_time=processing_time,
                )

                # put_sample returns False if the sample is rejected as stale
                success = await self.message_queue_client.put_sample(
                    sample=ray.cloudpickle.dumps(rollout_sample),
                    param_version=rollout_sample.param_version,
                )
                if success:
                    self.total_generated_samples += 1
                    self.staleness_samples += 1
                else:
                    self.dropped_stale_samples += 1

                logger.info(
                    "Batch step={} done in {:.1f}s, total_generated={}, queue_push={}",
                    self.global_steps, processing_time,
                    self.total_generated_samples, "ok" if success else "dropped",
                )
                self.global_steps += 1

            epoch += 1
            logger.info("Epoch {} complete, {} steps so far", epoch, self.global_steps)

        logger.info("Generation stopped after {} epochs, {} steps", epoch, self.global_steps)

    async def fit(self):
        """Start the async rollouter — main entry point."""
        logger.info("Starting...")

        if self.message_queue_client is None:
            raise ValueError("MessageQueue client not set. Call set_message_queue_client() first.")

        async with self.lock:
            self.paused = False
            self.running = True

        # Two concurrent tasks: generation loop + periodic monitor
        generation_task = asyncio.create_task(self._batch_generation_main())
        monitor_task = asyncio.create_task(self._async_monitor_loop())

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
            # Wake up _batch_generation_main waiting on condition.wait()
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
            # Reset staleness_samples to current queue size (all old-version data)
            self.staleness_samples = await self.message_queue_client.get_queue_size()

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
                "update_param_version: {} -> {}, staleness_samples={}, idle_ratio={}",
                old_version, version, self.staleness_samples, idle_ratio,
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
        ``generate_sequences()`` — same code path as training rollout.
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
            "[Validation] {} instances × {} trajectories = {} total",
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
        val_output = self.mcp_loop_manager.generate_sequences(val_batch)

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

        # Aggregate validation metrics
        metric_dict = {}
        if scores:
            scores_arr = np.array(scores)
            success_rate = float((scores_arr > 0).mean())
            mean_reward = float(scores_arr.mean())
            metric_dict["val/success_rate"] = success_rate
            metric_dict["val/mean_reward"] = mean_reward
            metric_dict["val/num_samples"] = len(scores_arr)
            logger.info(
                "[Validation] success_rate={:.2%}, mean_reward={:.4f}, num_samples={}",
                success_rate, mean_reward, len(scores_arr),
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
        if self.staleness_samples >= self.max_required_samples:
            return True

        return False

    async def get_statistics(self) -> dict:
        """Get rollouter statistics."""
        queue_stats = self.message_queue_client.get_statistics_sync()

        return {
            "monitor/queue/mq_queue_size": queue_stats["queue_size"],
            "count/current_param_version": self.current_param_version,
            "count/total_generated_samples": self.total_generated_samples,
            "count/staleness_samples": self.staleness_samples,
            "count/dropped_stale_samples": self.dropped_stale_samples,
            "count/failed_samples": self.failed_sample_count,
            "count/global_steps": self.global_steps,
            "static/max_required_samples": self.max_required_samples,
            "static/required_samples": self.required_samples,
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

        # Derive Rollouter's global_steps from Trainer's global_step in checkpoint path.
        # Conversion: each Trainer step consumes queue_items_per_train_step items,
        # and every trig steps triggers a weight sync.
        trainer_global_steps = int(global_step_folder.split("global_step_")[-1])
        queue_items_per_train_step = max(1, -(-self.required_samples // self._trajectories_per_queue_item))
        trig = self.config.async_training.trigger_parameter_sync_step
        self.global_steps = trainer_global_steps * queue_items_per_train_step * trig + 1
        logger.info("Setting global_steps to {}", self.global_steps)

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
