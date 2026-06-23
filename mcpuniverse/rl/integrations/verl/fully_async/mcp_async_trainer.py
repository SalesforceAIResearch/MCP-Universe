# pylint: disable=too-many-instance-attributes,super-init-not-called,invalid-overridden-method
# pylint: disable=protected-access,too-many-lines,import-outside-toplevel,broad-exception-caught

"""
MCP Fully Async Trainer for VERL Integration.

A queue-consuming PPO trainer that pulls rollout samples from a MessageQueue
(produced by MCPFullyAsyncRollouter) and runs the standard PPO training
pipeline: log_prob -> advantage -> actor/critic update -> weight sync.

Based on veRL upstream's FullyAsyncTrainer (Meituan contribution),
adapted for MCP agent training with MCPRewardManager.
"""

import gc
import os
import time
from datetime import datetime

import numpy as np
import ray
import torch
from omegaconf import OmegaConf
from tqdm import tqdm

from verl import DataProto
from verl.protocol import pad_dataproto_to_divisor
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

from ..utils import (
    _LazyLogger,
    extract_reward,
    flatten_and_reduce_metrics_inplace,
)
# Re-exported so tests/docs can reference it as
# ``mcp_async_trainer.flatten_dataproto_metrics_inplace``.
from ..utils import flatten_dataproto_metrics_inplace  # pylint: disable=unused-import
from ..mcp_reward_manager import MCPRewardManager
from ..mcp_log_prob_entropy import pop_entropy_metric_if_present

from .mcp_async_data import assemble_mcp_training_batch
from .mcp_async_queue import collect_rollout_samples_from_queue
from ..mcp_batch_sizing import (
    ExcessivePaddingException,
    compute_mcp_batch_sizing,
    get_max_pad_ratio,
)

logger = _LazyLogger()


