# pylint: disable=too-many-instance-attributes,super-init-not-called,invalid-overridden-method,protected-access

"""
MCP Fully Async Trainer for VERL Integration.

A queue-consuming PPO trainer that pulls rollout samples from a MessageQueue
(produced by MCPFullyAsyncRollouter) and runs the standard PPO training
pipeline: log_prob -> advantage -> actor/critic update -> weight sync.

Based on veRL upstream's FullyAsyncTrainer (Meituan contribution),
adapted for MCP agent training with MCPRewardManager.
"""

import os
import time
from datetime import datetime

import numpy as np
import ray
from omegaconf import OmegaConf
from tqdm import tqdm

from verl import DataProto
from verl.experimental.fully_async_policy.detach_utils import (
    MetricsAggregator,
    ValidateMetrics,
)
from verl.experimental.fully_async_policy.message_queue import MessageQueueClient
from verl.experimental.separation.ray_trainer import SeparateRayPPOTrainer
from verl.single_controller.ray import RayClassWithInitArgs, RayWorkerGroup
from verl.trainer.ppo import core_algos
from verl.trainer.ppo.ray_trainer import ResourcePoolManager
from verl.trainer.ppo.utils import Role, WorkerType, need_critic, need_reference_policy, need_reward_model
from verl.utils.checkpoint.checkpoint_manager import find_latest_ckpt_path, should_save_ckpt_esi
from verl.utils.debug import marked_timer
from verl.utils.tracking import Tracking, ValidationGenerationsLogger

from ..utils import _LazyLogger, extract_reward
from ..mcp_reward_manager import MCPRewardManager

from .mcp_async_data import assemble_mcp_training_batch

logger = _LazyLogger()


class TrainingStopException(Exception):
    """Raised when the message queue signals training should stop."""