def _maybe_dump_logprob_alignment(batch, step: int) -> None:
    """ENV-gated per-token dump to localize the rollout<->train logprob mismatch.

    Enable with MCP_DUMP_LOGPROB_ALIGN=<dir> (or =1 for cwd). For the first
    MCP_DUMP_LOGPROB_ALIGN_STEPS steps (default 2) it saves, for the first
    MCP_DUMP_LOGPROB_ALIGN_NSEQ sequences (default 16), the *aligned* per-token
    arrays: responses (token ids), response_mask, old_log_probs (Megatron),
    rollout_log_probs (SGLang). response_mask transitions encode turn boundaries
    (assistant=1, tool-result=0). Interpretation of where |old-rollout| is large:
      * clustered at mask transitions  -> multi-turn assembly / re-conditioning bug
      * uniform & ~uncorrelated         -> per-token alignment (off-by-N) bug
      * correlated but shifted          -> async staleness / weight-sync drift
    Diagnostic only; never touched unless the env var is set.
    """
    # Gate via env var OR a shared-filesystem sentinel file (robust to Ray/Apptainer
    # env-propagation: the sentinel lives on /export/share visible to every actor).
    # Sentinel: <repo>/_align_diag/DUMP_LOGPROB_ALIGN ; its (optional) contents = out dir.
    dest = os.environ.get("MCP_DUMP_LOGPROB_ALIGN", "")
    max_steps = int(os.environ.get("MCP_DUMP_LOGPROB_ALIGN_STEPS", "2"))
    if not dest:
        sentinel = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "..", "..", "_align_diag", "DUMP_LOGPROB_ALIGN",
        )
        sentinel = os.path.abspath(sentinel)
        if os.path.exists(sentinel):
            try:
                with open(sentinel, encoding="utf-8") as f:
                    dest = f.read().strip() or "1"
            except Exception:
                dest = "1"
    if not dest or step > max_steps:
        return
    b = batch.batch
    if "old_log_probs" not in b or "rollout_log_probs" not in b:
        return
    try:
        nseq = int(os.environ.get("MCP_DUMP_LOGPROB_ALIGN_NSEQ", "16"))
        default_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "..", "..", "_align_diag", "logprob_align_dumps",
        )
        outdir = os.path.abspath(default_dir) if dest == "1" else dest
        os.makedirs(outdir, exist_ok=True)
        def _np(key, cast_long=False):
            if key not in b:
                return None
            t = b[key][:nseq].detach()
            t = t.to(torch.long) if cast_long else t.float()
            return t.cpu().numpy()

        old = _np("old_log_probs")
        roll = _np("rollout_log_probs")
        # prompts/input_ids/position_ids/attention_mask enable offline HF arbitration
        # (re-score the exact [prompt+response] with disk weights to find who is wrong).
        path = os.path.join(outdir, f"logprob_align_step{step}.npz")
        np.savez_compressed(
            path,
            responses=_np("responses", cast_long=True),
            response_mask=_np("response_mask"),
            old_log_probs=old, rollout_log_probs=roll,
            prompts=_np("prompts", cast_long=True),
            input_ids=_np("input_ids", cast_long=True),
            position_ids=_np("position_ids", cast_long=True),
            attention_mask=_np("attention_mask"),
            # R3 diagnosis: SGLang-recorded routing that R3 replays, aligned with tokens
            # ([bs, prompt+resp, num_layers, topk]). Present only when RRR is on.
            routed_experts=_np("routed_experts", cast_long=True),
        )
        mask = _np("response_mask")
        m = mask if mask is not None else np.ones_like(old)
        mb = m > 0.5
        if mb.any():
            o, r = old[mb], roll[mb]
            corr = float(np.corrcoef(o, r)[0, 1]) if o.size > 1 else float("nan")
            logger.info(
                f"[LOGPROB_ALIGN] step={step} dumped {path} | masked={int(mb.sum())} "
                f"corr(old,roll)={corr:.3f} mean|old-roll|={float(np.abs(o - r).mean()):.3f} "
                f"old_ppl={float(np.exp(-o.mean())):.2f} roll_ppl={float(np.exp(-r.mean())):.2f}"
            )
    except Exception as e:  # pragma: no cover - diagnostic path must never break training
        logger.warning("[LOGPROB_ALIGN] dump failed: %s", e)


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
        # Staleness tracking: data produced under old weights (due to async delay)
        # increases off-policy degree and is monitored for training quality.
        # Two units: queue items (one per MCPRolloutSample) and trajectories
        # (one per row in the assembled DataProto); trajectory count is more
        # granular because one queue item carries up to rollout.n trajectories.
        self.stale_queue_items_processed = 0
        self.stale_trajectories_processed = 0
        # current_param_version increments once per weight sync.
        self.current_param_version = 0
        self.total_train_steps = None
        # trigger_parameter_sync_step: weight sync frequency in training steps.
        self.trigger_parameter_sync_step = config.async_training.trigger_parameter_sync_step
        self.last_ckpt_version = 0
        self.train_val_metrics = None

        # MCPRewardManager converts scalar rewards from non_tensor_batch["rewards"]
        # into a [B, S] token-level reward tensor, placing the reward at the last
        # valid response token and zeros elsewhere - the format required by PPO GAE.
        self.reward_fn = MCPRewardManager(tokenizer, num_examine=0)
        # num_examine=1: print one sample per validation step for inspection.
        self.val_reward_fn = MCPRewardManager(tokenizer, num_examine=1)

        # Single source of truth for batch sizing - see MCPBatchSizing
        # docstring. The ``self.<field>`` mirrors below are kept because
        # they are read in many places inside this class; new code should
        # prefer ``self.batch_sizing.<field>`` directly.
        self.batch_sizing = compute_mcp_batch_sizing(config)
        self.require_batches = self.batch_sizing.require_batches
        self.required_tasks = self.batch_sizing.required_tasks
        self.required_trajectories = self.batch_sizing.required_trajectories
        self.global_trajectory_minibatch = self.batch_sizing.global_trajectory_minibatch
        self.local_actor_minibatch = self.batch_sizing.local_actor_minibatch
        self.alignment_unit = self.batch_sizing.alignment_unit
        self.actor_dp_size = self.batch_sizing.dp
        self._max_pad_ratio = get_max_pad_ratio(config)
        logger.info(
            "Async batch sizing: {}",
            self.batch_sizing.describe(),
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

    def _init_worker_groups(self):
        # Inject expandable_segments into Megatron trainer worker processes.
        # veRL's _create_worker() overwrites runtime_env.env_vars with its own
        # WORLD_SIZE/RANK vars (base.py:662), so we can't set it via
        # update_options on the RayClassWithInitArgs. Instead, pass it through
        # the worker_env kwarg which gets merged into env_vars at base.py:643.
        strategy = self.config.actor_rollout_ref.actor.get("strategy", "fsdp2")

        from verl.single_controller.ray.base import create_colocated_worker_cls

        all_wg = {}
        wg_kwargs = {}
        if OmegaConf.select(self.config.trainer, "ray_wait_register_center_timeout") is not None:
            wg_kwargs["ray_wait_register_center_timeout"] = self.config.trainer.ray_wait_register_center_timeout
        wg_kwargs["device_name"] = getattr(self, "device_name", "cuda")

        if strategy == "megatron":
            worker_env = {
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True,garbage_collection_threshold:0.6",
            }
            # Propagate the entropy-memory switches to EVERY trainer rank (head +
            # all worker nodes). The fused logprob+entropy patch source-rewrites
            # forward_backward_batch; if some ranks rewrite and others do not (env
            # only set on the launcher node), their TP all-reduces desync -> hang.
            # Forwarding from os.environ here guarantees one consistent value.
            for _k in ("MCP_FUSED_LOGPROB_ENTROPY", "MCP_FUSED_LE_CHUNK", "MCP_VOCAB_ENTROPY_CHUNK_NNZ"):
                _v = os.environ.get(_k)
                if _v is not None:
                    worker_env[_k] = _v
            wg_kwargs["worker_env"] = worker_env
            logger.info("Will inject worker_env into trainer workers: {}", dict(worker_env))

        for resource_pool, class_dict in self.resource_pool_to_cls.items():
            worker_dict_cls = create_colocated_worker_cls(class_dict=class_dict)
            wg_dict = self.ray_worker_group_cls(
                resource_pool=resource_pool,
                ray_cls_with_init=worker_dict_cls,
                **wg_kwargs,
            )
            spawn_wg = wg_dict.spawn(prefix_set=class_dict.keys())
            all_wg.update(spawn_wg)
        self.all_wg = all_wg  # pylint: disable=attribute-defined-outside-init

    def _pad_batch_for_training(self, batch: DataProto) -> DataProto:
        """Pad batch to ``global_trajectory_minibatch`` using veRL's repeat-pad.

        Mirrors ``MCPPPOTrainer._pad_batch_for_training``. See that method's
        docstring for the full rationale; in short, fully-async Megatron
        actors are double-strict about batch sizing (DP-chunk + per-rank
        ``make_iterator``), and the safest fix when rollout under-collects
        is to repeat-pad the tail using veRL's built-in helper rather than
        either crashing or dropping all of a partial mini-batch.

        Padded entries are real trajectories duplicated from the start
        (not zero-pad); they contribute 2x gradient weight. For typical
        (358 of 360) shortfalls this is a 0.56% per-step bias.

        If the required pad ratio exceeds
        ``mcp_agent.batch_sizing.max_pad_ratio`` (default 0.1), the method
        raises ``ExcessivePaddingException`` so the outer ``fit`` loop
        can skip the step instead of taking a heavily-biased PPO update.
        """
        divisor = max(1, int(self.global_trajectory_minibatch))
        original_size = len(batch)
        if original_size <= 0:
            raise TrainingStopException(
                "Cannot pad an empty fully-async training batch."
            )
        if original_size % divisor == 0:
            return batch

        batch_padded, pad_size = pad_dataproto_to_divisor(batch, divisor)
        new_size = len(batch_padded)
        pad_ratio = float(pad_size) / float(new_size)

        if pad_ratio > self._max_pad_ratio:
            raise ExcessivePaddingException(
                pad_size=pad_size, batch_size=new_size, threshold=self._max_pad_ratio,
            )

        for key in ("global_token_num", "trajectory_param_versions"):
            values = batch_padded.meta_info.get(key)
            if isinstance(values, list) and 0 < len(values) < new_size:
                pad_values = [values[i % len(values)] for i in range(new_size - len(values))]
                batch_padded.meta_info[key] = list(values) + pad_values

        logger.warning(
            "Padded fully-async batch from {} to {} trajectories (pad_size={}, "
            "ratio={:.3f}, threshold={:.3f}, repeats first {} sample(s)) to "
            "satisfy global_trajectory_minibatch={} alignment",
            original_size, new_size, pad_size, pad_ratio, self._max_pad_ratio,
            pad_size, divisor,
        )
        return batch_padded

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

        Collects per-instance rollout queue items until one PPO minibatch worth
        of tasks is available.
        """
        collection = collect_rollout_samples_from_queue(
            self.message_queue_client,
            required_tasks=self.required_tasks,
            required_trajectories=self.required_trajectories,
            partial_rollout=self.config.async_training.get("partial_rollout", False),
            task_alignment_unit=self.batch_sizing.ppo_prompt_mini_batch_size,
        )
        rollout_samples = collection.samples
        total_trajectories = collection.total_trajectories

        if not rollout_samples:
            logger.warning(
                "Zero rollout samples, cannot train. Queue closed empty.",
            )
            return None, None

        if len(rollout_samples) < self.required_tasks:
            logger.warning(
                "Partial task batch accepted: {}/{} task items "
                "({}/{} nominal trajectories)",
                len(rollout_samples), self.required_tasks,
                total_trajectories, self.required_trajectories,
            )

        logger.info(
            "Collection done: {}/{} task items, {}/{} nominal trajectories, "
            "wait_time: {:.2f}s, mq_len: {}",
            len(rollout_samples), self.required_tasks,
            total_trajectories, self.required_trajectories,
            collection.total_wait_time, collection.queue_len,
        )

        # Merge samples into a unified DataProto: aligns padding, concatenates tensors,
        # merges non_tensor_batch, and collects param_version metadata.
        batch = assemble_mcp_training_batch(
            rollout_samples, self.tokenizer, self.config,
        )
        batch = self._pad_batch_for_training(batch)

        # Tag the batch with its sizing plan + actual collection stats so
        # downstream metrics / debugging tools have everything in one place.
        batch.meta_info.update(self.batch_sizing.to_meta_info())
        batch.meta_info["fully_async/task_items"] = len(rollout_samples)
        batch.meta_info["fully_async/actual_trajectories"] = len(batch)
        batch.meta_info["fully_async/total_wait_time"] = collection.total_wait_time
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
            strategy = self.config.actor_rollout_ref.actor.get("strategy", "fsdp2")
            if (
                strategy in {"fsdp", "fsdp2"}
                and self.config.trainer.get("balance_batch", False)
            ):
                self._balance_batch(batch, metrics=metrics)
            if batch.batch is not None and "attention_mask" in batch.batch:
                batch.meta_info["global_token_num"] = (
                    torch.sum(batch.batch["attention_mask"], dim=-1).tolist()
                )
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

    def _fit_compute_log_prob(self, batch: DataProto) -> DataProto:
        """Compute old log-probs without requiring entropy when it was skipped."""
        metrics = self.metrics
        timing_raw = self.timing_raw
        rollout_corr_config = self.config.algorithm.get("rollout_correction", None)
        bypass_recomputing_logprobs = rollout_corr_config and rollout_corr_config.get("bypass_mode", False)
        if bypass_recomputing_logprobs:
            from verl.trainer.ppo.rollout_corr_helper import apply_bypass_mode

            apply_bypass_mode(
                batch=batch,
                rollout_corr_config=rollout_corr_config,
                policy_loss_config=self.config.actor_rollout_ref.actor.policy_loss,
            )
        else:
            with marked_timer("old_log_prob", timing_raw, color="blue"):
                old_log_prob, old_log_prob_mfu = self._compute_old_log_prob(batch)
                pop_entropy_metric_if_present(
                    old_log_prob=old_log_prob,
                    batch=batch,
                    actor_config=self.config.actor_rollout_ref.actor,
                    metrics=metrics,
                    agg_loss=core_algos.agg_loss,
                )
                metrics["perf/mfu/actor_infer"] = old_log_prob_mfu
                if "routed_experts" in batch.batch and "routed_experts" in old_log_prob.batch:
                    router_mode = getattr(self.config.actor_rollout_ref.actor.router_replay, "mode", "disabled")
                    if router_mode == "R2":
                        batch.batch.pop("routed_experts")
                    else:
                        old_log_prob.batch.pop("routed_experts")
                batch = batch.union(old_log_prob)
                if "rollout_log_probs" in batch.batch.keys():
                    from verl.utils.debug.metrics import calculate_debug_metrics

                    metrics.update(calculate_debug_metrics(batch))
                    _maybe_dump_logprob_alignment(batch, self.global_steps)

        assert "old_log_probs" in batch.batch, f'"old_log_prob" not in {batch.batch.keys()=}'
        return batch

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
            except ExcessivePaddingException as exc:
                # Rollout under-collected so badly that pad-by-repeat would
                # dominate the gradient with duplicate samples. Drop this
                # batch's compute, log diagnostics, and pull a fresh batch
                # from the queue on the next iteration.
                logger.warning(
                    "Skipping fully-async step {} due to excessive padding: "
                    "{}. Returning to queue for the next batch.",
                    self.global_steps, exc,
                )
                continue

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

    def _fit_update_actor(self, batch: DataProto) -> DataProto:
        """Override: flatten ragged cross-rank metrics before ``reduce_metrics``.

        Repro: Megatron + DP>1 + ``use_dynamic_bsz=true`` lets different DP
        ranks split into different numbers of micro-batches. Each rank emits
        ``{"actor/pg_loss": [m0, m1, ...]}`` of its own length. Ray dispatch
        collects via ``DataProto.concat -> list_of_dict_to_dict_of_list``,
        producing a ragged ``{"actor/pg_loss": [[...], [...]]}``. The verl
        upstream ``reduce_metrics`` then calls ``np.mean(val)`` on the ragged
        list and crashes with::

            ValueError: setting an array element with a sequence.
            The detected shape was (2,) + inhomogeneous part.

        Worker-side flattening alone is insufficient because concat re-nests
        per-worker lists after our wrapper returns. The fix must happen on
        the trainer side, between dispatch return and ``reduce_metrics`` call.

        Semantics: flattening the list-of-lists into a single flat list is
        the correct reduction target -- ``np.mean`` over all per-rank,
        per-micro-batch values is exactly the intended cross-rank average.

        Implementation: delegates to ``flatten_and_reduce_metrics_inplace`` in
        ``..utils`` so the flatten-then-reduce logic can be unit-tested at
        module level without colliding with ray's class-method tracing
        wrapper (which makes calling subclass methods directly very awkward).
        """
        timing_raw = self.timing_raw
        if self.config.trainer.critic_warmup <= self.global_steps:
            with marked_timer("update_actor", timing_raw, color="red"):
                actor_output = self._update_actor(batch)
            flatten_and_reduce_metrics_inplace(actor_output, self.metrics)
        return batch

    def _fit_update_critic(self, batch: DataProto) -> DataProto:
        """Override mirrors ``_fit_update_actor``: flatten merged metrics first.

        Critic is currently disabled in the default mcp-async config, but if
        it is ever enabled the same dynamic-bsz cross-rank imbalance would
        crash the critic reduce path identically. Keep the two overrides in
        lockstep so we don't get a surprise regression later.
        """
        timing_raw = self.timing_raw
        if self.use_critic:
            with marked_timer("update_critic", timing_raw, color="pink"):
                critic_output = self._update_critic(batch)
            flatten_and_reduce_metrics_inplace(critic_output, self.metrics)
        return batch

    async def fit_step(self, batch_dict: dict = None):  # pylint: disable=unused-argument
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
            # Reclaim CPU-side temporaries (re-padded tensors, deserialized
            # queue data) before the GPU-intensive log_prob forward pass.
            gc.collect()
            batch = self._fit_compute_log_prob(batch)
            batch = self._fit_compute_ref_log_prob(batch)
            batch = self._fit_compute_critic(batch)
            batch = self._fit_compute_advantage(batch)
            # Reclaim memory between advantage computation and actor/critic
            # update - the highest-memory pipeline stages.  Without this,
            # stale allocations from log_prob/advantage accumulate and cause
            # fragmentation that triggers OOM in update_actor backward.
            gc.collect()
            batch = self._fit_update_critic(batch)
            gc.collect()
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
            metrics=self.metrics, sample_count=len(batch), timestamp=time.time(),
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
            (self.current_param_version > 0 and self.current_param_version % self.config.trainer.save_freq == 0)
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
        if self.progress_bar is not None:
            self.progress_bar.update(1)
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
            self.stale_queue_items_processed += stale_count

            # Per-trajectory staleness is more granular than per-queue-item.
            trajectory_param_versions = batch.meta_info.get("trajectory_param_versions", [])
            stale_traj_count = sum(
                1 for v in trajectory_param_versions
                if self.current_param_version - v >= 1
            )
            self.stale_trajectories_processed += stale_traj_count

            metrics.update({
                "fully_async/count/stale_queue_items_processed": self.stale_queue_items_processed,
                "fully_async/count/stale_trajectories_processed": self.stale_trajectories_processed,
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