# num_cpus=10: Trainer is CPU-intensive (data assembly, metrics computation);
# reserving enough CPUs prevents contention with Actor worker group.
@ray.remote(num_cpus=10)
class MCPFullyAsyncTrainer(SeparateRayPPOTrainer):
    """Fully asynchronous PPO trainer for MCP agent training.

    Obtains rollout samples from a MessageQueue and runs the PPO training
    pipeline. Weight updates trigger ParameterSynchronizer to broadcast
    new weights to the rollouter.
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
        # Skip super().__init__() to avoid initializing rollout components;
        # in fully async mode the Trainer never performs rollout.
        self.tokenizer = tokenizer
        self.processor = processor
        self.config = config

        # Fully async mode requires separate training and inference GPUs.
        self.hybrid_engine = config.actor_rollout_ref.hybrid_engine
        assert not self.hybrid_engine, "Fully async mode requires hybrid_engine=False"

        self.role_worker_mapping = role_worker_mapping
        self.resource_pool_manager = resource_pool_manager
        self.use_reference_policy = need_reference_policy(self.config)
        self.use_rm = need_reward_model(self.config)
        if self.use_rm:
            # MCP computes reward via MCPRewardManager from non_tensor_batch["rewards"];
            # no external reward model is needed.
            logger.warning(
                "reward_model.enable=True but MCP uses MCPRewardManager. Setting use_rm=False."
            )
            self.use_rm = False
        self.use_critic = need_critic(self.config)
        self.ray_worker_group_cls = ray_worker_group_cls
        self.device_name = device_name if device_name else self.config.trainer.device

        # When using LoRA, ref policy reuses the frozen base weights inside the actor
        # instead of loading a separate model, saving GPU memory.
        lora_rank = config.actor_rollout_ref.model.get("lora", {}).get("rank", 0)
        if lora_rank <= 0:
            lora_rank = config.actor_rollout_ref.model.get("lora_rank", 0)
        self.ref_in_actor = (
            lora_rank > 0
            or config.actor_rollout_ref.model.get("lora_adapter_path") is not None
        )

        # KL penalty in reward prevents policy from diverging too far from ref policy.
        self.kl_ctrl_in_reward = None
        if self.config.algorithm.use_kl_in_reward:
            self.kl_ctrl_in_reward = core_algos.get_kl_controller(self.config.algorithm.kl_ctrl)

        self.use_prefix_grouper = self.config.actor_rollout_ref.actor.get("use_prefix_grouper", False)
        self.use_legacy_worker_impl = config.trainer.get("use_legacy_worker_impl", "auto")

        # ==================== SeparateRayPPOTrainer state ====================
        # global_steps starts at 1 and increments once per fit_step.
        self.global_steps = 1
        self.epoch = 0
        self.max_steps_duration = 0
        self.progress_bar = None
        self.logger = None
        self.is_last_step = False
        self.prev_step_profile = False
        self.curr_step_profile = False
        self.next_step_profile = False
        self.last_val_metrics = {}
        self.metrics = {}
        self.timing_raw = {}
        self.validation_generations_logger = ValidationGenerationsLogger(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
        )
        self.future_reward = None
        self.reward_tensor = None
        self.reward_extra_infos_dict = {}

        # ==================== Worker groups (set in _init_models) ====================
        self.actor_wg = None
        self.actor_rollout_wg = None
        self.critic_wg = None
        self.ref_policy_wg = None
        self.rm_wg = None

        # ==================== Fully async config ====================
        self.message_queue_client = None
        self.param_synchronizer = None

        # local_trigger_step: counts training steps between weight syncs (1-based).
        # MIS (Multiple Importance Sampling): allows multi-step training before syncing
        # to increase throughput at the cost of reduced on-policy data quality.
        self.local_trigger_step = 1
        self.processed_samples = 0
        # Staleness tracking: data produced under old weights (due to async delay)
        # increases off-policy degree and is monitored for training quality.
        self.stale_samples_processed = 0
        self.stale_trajectory_processed = 0
        # current_param_version increments once per weight sync.
        self.current_param_version = 0
        self.total_train_steps = None
        # trigger_parameter_sync_step: weight sync frequency in training steps.
        self.trigger_parameter_sync_step = config.async_training.trigger_parameter_sync_step
        self.last_ckpt_version = 0
        self.train_val_metrics = None

        # MCPRewardManager converts scalar rewards from non_tensor_batch["rewards"]
        # into a [B, S] token-level reward tensor, placing the reward at the last
        # valid response token and zeros elsewhere — the format required by PPO GAE.
        self.reward_fn = MCPRewardManager(tokenizer, num_examine=0)
        # num_examine=1: print one sample per validation step for inspection.
        self.val_reward_fn = MCPRewardManager(tokenizer, num_examine=1)

        self.require_batches = config.async_training.require_batches
        # required_samples = ppo_mini_batch_size * require_batches
        self.required_samples = (
            config.actor_rollout_ref.actor.ppo_mini_batch_size * self.require_batches
        )

        # MetricsAggregator accumulates per-step metrics and reports them on sync.
        total_gpus = (
            config.trainer.nnodes * config.trainer.n_gpus_per_node
            + config.rollout.nnodes * config.rollout.n_gpus_per_node
        )
        self.metrics_aggregator = MetricsAggregator(total_gpus=total_gpus)

    # ==================== Wiring methods ====================

    def set_message_queue_client(self, message_queue_client: MessageQueueClient):
        """Set message queue client."""
        self.message_queue_client = message_queue_client

    def set_parameter_synchronizer(self, param_synchronizer):
        """Set parameter synchronizer."""
        self.param_synchronizer = param_synchronizer

    def set_total_train_steps(self, total_train_steps):
        """Set total training steps and create progress bar."""
        self.total_train_steps = total_train_steps
        self.progress_bar = tqdm(total=self.total_train_steps, initial=0, desc="MCP Async Training")

    def get_actor_wg(self):
        """Get actor worker group."""
        return self.actor_wg

    # ==================== Worker initialization ====================

    def _create_actor_rollout_classes(self):
        """Create only actor worker class (trainer does not do rollout)."""
        for role in [Role.Actor]:
            resource_pool = self.resource_pool_manager.get_resource_pool(role)
            role_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[role],
                config=self.config.actor_rollout_ref,
                role=str(role),
            )
            self.resource_pool_to_cls[resource_pool][str(role)] = role_cls

    def _init_models(self):
        """Initialize actor (and optionally critic, ref policy) models."""
        if self.use_critic:
            self.critic_wg = self.all_wg[str(Role.Critic)]
            self.critic_wg.init_model()

        if self.use_reference_policy and not self.ref_in_actor:
            self.ref_policy_wg = self.all_wg[str(Role.RefPolicy)]
            self.ref_policy_wg.init_model()

        if self.use_rm:
            self.rm_wg = self.all_wg[str(Role.RewardModel)]
            self.rm_wg.init_model()

        self.actor_wg = self.all_wg[str(Role.Actor)]
        self.actor_wg.init_model()
        # actor_rollout_wg aliases actor_wg for upstream API compatibility
        # (_compute_old_log_prob, save_checkpoint, etc.)
        self.actor_rollout_wg = self.actor_wg

    async def init_workers(self):
        """Initialize distributed training workers."""
        self._init_resource_pools()
        self._create_worker_classes()
        self._init_worker_groups()
        self._init_models()

    # ==================== Queue consumption ====================

    def _get_samples_from_queue(self) -> tuple[None, None] | tuple[int, DataProto]:
        """Pull samples from message queue and assemble training batch.

        Collects MCPRolloutSample objects from the queue until the total
        number of trajectories reaches ``required_samples``
        (= ``ppo_mini_batch_size * require_batches``).

        Each MCPRolloutSample may contain multiple trajectories (e.g. one
        batch of ``rollout_batch_size * n`` trajectories), so we count
        actual trajectory rows rather than sample count.
        """
        logger.info(
            "Requesting {} trajectories from queue", self.required_samples,
        )

        consumer_start = time.time()
        rollout_samples = []
        total_trajectories = 0
        queue_len = 0

        while total_trajectories < self.required_samples:
            # get_sample_sync blocks until a sample is available.
            result = self.message_queue_client.get_sample_sync()

            # get_sample_sync returns None when queue is closed,
            # or (sample_data, queue_length) tuple otherwise.
            if result is None:
                logger.info(
                    "Queue closed (None). Collected {}/{} trajectories from {} samples",
                    total_trajectories, self.required_samples, len(rollout_samples),
                )
                break

            sample_bytes, queue_len = result

            if sample_bytes is None:
                logger.info(
                    "Termination signal received. Collected {}/{} trajectories from {} samples",
                    total_trajectories, self.required_samples, len(rollout_samples),
                )
                break

            # Deserialize immediately to count trajectory rows.
            rollout_sample = ray.cloudpickle.loads(sample_bytes)
            rollout_samples.append(rollout_sample)

            sample_traj_count = (
                len(rollout_sample.data)
                if rollout_sample.data is not None and rollout_sample.data.batch is not None
                else 0
            )
            total_trajectories += sample_traj_count

            if len(rollout_samples) % 10 == 0:
                logger.info(
                    "Collected {}/{} trajectories from {} samples. mq_len: {}",
                    total_trajectories, self.required_samples,
                    len(rollout_samples), queue_len,
                )

        consumer_end = time.time()

        # Return None to signal training termination if queue closed before enough data.
        if not rollout_samples or total_trajectories < self.required_samples:
            logger.warning(
                "Not enough trajectories: {}/{}",
                total_trajectories, self.required_samples,
            )
            return None, None

        total_wait_time = consumer_end - consumer_start
        logger.info(
            "Collection done: {}/{} trajectories from {} samples, "
            "wait_time: {:.2f}s, mq_len: {}",
            total_trajectories, self.required_samples,
            len(rollout_samples), total_wait_time, queue_len,
        )

        # Merge samples into a unified DataProto: aligns padding, concatenates tensors,
        # merges non_tensor_batch, and collects param_version metadata.
        batch = assemble_mcp_training_batch(
            rollout_samples, self.tokenizer, self.config,
        )

        batch.meta_info["fully_async/total_wait_time"] = total_wait_time
        return 0, batch

    # ==================== PPO pipeline ====================

    def _fit_generate(self, batch: DataProto = None) -> DataProto:
        """Get batch from message queue (replaces rollout generation)."""
        metrics = self.metrics
        timing_raw = self.timing_raw
        with marked_timer("gen", timing_raw, color="red"):
            _, batch = self._get_samples_from_queue()
            if batch is None:
                raise TrainingStopException("Training terminated: queue returned None")
            self._collect_metrics_from_samples(batch, metrics)
        return batch

    def _fit_compute_reward(self, batch: DataProto) -> DataProto:
        """Compute rewards using MCPRewardManager.

        MCP rewards are typically pre-computed during rollout (stored in
        non_tensor_batch["rewards"] or batch["rm_scores"]).
        MCPRewardManager handles all cases and places the reward at the
        last valid response token position in a [B, S] tensor.

        The result is stored in batch["rm_scores"] so that the inherited
        _fit_compute_advantage can extract it via extract_reward().
        """
        timing_raw = self.timing_raw
        with marked_timer("reward", timing_raw, color="yellow"):
            if self.use_rm and "rm_scores" not in batch.batch.keys():
                batch_reward = self._compute_reward_colocate(batch)
                batch = batch.union(batch_reward)

            if "rm_scores" not in batch.batch.keys():
                result = self.reward_fn(batch, return_dict=True)
                reward_tensor = result["reward_tensor"]
                reward_extra_infos_dict = result.get("reward_extra_info", {})
                batch.batch["rm_scores"] = reward_tensor
                self.reward_tensor = reward_tensor
                self.reward_extra_infos_dict = reward_extra_infos_dict
            else:
                self.reward_tensor, self.reward_extra_infos_dict = extract_reward(batch)
        return batch

    def _compute_old_log_prob(self, batch: DataProto):
        """MIS pattern: save/restore CPU weights for multi-step between syncs.

        If local_trigger_step == 1: save current weights to CPU
        If local_trigger_step > 1: restore version-1 weights, compute, restore current
        """
        # MIS (Multiple Importance Sampling): when trigger_parameter_sync_step > 1,
        # the trainer runs multiple gradient steps before syncing weights. PPO requires
        # old_log_prob from the behavior policy, so we save/restore weights to ensure
        # importance ratios are computed against the policy that generated the data.
        #
        # Step 1 (local_trigger_step == 1): save current weights to CPU slot 1,
        #   compute old_log_prob with current weights (on-policy).
        # Step N (local_trigger_step > 1): save updated weights to slot N, restore slot 1,
        #   compute old_log_prob, restore slot N, then free slot N.

        # Debug: log worker group info for GPU utilization investigation
        wg = self.actor_rollout_wg
        n_workers = len(wg._workers) if hasattr(wg, '_workers') else 'N/A'
        dispatch_info = wg._dispatch_info.get("actor", "NOT_QUERIED")
        collect_info = wg._collect_info.get("actor", "NOT_QUERIED")
        logger.info(
            "[DEBUG dispatch] actor_rollout_wg: n_workers={}, dispatch_info={}, collect_info={}, batch_size={}",
            n_workers, dispatch_info, collect_info, len(batch),
        )

        if self.local_trigger_step == 1:
            self.actor_rollout_wg.save_model_to_cpu(1)
            old_log_prob, old_log_prob_mfu = super()._compute_old_log_prob(batch)
        else:
            self.actor_rollout_wg.save_model_to_cpu(self.local_trigger_step)
            self.actor_rollout_wg.restore_model_from_cpu(1)
            old_log_prob, old_log_prob_mfu = super()._compute_old_log_prob(batch)
            self.actor_rollout_wg.restore_model_from_cpu(self.local_trigger_step)
            self.actor_rollout_wg.clear_cpu_model(self.local_trigger_step)
        return old_log_prob, old_log_prob_mfu

    # ==================== Training loop ====================

    async def fit(self):
        """Main training loop: pull from queue, train, sync weights."""
        logger.info("Starting...")
        if self.message_queue_client is None:
            raise ValueError("MessageQueue client not set.")
        if self.param_synchronizer is None:
            raise ValueError("ParameterSynchronizer not set.")

        self.logger = Tracking(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
            default_backend=self.config.trainer.logger,
            config=OmegaConf.to_container(self.config, resolve=True),
        )

        self.max_steps_duration = 0

        # Pull any initial validation data generated by the rollouter before training.
        self._log_validation_data()

        # Loop terminates via TrainingStopException when the queue closes.
        # total_train_steps is used only for tqdm display, not for stopping.
        while True:
            try:
                await self.fit_step()
            except TrainingStopException:
                logger.info("Training stopped by queue termination signal")
                break

        ray.get(self.param_synchronizer.wait_last_valid.remote())
        self._log_validation_data()

        # Force a final weight sync + validation if the last version didn't trigger one
        # or if there are unsynchronized local training steps.
        if self.current_param_version % self.config.rollout.test_freq != 0 or self.local_trigger_step > 1:
            await self._trigger_parameter_sync_after_step(validate=True, global_steps=self.global_steps)
            ray.get(self.param_synchronizer.wait_last_valid.remote())
            self._log_validation_data()

        self.progress_bar.close()
        self._fit_save_checkpoint()

    def _fit_start_profile(self):
        """Override: no-op if global_profiler config is missing."""
        if hasattr(self.config, "global_profiler") and self.config.global_profiler is not None:
            super()._fit_start_profile()

    def _fit_stop_profile(self):
        """Override: no-op if global_profiler config is missing."""
        if hasattr(self.config, "global_profiler") and self.config.global_profiler is not None:
            super()._fit_stop_profile()

    def _fit_torch_memory(self):
        """Override: no-op if profiler config is missing."""
        if hasattr(self.config.actor_rollout_ref.actor, "profiler"):
            super()._fit_torch_memory()

    async def fit_step(self, batch_dict: dict = None):
        """Single training step: get batch -> PPO pipeline -> weight sync."""
        logger.info("fit_step")
        self.metrics = {"training/global_step": self.global_steps, "training/epoch": self.epoch}
        self.timing_raw = {}
        self.future_reward = None
        self.reward_tensor = None
        self.reward_extra_infos_dict = {}

        self._fit_start_profile()

        with marked_timer("step", self.timing_raw):
            batch = self._fit_generate(None)
            batch = self._fit_compute_reward(batch)
            batch = self._fit_compute_log_prob(batch)
            batch = self._fit_compute_ref_log_prob(batch)
            batch = self._fit_compute_critic(batch)
            batch = self._fit_compute_advantage(batch)
            batch = self._fit_update_critic(batch)
            batch = self._fit_update_actor(batch)
            self._fit_dump_data(batch)

        self._fit_stop_profile()
        self._fit_collect_metrics(batch)
        await self._fit_update_weights()
        self._fit_save_checkpoint()
        self._fit_torch_memory()
        self._fit_postprocess_step()

    def _fit_collect_metrics(self, batch):
        """Collect metrics and log validation data."""
        super()._fit_collect_metrics(batch)
        self.metrics_aggregator.add_step_metrics(
            metrics=self.metrics, sample_count=self.required_samples, timestamp=time.time(),
        )
        self._log_validation_data()

    async def _fit_update_weights(self):
        """Trigger parameter synchronization after training step."""
        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        logger.info(
            "global_steps={} local_trigger_step={} trigger_parameter_sync_step={} {}",
            self.global_steps, self.local_trigger_step, self.trigger_parameter_sync_step, time_str,
        )
        await self._trigger_parameter_sync_after_step()

    def _fit_save_checkpoint(self):
        """Save checkpoint based on version and frequency."""
        # Checkpoint decision uses param_version (not global_steps) because
        # param_version is the true indicator of model state changes.
        timing_raw = self.timing_raw
        # ESI (Early Stop Indicator): force checkpoint when job is near timeout.
        esi_close_to_expiration = should_save_ckpt_esi(
            max_steps_duration=self.max_steps_duration,
            redundant_time=self.config.trainer.esi_redundant_time,
        )
        if self.config.trainer.save_freq > 0 and (
            self.current_param_version % self.config.trainer.save_freq == 0
            or esi_close_to_expiration
        ):
            if esi_close_to_expiration:
                logger.warning("Force saving checkpoint: ESI expiration approaching.")
            with marked_timer("save_checkpoint", timing_raw, color="green"):
                self._save_checkpoint()

    def _fit_postprocess_step(self):
        """Track step duration and increment global step counter."""
        # Track max step duration for ESI to estimate whether next step will fit.
        steps_duration = self.timing_raw.get("step", 0)
        self.max_steps_duration = max(self.max_steps_duration, steps_duration)
        self.global_steps += 1

    # ==================== Checkpoint ====================

    def _save_checkpoint(self):
        """Save actor (and critic) checkpoint."""
        local_global_step_folder = os.path.join(
            self.config.trainer.default_local_dir,
            f"global_step_{self.current_param_version}",
        )

        logger.info("Saving checkpoint to {}", local_global_step_folder)
        actor_local_path = os.path.join(local_global_step_folder, "actor")

        actor_remote_path = (
            None
            if self.config.trainer.default_hdfs_dir is None
            else os.path.join(
                self.config.trainer.default_hdfs_dir,
                f"global_step_{self.current_param_version}", "actor",
            )
        )

        remove_previous = self.config.trainer.get("remove_previous_ckpt_in_save", False)
        max_actor_ckpt = (
            self.config.trainer.get("max_actor_ckpt_to_keep", None) if not remove_previous else 1
        )
        max_critic_ckpt = (
            self.config.trainer.get("max_critic_ckpt_to_keep", None) if not remove_previous else 1
        )

        self.actor_rollout_wg.save_checkpoint(
            actor_local_path, actor_remote_path,
            self.current_param_version, max_ckpt_to_keep=max_actor_ckpt,
        )

        if self.use_critic:
            critic_local_path = os.path.join(local_global_step_folder, str(Role.Critic))
            critic_remote_path = (
                None
                if self.config.trainer.default_hdfs_dir is None
                else os.path.join(
                    self.config.trainer.default_hdfs_dir,
                    f"global_step_{self.current_param_version}", str(Role.Critic),
                )
            )
            self.critic_wg.save_checkpoint(
                critic_local_path, critic_remote_path,
                self.current_param_version, max_ckpt_to_keep=max_critic_ckpt,
            )

        # Notify Rollouter to save its own checkpoint (e.g. dataloader state).
        ray.get(self.param_synchronizer.rollouter_save_checkpoint.remote(local_global_step_folder))

        # Record latest checkpoint version for fast resume lookup.
        latest_path = os.path.join(
            self.config.trainer.default_local_dir,
            "latest_checkpointed_iteration.txt",
        )
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(str(self.current_param_version))

    def load_checkpoint(self):
        """Load checkpoint and resume training state."""
        if self.config.trainer.resume_mode == "disable":
            self.actor_rollout_wg.load_checkpoint(None)
            return 0

        if self.config.trainer.default_hdfs_dir is not None:
            raise NotImplementedError("HDFS resume not implemented")

        checkpoint_folder = self.config.trainer.default_local_dir
        if not os.path.isabs(checkpoint_folder):
            checkpoint_folder = os.path.join(os.getcwd(), checkpoint_folder)
        global_step_folder = find_latest_ckpt_path(checkpoint_folder)

        if self.config.trainer.resume_mode == "auto":
            if global_step_folder is None:
                logger.info("Training from scratch")
                self.actor_rollout_wg.load_checkpoint(None)
                return 0
        elif self.config.trainer.resume_mode == "resume_path":
            assert isinstance(self.config.trainer.resume_from_path, str)
            assert "global_step_" in self.config.trainer.resume_from_path
            global_step_folder = self.config.trainer.resume_from_path
            if not os.path.isabs(global_step_folder):
                global_step_folder = os.path.join(os.getcwd(), global_step_folder)

        logger.info("Loading checkpoint from: {}", global_step_folder)
        # Recover global_steps: each param_version spans trigger_parameter_sync_step training steps.
        self.current_param_version = int(global_step_folder.split("global_step_")[-1])
        self.global_steps = self.current_param_version * self.trigger_parameter_sync_step + 1
        self.last_ckpt_version = self.current_param_version
        logger.info(
            "global_steps={}, param_version={}",
            self.global_steps, self.current_param_version,
        )

        actor_path = os.path.join(global_step_folder, "actor")
        self.actor_rollout_wg.load_checkpoint(
            actor_path, del_local_after_load=self.config.trainer.del_local_ckpt_after_load,
        )

        if self.use_critic:
            critic_path = os.path.join(global_step_folder, str(Role.Critic))
            self.critic_wg.load_checkpoint(
                critic_path, del_local_after_load=self.config.trainer.del_local_ckpt_after_load,
            )

        return self.current_param_version

    # ==================== Metrics ====================

    def _collect_metrics_from_samples(self, batch, metrics):
        """Collect staleness, async, and training batch statistics from batch."""
        if hasattr(batch, "meta_info") and batch.meta_info:
            # Staleness tracking: data produced under an older param_version is off-policy.
            # A higher stale ratio indicates greater asynchrony and potential training quality loss.
            samples_param_versions = batch.meta_info.get("rollout_param_versions", [])
            stale_count = sum(
                1 for v in samples_param_versions
                if self.current_param_version - v >= 1
            )
            self.stale_samples_processed += stale_count

            # Per-trajectory staleness is more granular than per-sample.
            trajectory_param_versions = batch.meta_info.get("trajectory_param_versions", [])
            stale_traj_count = sum(
                1 for v in trajectory_param_versions
                if self.current_param_version - v >= 1
            )
            self.stale_trajectory_processed += stale_traj_count

            metrics.update({
                "fully_async/count/stale_samples_processed": self.stale_samples_processed,
                "fully_async/count/stale_trajectory_processed": self.stale_trajectory_processed,
                "fully_async/count/current_param_version": self.current_param_version,
            })

            for key, value in batch.meta_info.items():
                if key.startswith("fully_async") or key.startswith("timing_s"):
                    metrics[key] = value

        if hasattr(batch, "non_tensor_batch") and batch.non_tensor_batch is not None:
            if "rewards" in batch.non_tensor_batch:
                rewards = np.asarray(batch.non_tensor_batch["rewards"], dtype=float)
                metrics["train_batch/num_trajectories"] = len(rewards)
                metrics["train_batch/mean_reward"] = float(np.mean(rewards))
                metrics["train_batch/total_reward"] = float(np.sum(rewards))
                metrics["train_batch/max_reward"] = float(np.max(rewards))
                metrics["train_batch/min_reward"] = float(np.min(rewards))
                metrics["train_batch/success_rate"] = float(np.mean(rewards > 0))
                metrics["train_batch/success_count"] = int(np.sum(rewards > 0))

            if "uid" in batch.non_tensor_batch:
                uids = batch.non_tensor_batch["uid"]
                metrics["train_batch/num_instances"] = len(set(uids))

    # ==================== Parameter sync ====================

    async def _trigger_parameter_sync_after_step(self, validate: bool = False, global_steps: int = 0):
        """Trigger weight sync to rollouter after sufficient training steps."""
        # Only sync after trigger_parameter_sync_step local steps, unless forced via validate.
        # Reducing sync frequency improves throughput (NCCL broadcast has non-trivial cost).
        if self.local_trigger_step < self.trigger_parameter_sync_step and not validate:
            self.local_trigger_step += 1
            return

        self.current_param_version += 1
        self.local_trigger_step = 1
        self.logger.log(
            data=self.metrics_aggregator.get_aggregated_metrics(),
            step=self.current_param_version,
        )
        self.progress_bar.update(1)
        self.metrics_aggregator.reset()

        timing_param_sync = {}
        with marked_timer("timing_s/wait_last_valid", timing_param_sync):
            ray.get(self.param_synchronizer.wait_last_valid.remote())
        # use_trainer_do_validate=False: MCP validation is handled by Rollouter
        # (requires MCP environment interaction), not the Trainer.
        with marked_timer("timing_s/param_sync", timing_param_sync):
            ray.get(
                self.param_synchronizer.sync_weights.remote(
                    self.current_param_version,
                    validate=validate,
                    global_steps=self.global_steps if not global_steps else global_steps,
                    use_trainer_do_validate=False,
                )
            )
        self.logger.log(data=timing_param_sync, step=self.current_param_version)

    def _log_validation_data(self):
        """Pull and log validation metrics from message queue."""
        # Validation is produced by Rollouter and pushed to a dedicated validate channel;
        # Trainer pulls and forwards to the tracking logger (e.g. wandb).
        val_data = self.message_queue_client.get_validate_sync()
        if not val_data:
            return

        val_metrics: ValidateMetrics = ray.cloudpickle.loads(val_data)
        if val_metrics.metrics:
            self.logger.log(data=val_metrics.metrics, step=val_metrics.param_version)
            logger.info(
                "param_version={} Validation: {}",
                val_metrics.param_version, val_metrics.metrics,
            )
        self.logger.log(data=val_metrics.timing_raw, step=val_metrics.param_version)
