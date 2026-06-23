"""
MCP PPO Trainer for VERL integration.

Extends VERL's RayPPOTrainer with MCP agent loop support.
Similar to SkyRL's SkyAgentPPOTrainer but uses MCP-Universe.

Note: This trainer only supports hybrid mode (shared GPUs for actor and rollout).
For fully async mode, use MCPFullyAsyncTrainer.
"""
# pylint: disable=import-outside-toplevel,attribute-defined-outside-init,broad-exception-caught,too-many-lines

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import queue
import threading
import time

import numpy as np
import torch
from omegaconf import OmegaConf
from tqdm import tqdm
from loguru import logger

from verl import DataProto
from verl.trainer.ppo.ray_trainer import RayPPOTrainer, Role, compute_advantage
from verl.trainer.ppo.core_algos import agg_loss
from verl.trainer.ppo.metric_utils import (
    compute_data_metrics,
    compute_throughout_metrics,
    compute_timing_metrics,
    process_validation_metrics,
)
from verl.protocol import pad_dataproto_to_divisor, unpad_dataproto
from verl.single_controller.ray import RayClassWithInitArgs
from verl.single_controller.ray.base import create_colocated_worker_cls
from verl.utils.checkpoint.checkpoint_manager import should_save_ckpt_esi
from verl.utils.debug import marked_timer
from verl.utils.metric import reduce_metrics
from verl.utils.tracking import Tracking

from ..mcp_batch_sizing import (
    ExcessivePaddingException,
    compute_mcp_batch_sizing,
    get_max_pad_ratio,
)
from ..data_proto_padding import concat_padded_dataprotos
from ..mcp_log_prob_entropy import pop_entropy_metric_if_present
from ..utils import compute_validation_reward_metrics, extract_reward
from ..mcp_loop_manager import MCPLoopManager


_MISSING = object()


# Inference backends that support the MCP "direct sleep handoff" fast-path
# (abort_all_requests + per-server sleep.remote() instead of replica.sleep()
# which waits for in-flight requests to drain). Both veRL's vLLM and SGLang
# replicas expose ``servers[i].sleep.remote()`` (vLLM: vllm_async_server.py,
# SGLang: async_sglang_server.py:308). ``abort_all_requests`` is vLLM-only
# at the moment (RolloutReplica.abort_all_requests is currently a no-op for
# SGLang); we duck-type via ``getattr(... , None)`` so SGLang gracefully
# skips the abort step and goes straight to sleep.
_ROLLOUT_FAST_PATH_BACKENDS = ("vllm", "sglang")


# Backwards-compatibility for two MCP config keys that were named with
# ``_vllm_`` before we added SGLang support. Map old -> new; reads check the
# new name first, fall back to the legacy name with a warning.
_LEGACY_LIFECYCLE_KEY_RENAMES = {
    "mcp_agent.suspend_rollout_workers_during_postprocess":
        "mcp_agent.suspend_vllm_workers_during_postprocess",
    "mcp_agent.direct_rollout_sleep_handoff":
        "mcp_agent.direct_vllm_sleep_handoff",
}

# Legacy config keys we've already emitted a deprecation warning for (warn once).
_LEGACY_KEYS_WARNED: set = set()


def _select_with_legacy_fallback(config, new_path: str, default=None):
    """Read a MCP lifecycle config key with legacy-name backwards compatibility.

    Looks up ``new_path`` first; if missing, tries the old ``_vllm_`` named
    counterpart (from ``_LEGACY_LIFECYCLE_KEY_RENAMES``) and emits a one-time
    deprecation warning when found. Returns ``default`` if neither is set.
    """
    val = OmegaConf.select(config, new_path, default=None)
    if val is not None:
        return val
    legacy = _LEGACY_LIFECYCLE_KEY_RENAMES.get(new_path)
    if legacy is None:
        return default
    legacy_val = OmegaConf.select(config, legacy, default=None)
    if legacy_val is None:
        return default
    if legacy not in _LEGACY_KEYS_WARNED:
        logger.warning(
            "MCP config key '{}' is deprecated; use '{}' instead. The legacy "
            "name will be removed in a future release.",
            legacy, new_path,
        )
        _LEGACY_KEYS_WARNED.add(legacy)
    return legacy_val


@dataclass(frozen=True)
class _TemperatureState:
    """Training/validation temperature state for temporary validation overrides."""

    had_original: bool
    original: object
    validation: object


def compute_response_mask(batch: DataProto) -> torch.Tensor:
    """Compute response mask from attention mask."""
    attention_mask = batch.batch["attention_mask"]
    prompt_length = batch.batch["prompts"].shape[1]
    response_length = batch.batch["responses"].shape[1]
    response_mask = attention_mask[:, prompt_length:prompt_length + response_length]
    return response_mask


def _normalize_hybrid_rollout_lifecycle_config(config) -> None:
    """Normalize MCP hybrid rollout lifecycle knobs without editing scripts.

    Applies to any inference backend in ``_ROLLOUT_FAST_PATH_BACKENDS`` (vLLM,
    SGLang); SGLang gracefully falls back at runtime if its replica lacks
    ``abort_all_requests`` (handled via ``getattr`` in
    ``_mcp_safe_sleep_replicas_after_rollout``).

    SGLang in hybrid mode is intentionally REJECTED at the top of this
    function (not silently downgraded). veRL has no colocated SGLang worker:
    SGLang always runs as a standalone HTTP server, so hybrid mode would
    double-load the model on the same GPU as the actor and OOM at the first
    ``update_weights``. Use ``fully_async`` (separate actor / rollout GPU
    pools) instead - see ``run_fully_async[_megatron]_train.sh``.
    """
    hybrid_engine = bool(
        OmegaConf.select(config, "actor_rollout_ref.hybrid_engine", default=False)
    )
    rollout_name = str(
        OmegaConf.select(config, "actor_rollout_ref.rollout.name", default="")
    ).lower()

    # Hard-reject SGLang in hybrid mode. The launch scripts already block
    # this at the BACKEND= env check, but enforce here too in case someone
    # bypasses scripts (e.g. directly invokes the hydra entry point with
    # actor_rollout_ref.rollout.name=sglang).
    if hybrid_engine and rollout_name == "sglang":
        raise RuntimeError(
            "Hybrid mode does not support SGLang as the inference backend. "
            "veRL has no colocated SGLangRolloutWorker, so SGLang always runs "
            "as a standalone HTTP server, which double-loads the model on the "
            "same GPU as the actor (OOM at first update_weights). "
            "Use fully_async mode instead: run "
            "`BACKEND=sglang bash scripts/start_multinode_async.sh`. "
            "See mcpuniverse/rl/integrations/verl/README.md > 'Inference Backend'."
        )

    rollout_mode = str(OmegaConf.select(config, "mcp_agent.rollout_mode", default="")).lower()
    free_cache_engine = bool(
        OmegaConf.select(
            config,
            "actor_rollout_ref.rollout.free_cache_engine",
            default=False,
        )
    )

    if (
        hybrid_engine
        and rollout_name in _ROLLOUT_FAST_PATH_BACKENDS
        and rollout_mode == "token"
        and not free_cache_engine
    ):
        OmegaConf.update(
            config,
            "actor_rollout_ref.rollout.free_cache_engine",
            True,
            merge=False,
        )
        logger.info(
            "MCP hybrid TITO normalized actor_rollout_ref.rollout.free_cache_engine "
            "from False to True in memory so sleep_replicas() uses the same "
            "effective lifecycle as older MCP-Universe/veRL hybrid runs."
        )

    suspend_workers = _select_with_legacy_fallback(
        config,
        "mcp_agent.suspend_rollout_workers_during_postprocess",
        default=None,
    )
    if (
        hybrid_engine
        and rollout_name in _ROLLOUT_FAST_PATH_BACKENDS
        and rollout_mode == "token"
        and suspend_workers is None
    ):
        OmegaConf.update(
            config,
            "mcp_agent.suspend_rollout_workers_during_postprocess",
            False,
            merge=False,
            force_add=True,
        )
        logger.info(
            "MCP hybrid TITO leaves local rollout-server suspension disabled; "
            "the lifecycle matches the older update_weights -> rollout -> "
            "postprocess -> sleep handoff."
        )

    direct_sleep_handoff = _select_with_legacy_fallback(
        config,
        "mcp_agent.direct_rollout_sleep_handoff",
        default=None,
    )
    if (
        hybrid_engine
        and rollout_name in _ROLLOUT_FAST_PATH_BACKENDS
        and rollout_mode == "token"
        and direct_sleep_handoff is None
    ):
        OmegaConf.update(
            config,
            "mcp_agent.direct_rollout_sleep_handoff",
            True,
            merge=False,
            force_add=True,
        )
        logger.info(
            "MCP hybrid TITO enables direct rollout sleep handoff by default "
            "(applies to {} backends): after rollout postprocess, stale "
            "request records are aborted (where supported) before sleeping "
            "rollout servers so the trainer does not wait in "
            "checkpoint_manager.sleep_replicas().",
            list(_ROLLOUT_FAST_PATH_BACKENDS),
        )


def _uses_mcp_json_dataset(config, train_dataset=None) -> bool:
    """Return whether the training data path is MCP's lightweight JSON dataset."""
    if train_dataset is not None and train_dataset.__class__.__name__ == "MCPDataset":
        return True

    train_files = OmegaConf.select(config, "data.train_files", default="")
    if isinstance(train_files, (list, tuple)):
        return bool(train_files) and all(str(path).endswith(".json") for path in train_files)
    return str(train_files).endswith(".json")


def _normalize_mcp_dataloader_config(config, train_dataset=None) -> None:
    """Avoid slow worker forking for small in-memory MCP JSON datasets."""
    if not _uses_mcp_json_dataset(config, train_dataset=train_dataset):
        return

    workers = int(
        OmegaConf.select(config, "data.dataloader_num_workers", default=0) or 0
    )
    if workers == 0:
        return

    OmegaConf.update(
        config,
        "data.dataloader_num_workers",
        0,
        merge=False,
        force_add=True,
    )
    logger.warning(
        "MCP JSON dataset is already loaded in memory; setting "
        "data.dataloader_num_workers=0 in memory to avoid slow worker fork "
        "inside the Ray/CUDA TaskRunner. The launch script parameters are unchanged."
    )


class _AsyncTrackingBackend:
    """Small non-blocking adapter for slow experiment tracking backends.

    The worker thread polls the queue with a short timeout and re-checks
    ``self._closed`` on every empty cycle. This avoids the previous sentinel-
    based shutdown which could deadlock when ``finish()`` raced with a full
    queue (sentinel ``put`` raised ``queue.Full`` and the worker stayed
    blocked on ``queue.get()`` forever).
    """

    _POLL_TIMEOUT = 0.5

    def __init__(self, backend, name: str, max_queue_size: int = 2048):
        self._backend = backend
        self._name = name
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._closed = False
        self._warned_full = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"mcp-{name}-tracking",
            daemon=True,
        )
        self._thread.start()

    def log(self, data, step):
        """Enqueue a tracking record (non-blocking; drops if the queue is full)."""
        if self._closed:
            return
        try:
            self._queue.put_nowait((dict(data), step))
        except queue.Full:
            if not self._warned_full:
                self._warned_full = True
                logger.warning(
                    "{} tracking queue is full; dropping later tracking metrics "
                    "to keep training from blocking.",
                    self._name,
                )

    def finish(self, *args, **kwargs):
        """Close the tracker and flush the background logging thread."""
        self._closed = True
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            logger.warning(
                "{} tracking thread did not exit within 5s after finish(); "
                "leaking daemon thread.", self._name,
            )

        finish = getattr(self._backend, "finish", None)
        if callable(finish):
            return finish(*args, **kwargs)
        return None

    def _run(self):
        while True:
            try:
                item = self._queue.get(timeout=self._POLL_TIMEOUT)
            except queue.Empty:
                if self._closed:
                    return
                continue
            try:
                data, step = item
                self._backend.log(data=data, step=step)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("{} tracking log failed: {}", self._name, exc)
            finally:
                self._queue.task_done()


def _wrap_slow_tracking_backends(tracking_logger, config) -> None:
    """Make network tracking backends non-blocking for the training loop."""
    enabled = bool(OmegaConf.select(config, "mcp_agent.async_tracking", default=True))
    if not enabled or not hasattr(tracking_logger, "logger"):
        return

    for backend_name in ("wandb", "vemlp_wandb"):
        backend = tracking_logger.logger.get(backend_name)
        if backend is None or isinstance(backend, _AsyncTrackingBackend):
            continue
        tracking_logger.logger[backend_name] = _AsyncTrackingBackend(
            backend,
            backend_name,
        )
        logger.info(
            "Using asynchronous {} tracking backend so metric logging cannot "
            "block rollout/training handoff.",
            backend_name,
        )


class MCPPPOTrainer(RayPPOTrainer):  # pylint: disable=too-many-instance-attributes
    """
    Distributed PPO trainer with MCP agent support (Hybrid Mode).

    Extends VERL's RayPPOTrainer to use MCPLoopManager for
    agent-based rollout with MCP tool use.

    Key differences from RayPPOTrainer:
    1. Uses MCPLoopManager instead of standard rollout
    2. Supports MCP server configuration
    3. Handles multi-turn agent trajectories

    Note: This trainer only supports hybrid mode (shared GPUs).
    For fully async mode, use MCPFullyAsyncTrainer.

    Usage:
        ```python
        from mcpuniverse.rl.integrations.verl import MCPPPOTrainer

        trainer = MCPPPOTrainer(
            config=config,
            tokenizer=tokenizer,
            reward_fn=reward_fn,
            ...
        )
        trainer.init_workers()
        trainer.fit()
        ```
    """

    def __init__(
        self,
        config,
        tokenizer,
        processor,
        role_worker_mapping,
        resource_pool_manager,
        ray_worker_group_cls,
        reward_fn=None,
        val_reward_fn=None,
        train_dataset=None,
        val_dataset=None,
        collate_fn=None,
        train_sampler=None,
        device_name: str = "cuda",
    ):
        """
        Initialize MCP PPO trainer (Hybrid Mode).

        Args:
            config: Training configuration
            tokenizer: Tokenizer
            processor: Processor (for multimodal)
            role_worker_mapping: Mapping from roles to worker classes
            resource_pool_manager: Resource pool manager
            ray_worker_group_cls: Ray worker group class
            reward_fn: Reward function for training
            val_reward_fn: Reward function for validation
            train_dataset: Training dataset
            val_dataset: Validation dataset
            collate_fn: Collate function
            train_sampler: Training sampler
            device_name: Device for training ("cuda" or "npu")
        """
        logger.info("Initializing MCPPPOTrainer in HYBRID MODE")
        _normalize_hybrid_rollout_lifecycle_config(config)
        _normalize_mcp_dataloader_config(config, train_dataset=train_dataset)
        super().__init__(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            collate_fn=collate_fn,
            train_sampler=train_sampler,
            device_name=device_name,
        )

        # reward_fn / val_reward_fn are no longer accepted by RayPPOTrainer.__init__
        # in newer VERL versions, so we store them ourselves.
        self.reward_fn = reward_fn
        self.val_reward_fn = val_reward_fn
        self.async_rollout_manager = None

        # MCP config
        rollout_n = max(1, int(self.config.actor_rollout_ref.rollout.get("n", 1)))
        self.num_trajectories = rollout_n
        try:
            OmegaConf.update(
                self.config,
                "mcp_agent.num_trajectories",
                self.num_trajectories,
                merge=False,
                force_add=True,
            )
        except Exception as exc:
            # ``force_add=True`` should always succeed; failing means the live
            # OmegaConf is in an exotic struct mode we can't write through.
            # The previous fallback (``mcp_cfg["num_trajectories"] = ...``)
            # mutated a local copy returned by ``config.get(..., {})`` and
            # silently never reached self.config. Surface the failure loudly
            # so the caller can fix the yaml; downstream MCPLoopManager will
            # still derive num_trajectories from rollout.n when > 1.
            logger.warning(
                "OmegaConf.update for mcp_agent.num_trajectories failed: {}. "
                "MCPLoopManager will rely on rollout.n={} instead.",
                exc, rollout_n,
            )

        self.batch_sizing = compute_mcp_batch_sizing(config, require_batches=1)
        self.global_trajectory_minibatch = self.batch_sizing.global_trajectory_minibatch
        self.local_actor_minibatch = self.batch_sizing.local_actor_minibatch
        self.alignment_unit = self.batch_sizing.alignment_unit
        self.actor_dp_size = self.batch_sizing.dp
        self._max_pad_ratio = get_max_pad_ratio(config)

        logger.info(
            "MCPPPOTrainer initialized with {} trajectories (synced from rollout.n); "
            "batch sizing: strategy={} ppo_prompt_mini_batch_size={} "
            "global_trajectory_minibatch={} actor_dp={} "
            "local_actor_minibatch={} alignment_unit={}",
            self.num_trajectories,
            self.batch_sizing.strategy,
            self.batch_sizing.ppo_prompt_mini_batch_size,
            self.global_trajectory_minibatch,
            self.actor_dp_size,
            self.local_actor_minibatch,
            self.alignment_unit,
        )

    def _rollout_free_cache_engine_enabled(self) -> bool:
        """Return rollout free-cache setting for lifecycle diagnostics."""
        return bool(
            OmegaConf.select(
                self.config,
                "actor_rollout_ref.rollout.free_cache_engine",
                default=False,
            )
        )

    @staticmethod
    def _rollout_replicas_already_slept(batch: DataProto | None) -> bool:
        """Return whether rollout generation already slept hybrid replicas."""
        if batch is None:
            return False
        meta_info = getattr(batch, "meta_info", None) or {}
        return bool(meta_info.get("rollout_replicas_slept", False))

    def _mcp_safe_sleep_replicas_after_rollout(self, context: str) -> bool:  # pylint: disable=too-many-return-statements
        """Sleep MCP rollout replicas after flushing stale rollout requests.

        veRL's ``vLLMReplica.sleep()`` (and SGLang equivalent) first waits for
        requests to drain.  MCP TITO rollouts can finish and materialize all
        trajectory results while the rollout server still has a stale request
        record, which makes that drain wait spin and prevents training from
        starting.  At this point rollout is complete, so aborting any leftover
        requests is safe and keeps the old
        update_weights -> rollout -> sleep lifecycle from hanging.

        Backend coverage:
        - vLLM: ``replica.abort_all_requests()`` is implemented; this path
          aborts then sleeps.
        - SGLang: ``RolloutReplica.abort_all_requests`` is currently a no-op
          upstream (verl/workers/rollout/replica.py:234). We use ``getattr``
          duck-typing below so SGLang gracefully skips the abort step and
          goes straight to ``servers[i].sleep.remote()`` (which exists for
          both backends). Worst case: SGLang sleep waits a little longer on
          drain. If SGLang adds ``abort_all_requests`` later, this path will
          automatically pick it up.
        """
        if not getattr(self, "async_rollout_mode", False):
            return False
        if not self._rollout_free_cache_engine_enabled():
            return False
        if not bool(
            _select_with_legacy_fallback(
                self.config,
                "mcp_agent.direct_rollout_sleep_handoff",
                default=False,
            )
        ):
            return False

        manager = getattr(self, "async_rollout_manager", None)
        replicas = list(getattr(manager, "rollout_replicas", []) or [])
        if not replicas:
            replicas = list(getattr(self.checkpoint_manager, "replicas", []) or [])
        if not manager or not replicas:
            logger.info(
                "sleep_replicas after {} using checkpoint_manager fallback: "
                "async rollout manager or rollout replicas were not directly "
                "available for MCP direct sleep handoff",
                context,
            )
            return False

        rollout_backend = str(
            OmegaConf.select(
                self.config,
                "actor_rollout_ref.rollout.name",
                default="",
            )
        ).lower()
        if rollout_backend not in _ROLLOUT_FAST_PATH_BACKENDS:
            return False

        run_async = getattr(manager, "_run_async_safely", None)
        if not callable(run_async):
            logger.info(
                "sleep_replicas after {} using checkpoint_manager fallback: "
                "async rollout manager has no _run_async_safely hook",
                context,
            )
            return False

        async def abort_then_sleep() -> None:
            logger.info(
                "sleep_replicas after {} using MCP direct {} handoff for "
                "{} rollout replica(s)",
                context,
                rollout_backend,
                len(replicas),
            )
            abort_tasks = []
            for replica in replicas:
                abort = getattr(replica, "abort_all_requests", None)
                if callable(abort):
                    abort_tasks.append(abort())

            if abort_tasks:
                abort_t0 = time.monotonic()
                try:
                    abort_timeout = float(
                        OmegaConf.select(
                            self.config,
                            "mcp_agent.stale_request_abort_timeout",
                            default=2.0,
                        )
                    )
                    await asyncio.wait_for(
                        asyncio.gather(*abort_tasks, return_exceptions=True),
                        timeout=max(0.1, abort_timeout),
                    )
                    logger.info(
                        "sleep_replicas after {} aborted stale rollout "
                        "requests in {:.2f}s before rollout-server sleep",
                        context,
                        time.monotonic() - abort_t0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "sleep_replicas after {} stale-request abort timed "
                        "out after {:.2f}s; continuing to rollout-server sleep",
                        context,
                        time.monotonic() - abort_t0,
                    )

            sleep_tasks = []
            for replica in replicas:
                servers = getattr(replica, "servers", None)
                if servers:
                    for server in servers:
                        sleep_method = getattr(server, "sleep", None)
                        remote = getattr(sleep_method, "remote", None)
                        if callable(remote):
                            sleep_tasks.append(remote())
                    continue
                sleep = getattr(replica, "sleep", None)
                if callable(sleep):
                    sleep_tasks.append(sleep())

            if not sleep_tasks:
                logger.warning(
                    "sleep_replicas after {} found {} rollout replica(s) but "
                    "no sleep hooks; falling back would risk wait-drain hang",
                    context,
                    len(replicas),
                )
                return

            sleep_t0 = time.monotonic()
            await asyncio.gather(*sleep_tasks)
            logger.info(
                "sleep_replicas after {} direct rollout-server sleep "
                "completed in {:.2f}s",
                context,
                time.monotonic() - sleep_t0,
            )

        run_async(abort_then_sleep())  # pylint: disable=not-callable
        return True

    def _sleep_replicas_after_rollout(
        self,
        context: str,
        batch: DataProto | None = None,
    ) -> None:
        """Run the hybrid rollout-to-training lifecycle handoff."""
        if self._rollout_replicas_already_slept(batch):
            logger.info(
                "sleep_replicas after {} skipped; rollout replicas already "
                "slept during rollout postprocess handoff "
                "(rollout.free_cache_engine={})",
                context,
                self._rollout_free_cache_engine_enabled(),
            )
            return

        t0 = time.monotonic()
        logger.info(
            "sleep_replicas after {} starting "
            "(rollout.free_cache_engine={})",
            context,
            self._rollout_free_cache_engine_enabled(),
        )
        if not self._mcp_safe_sleep_replicas_after_rollout(context):
            self.checkpoint_manager.sleep_replicas()
        logger.info(
            "sleep_replicas after {} returned in {:.2f}s "
            "(rollout.free_cache_engine={})",
            context,
            time.monotonic() - t0,
            self._rollout_free_cache_engine_enabled(),
        )

    def _mcp_balance_rollout_batch_enabled(self) -> bool:
        """Return whether to run veRL sequence-length balancing for MCP batches.

        Opt-in by default (``mcp_agent.balance_rollout_batch=False``): MCP
        rollout already aligns row counts at the trainer boundary, so the
        veRL sequence-length reorder is a multi-GB tensor shuffle with no
        FSDP benefit unless the caller explicitly asks for it.
        """
        return bool(
            OmegaConf.select(
                self.config,
                "mcp_agent.balance_rollout_batch",
                default=False,
            )
        )

    def _hybrid_per_instance_postprocess_enabled(self) -> bool:
        """Return whether hybrid MCP rollout should postprocess per task first."""
        return bool(
            OmegaConf.select(
                self.config,
                "mcp_agent.hybrid_per_instance_postprocess",
                default=False,
            )
        )

    def _concat_rollout_dataprotos(self, output, *, context: str):
        """Convert per-instance rollout DataProtos back to one trainer batch."""
        if not isinstance(output, list):
            return output

        pad_token_id = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
        logger.info(
            "{} returned {} per-instance DataProtos; concatenating for trainer",
            context,
            len(output),
        )
        return concat_padded_dataprotos(
            output,
            pad_token_id=pad_token_id,
            context=context,
        )

    def _maybe_balance_rollout_batch(self, batch: DataProto, metrics: dict) -> None:
        """Validate DP alignment and optionally run expensive rollout reordering."""
        if not self.config.trainer.balance_batch:
            return

        dp_size = max(1, int(self.actor_dp_size))

        # Single-rank training has no cross-rank reorder to do.
        if dp_size == 1:
            metrics["balance_batch/skipped_single_dp"] = 1.0
            return

        current_bs = int(batch.batch["attention_mask"].shape[0])
        remainder = current_bs % dp_size
        if remainder != 0:
            raise ValueError(
                "Hybrid balance_batch requires batch_size % dp_size == 0, "
                "but got "
                f"batch_size={current_bs}, dp_size={dp_size}, remainder={remainder}. "
                "Pad the batch with _pad_batch_for_training upstream."
            )

        metrics["balance_batch/dp_size"] = float(dp_size)
        metrics["balance_batch/aligned_batch_size"] = float(current_bs)

        if not self._mcp_balance_rollout_batch_enabled():
            metrics["balance_batch/skipped_mcp_rollout"] = 1.0
            logger.info(
                "Skipping veRL sequence-length batch balancing for MCP rollout batch: "
                "batch_size={}, dp_size={}, alignment_unit={}. "
                "MCP already validates row-count alignment; skipping avoids "
                "GB-scale tensor reorder before FSDP training.",
                current_bs,
                dp_size,
                self.alignment_unit,
            )
            return

        _balance_t0 = time.monotonic()
        logger.info(
            "Balancing MCP rollout batch across actor data-parallel ranks "
            "(batch_size={}, dp_size={})",
            current_bs,
            dp_size,
        )
        self._balance_batch(batch, metrics=metrics)
        logger.info("Balanced rollout batch in {:.2f}s", time.monotonic() - _balance_t0)

    def init_workers(self):
        """
        Initialize distributed training workers with MCP support (Hybrid Mode).

        Creates:
        1. Actor/Rollout workers (combined in ActorRolloutRefWorker)
        2. Critic workers
        3. Reference policy workers (if using KL)
        4. Reward model workers (if enabled)
        5. MCPLoopManager for agent rollout
        """
        self.resource_pool_manager.create_resource_pool()
        self.resource_pool_to_cls = {
            pool: {} for pool in self.resource_pool_manager.resource_pool_dict.values()
        }

        logger.info("=== Initializing workers in HYBRID MODE (shared GPUs) ===")

        # Actor/Rollout worker
        if self.hybrid_engine:
            actor_rollout_resource_pool = self.resource_pool_manager.get_resource_pool(Role.ActorRollout)
            resource_pool = actor_rollout_resource_pool
            actor_rollout_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[Role.ActorRollout],
                config=self.config.actor_rollout_ref,
                role="actor_rollout",
            )
            self.resource_pool_to_cls[resource_pool]["actor_rollout"] = actor_rollout_cls
        else:
            raise NotImplementedError("Non-hybrid engine not supported. Use MCPFullyAsyncTrainer for fully async mode.")

        # Critic worker
        if self.use_critic:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.Critic)
            critic_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[Role.Critic],
                config=self.config.critic
            )
            self.resource_pool_to_cls[resource_pool]["critic"] = critic_cls

        # Reference policy worker
        if self.use_reference_policy:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.RefPolicy)
            ref_policy_cls = RayClassWithInitArgs(
                self.role_worker_mapping[Role.RefPolicy],
                config=self.config.actor_rollout_ref,
                role="ref",
            )
            self.resource_pool_to_cls[resource_pool]["ref"] = ref_policy_cls

        # Reward model worker
        if self.use_rm:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.RewardModel)
            rm_cls = RayClassWithInitArgs(
                self.role_worker_mapping[Role.RewardModel],
                config=self.config.reward_model
            )
            self.resource_pool_to_cls[resource_pool]["rm"] = rm_cls

        # Create worker groups
        all_wg = {}
        wg_kwargs = {"device_name": self.device_name}

        if OmegaConf.select(self.config.trainer, "ray_wait_register_center_timeout") is not None:
            wg_kwargs["ray_wait_register_center_timeout"] = \
                self.config.trainer.ray_wait_register_center_timeout

        for resource_pool, class_dict in self.resource_pool_to_cls.items():
            worker_dict_cls = create_colocated_worker_cls(class_dict=class_dict)
            wg_dict = self.ray_worker_group_cls(
                resource_pool=resource_pool,
                ray_cls_with_init=worker_dict_cls,
                **wg_kwargs,
            )
            spawn_wg = wg_dict.spawn(prefix_set=class_dict.keys())
            all_wg.update(spawn_wg)

        if self.use_critic:
            self.critic_wg = all_wg["critic"]
            self.critic_wg.init_model()

        if self.use_reference_policy and not self.ref_in_actor:
            self.ref_policy_wg = all_wg["ref"]
            self.ref_policy_wg.init_model()

        if self.use_rm:
            self.rm_wg = all_wg["rm"]
            self.rm_wg.init_model()

        # Initialize actor/rollout last for better inference engine memory estimation
        self.actor_rollout_wg = all_wg["actor_rollout"]
        self.actor_rollout_wg.init_model()

        # Initialize MCP Loop Manager for async rollout
        self.async_rollout_mode = self.config.actor_rollout_ref.rollout.mode == "async"
        if self.async_rollout_mode:
            self.async_rollout_manager = MCPLoopManager(
                config=self.config,
                worker_group=self.actor_rollout_wg,
                rollout_resource_pool=actor_rollout_resource_pool,
            )
            logger.info("MCPLoopManager initialized for async rollout")

        # Create CheckpointEngineManager for weight sync (FSDP <-> inference engine)
        from verl.checkpoint_engine.base import CheckpointEngineManager  # pylint: disable=no-name-in-module
        ckpt_backend = self.config.actor_rollout_ref.rollout.get("checkpoint_engine", {}).get("backend", "naive")
        self.checkpoint_manager = CheckpointEngineManager(
            backend=ckpt_backend,
            trainer=self.actor_rollout_wg,
            replicas=self.async_rollout_manager.rollout_replicas if self.async_rollout_mode else [],
        )
        # Sleep replicas initially so checkpoint loading works
        self.checkpoint_manager.sleep_replicas()

    @staticmethod
    def _get_config_value(cfg, key, default=_MISSING):
        """Read ``key`` from dict/OmegaConf/object config fragments.

        Dict and OmegaConf DictConfig support ``.get(key, default)`` directly;
        SimpleNamespace-like objects fall back to ``getattr``.
        """
        if cfg is None:
            return default
        if hasattr(cfg, "get") and callable(cfg.get):
            return cfg.get(key, default)
        return getattr(cfg, key, default)

    @staticmethod
    def _set_config_value(cfg, key, value) -> None:
        """Set ``key`` on dict/OmegaConf/object config fragments."""
        if cfg is None:
            return
        if hasattr(cfg, "__setitem__"):
            cfg[key] = value
        else:
            setattr(cfg, key, value)

    @staticmethod
    def _delete_config_value(cfg, key) -> None:
        """Delete ``key`` from dict/OmegaConf/object config fragments if present."""
        if cfg is None:
            return
        try:
            if hasattr(cfg, "__contains__") and key in cfg:
                del cfg[key]
                return
        except Exception:
            pass
        if hasattr(cfg, key):
            delattr(cfg, key)

    def _set_llm_temperature(self, value) -> None:
        """Set training LLM temperature on trainer and loop-manager configs."""
        self._set_config_value(self.config.mcp_agent.llm_config, "temperature", value)

        mgr = self.async_rollout_manager
        if mgr is None:
            return
        mcp_config = getattr(mgr, "mcp_config", None)
        llm_config = getattr(mcp_config, "llm_config", None)
        if llm_config is not None:
            self._set_config_value(llm_config, "temperature", value)
        if hasattr(mgr, "_llm_config_base"):
            mgr._llm_config_base["temperature"] = value  # pylint: disable=protected-access

    def _restore_llm_temperature(self, state: _TemperatureState) -> None:
        """Restore training LLM temperature after validation."""
        if state.had_original:
            self._set_llm_temperature(state.original)
            return

        self._delete_config_value(self.config.mcp_agent.llm_config, "temperature")
        mgr = self.async_rollout_manager
        if mgr is None:
            return
        mcp_config = getattr(mgr, "mcp_config", None)
        llm_config = getattr(mcp_config, "llm_config", None)
        if llm_config is not None:
            self._delete_config_value(llm_config, "temperature")
        if hasattr(mgr, "_llm_config_base"):
            mgr._llm_config_base.pop("temperature", None)  # pylint: disable=protected-access

    def _set_val_temperature(self):
        """Set validation temperature, return state for restore."""
        has_llm_config = (
            self.async_rollout_mode
            and hasattr(self.config, 'mcp_agent')
            and hasattr(self.config.mcp_agent, 'llm_config')
        )
        if not has_llm_config:
            return _TemperatureState(False, _MISSING, _MISSING)

        original_temp = self._get_config_value(
            self.config.mcp_agent.llm_config, "temperature", _MISSING,
        )
        val_llm_config = self._get_config_value(
            self.config.mcp_agent, "val_llm_config", None,
        )
        val_temp = self._get_config_value(
            val_llm_config, "temperature", original_temp,
        )

        state = _TemperatureState(
            had_original=original_temp is not _MISSING,
            original=original_temp,
            validation=val_temp,
        )
        if val_temp is not _MISSING and val_temp != original_temp:
            self._set_llm_temperature(val_temp)
            logger.info(
                f"Validation: Set llm_config.temperature to "
                f"{val_temp} (training: {None if original_temp is _MISSING else original_temp})"
            )
        else:
            current_temp = None if original_temp is _MISSING else original_temp
            logger.info(
                f"Validation: Using same temperature as training ({current_temp})"
            )
        return state

    def _restore_temperature(self, state: _TemperatureState):
        """Restore training temperature after validation."""
        should_restore = (
            state.validation is not _MISSING
            and state.validation != state.original
        )
        has_llm_config = (
            self.async_rollout_mode
            and hasattr(self.config, 'mcp_agent')
            and hasattr(self.config.mcp_agent, 'llm_config')
        )
        if should_restore and has_llm_config:
            self._restore_llm_temperature(state)
            restored_temp = None if state.original is _MISSING else state.original
            logger.info(
                f"Validation complete: Restored llm_config.temperature "
                f"to {restored_temp} (from validation: {state.validation})"
            )

    def _validate_batch(self, test_data, val_num_trajectories):
        """Process one validation batch.

        Returns collected scores plus requested/collected counts. Missing
        trajectories are not converted into training rows, but validation
        metrics use requested as the denominator.
        """
        if "non_tensor_batch" in test_data:
            non_tensor_batch = test_data["non_tensor_batch"]
        else:
            non_tensor_batch = test_data

        if "instruction" in non_tensor_batch:
            input_texts = non_tensor_batch["instruction"]
            if not isinstance(input_texts, list):
                input_texts = [input_texts]
        elif non_tensor_batch:
            # Use any other column to size the placeholder list. ``next(iter(...))``
            # on an empty dict raises StopIteration; ``elif`` above guards that.
            input_texts = [""] * len(next(iter(non_tensor_batch.values())))
        else:
            raise ValueError(
                "Validation batch has empty non_tensor_batch; expected at least "
                "an 'instruction' column from the MCP dataset."
            )

        input_texts_expanded = sum(
            [[t] * val_num_trajectories for t in input_texts], [],
        )

        test_gen_batch = DataProto(
            batch=None,
            non_tensor_batch={
                k: np.array(v, dtype=object) if isinstance(v, list) else v
                for k, v in non_tensor_batch.items()
            },
            meta_info={
                "eos_token_id": self.tokenizer.eos_token_id,
                "pad_token_id": self.tokenizer.pad_token_id,
                "recompute_log_prob": False,
                "do_sample": self.config.actor_rollout_ref.rollout.val_kwargs.do_sample,
                "validate": True,
                "val_mode": True,
            },
        )

        size_divisor = (
            self.actor_rollout_wg.world_size
            if not self.async_rollout_mode
            else self.config.actor_rollout_ref.rollout.get("agent", {}).get("num_workers", 1)
        )
        test_gen_batch_padded, pad_size = pad_dataproto_to_divisor(
            test_gen_batch, size_divisor,
        )

        update_t0 = time.monotonic()
        logger.info("Validation update_weights starting")
        self.checkpoint_manager.update_weights()
        logger.info(
            "Validation update_weights completed in {:.2f}s",
            time.monotonic() - update_t0,
        )
        if not self.async_rollout_mode:
            gen_t0 = time.monotonic()
            logger.info("Validation actor_rollout_wg.generate_sequences starting")
            test_output = self.actor_rollout_wg.generate_sequences(test_gen_batch_padded)
            logger.info(
                "Validation actor_rollout_wg.generate_sequences completed in {:.2f}s",
                time.monotonic() - gen_t0,
            )
            test_output = unpad_dataproto(
                test_output, pad_size=pad_size * val_num_trajectories,
            )
        else:
            gen_t0 = time.monotonic()
            logger.info("Validation async_rollout_manager.generate_sequences starting")
            if self._hybrid_per_instance_postprocess_enabled():
                logger.warning(
                    "mcp_agent.hybrid_per_instance_postprocess is ignored with "
                    "the GitHub-aligned rollout path."
                )
            test_output = self.async_rollout_manager.generate_sequences(test_gen_batch)
            logger.info(
                "Validation async_rollout_manager.generate_sequences completed in {:.2f}s",
                time.monotonic() - gen_t0,
            )
            test_output = self._concat_rollout_dataprotos(
                test_output,
                context="Validation rollout",
            )
        self._sleep_replicas_after_rollout("validation", test_output)
        logger.info("Validation generation complete")

        log_val_generations = int(
            self.config.trainer.get("log_val_generations", 0) or 0
        )
        should_decode_outputs = log_val_generations > 0
        if (
            should_decode_outputs
            and test_output.batch is not None
            and "responses" in test_output.batch
        ):
            decode_t0 = time.monotonic()
            output_texts = [
                self.tokenizer.decode(ids, skip_special_tokens=True)
                for ids in test_output.batch["responses"]
            ]
            logger.info(
                "Validation response decode completed in {:.2f}s for {} samples",
                time.monotonic() - decode_t0, len(output_texts),
            )
        else:
            output_texts = [""] * len(input_texts_expanded)

        # Expand non_tensor_batch for val_num_trajectories
        test_batch = test_output
        for key, val in test_gen_batch.non_tensor_batch.items():
            if key not in test_batch.non_tensor_batch:
                if hasattr(val, 'tolist'):
                    val = val.tolist()
                if isinstance(val, (list, np.ndarray)):
                    expanded = []
                    for v in val:
                        expanded.extend([v] * val_num_trajectories)
                    test_batch.non_tensor_batch[key] = np.array(expanded, dtype=object)
                else:
                    test_batch.non_tensor_batch[key] = val
        test_batch.meta_info["validate"] = True

        reward_t0 = time.monotonic()
        result = self.val_reward_fn(test_batch, return_dict=True)
        scores = result["reward_tensor"].sum(-1).cpu().tolist()
        logger.info(
            "Validation reward computation completed in {:.2f}s for {} samples",
            time.monotonic() - reward_t0, len(scores),
        )
        rollout_metrics = test_output.meta_info.get("rollout_metrics", {})
        num_requested = int(
            rollout_metrics.get("num_trajectories")
            or rollout_metrics.get("num_requested")
            or len(input_texts_expanded)
        )
        num_collected = int(
            rollout_metrics.get("num_collected")
            or len(scores)
        )
        num_missing = int(
            rollout_metrics.get("num_missing")
            if "num_missing" in rollout_metrics
            else max(num_requested - num_collected, 0)
        )

        turns = None
        if "__num_turns__" in test_batch.non_tensor_batch:
            turns = test_batch.non_tensor_batch["__num_turns__"]

        data_sources = None
        if "data_source" in test_gen_batch.non_tensor_batch:
            data_sources = test_gen_batch.non_tensor_batch["data_source"].copy()

        val_counts = {
            "num_requested": num_requested,
            "num_collected": num_collected,
            "num_missing": num_missing,
        }
        return input_texts_expanded, output_texts, scores, turns, data_sources, val_counts

    def _compute_val_metrics(self, sample_scores, sample_turns, data_source_lst,
                             sample_inputs, reward_extra_infos_dict,
                             validation_counts=None):
        """Compute validation metrics dict."""
        metric_dict = {}
        validation_counts = validation_counts or {}
        num_requested = validation_counts.get("num_requested")

        reward_metrics = compute_validation_reward_metrics(
            sample_scores, num_requested=num_requested, prefix="val",
        )
        if reward_metrics:
            metric_dict.update(reward_metrics)
            logger.info(
                f"[Validation] success_rate={metric_dict['val/success_rate']:.2%}, "
                f"mean_reward={metric_dict['val/mean_reward']:.4f}, "
                f"num_samples={metric_dict['val/num_samples']}, "
                f"collected={metric_dict['val/num_collected']}, "
                f"missing={metric_dict['val/num_missing']}"
            )

        data_sources = (
            np.concatenate(data_source_lst, axis=0)
            if data_source_lst else np.array([])
        )
        if data_sources.size > 0:
            data_src2var2metric2val = process_validation_metrics(
                data_sources, sample_inputs, reward_extra_infos_dict,
            )
            for data_source, var2metric2val in data_src2var2metric2val.items():
                for var_name, metric2val in var2metric2val.items():
                    for metric_name, metric_val in metric2val.items():
                        pfx = f"val/{data_source}/{var_name}/{metric_name}"
                        metric_dict[pfx] = metric_val

        if sample_turns:
            turns_arr = np.concatenate(sample_turns)
            metric_dict["val/num_turns/min"] = turns_arr.min()
            metric_dict["val/num_turns/max"] = turns_arr.max()
            metric_dict["val/num_turns/mean"] = turns_arr.mean()

        if metric_dict:
            lines = ["-" * 70, "[Validation Metrics]"]
            for k, v in sorted(metric_dict.items()):
                lines.append(
                    f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}"
                )
            lines.append("=" * 70)
            logger.info("\n{}", "\n".join(lines))

        return metric_dict

    def _validate(self, epoch: int = None):  # pylint: disable=arguments-renamed
        """Run validation on the validation dataset.

        Args:
            epoch: Current epoch number (optional, for logging)
        """
        if epoch is not None:
            logger.info(f"[Epoch {epoch}] Starting validation...")

        temperature_state = self._set_val_temperature()

        val_num_trajectories = (
            self.async_rollout_manager.val_num_trajectories
            if self.async_rollout_mode else 1
        )

        sample_inputs = []
        sample_outputs = []
        sample_scores = []
        sample_turns = []
        data_source_lst = []
        validation_counts = {
            "num_requested": 0,
            "num_collected": 0,
            "num_missing": 0,
        }
        reward_extra_infos_dict: dict[str, list] = defaultdict(list)

        for test_data in self.val_dataloader:
            inputs, outputs, scores, turns, data_sources, val_counts = self._validate_batch(
                test_data, val_num_trajectories,
            )
            sample_inputs.extend(inputs)
            sample_outputs.extend(outputs)
            sample_scores.extend(scores)
            for key in validation_counts:
                validation_counts[key] += int(val_counts.get(key, 0))
            reward_extra_infos_dict["reward"].extend(scores)
            if turns is not None:
                sample_turns.append(turns)
            if data_sources is not None:
                data_source_lst.append(data_sources)

        self._maybe_log_val_generations(
            inputs=sample_inputs, outputs=sample_outputs, scores=sample_scores,
        )
        self._print_validation_results(
            sample_inputs, sample_outputs, sample_scores,
            validation_counts=validation_counts,
        )

        metric_dict = self._compute_val_metrics(
            sample_scores, sample_turns, data_source_lst,
            sample_inputs, reward_extra_infos_dict,
            validation_counts=validation_counts,
        )

        self._restore_temperature(temperature_state)
        return metric_dict

    def _print_validation_results(
        self, sample_inputs, sample_outputs, sample_scores,
        validation_counts=None,
    ):
        """Print validation summary, with optional per-sample details."""
        logger.info("=" * 70)
        logger.info("VALIDATION RESULTS")
        logger.info("=" * 70)

        # Reward statistics
        validation_counts = validation_counts or {}
        num_requested = validation_counts.get("num_requested")
        reward_metrics = compute_validation_reward_metrics(
            sample_scores, num_requested=num_requested, prefix="val",
        )
        if reward_metrics:
            scores_arr = np.array(sample_scores) if sample_scores else np.array([])
            logger.info("[Reward Statistics]")
            logger.info(f"  Total requested: {reward_metrics['val/num_samples']}")
            logger.info(f"  Collected:        {reward_metrics['val/num_collected']}")
            logger.info(f"  Missing:          {reward_metrics['val/num_missing']}")
            logger.info(f"  Mean reward:      {reward_metrics['val/mean_reward']:.4f}")
            logger.info(f"  Success rate:     {reward_metrics['val/success_rate']:.2%}")
            if len(scores_arr) > 0:
                logger.info(f"  Collected mean:   {reward_metrics['val/mean_reward_collected']:.4f}")
                logger.info(f"  Collected std:    {scores_arr.std():.4f}")
                logger.info(f"  Collected min:    {scores_arr.min():.4f}")
                logger.info(f"  Collected max:    {scores_arr.max():.4f}")
        else:
            logger.info("[Reward Statistics]")
            logger.info("  No samples collected!")

        log_samples = bool(
            OmegaConf.select(self.config, "trainer.log_validation_samples", default=False)
        )
        if not log_samples:
            logger.info("-" * 70)
            logger.info(
                "[Per-Sample Results] skipped "
                "(set trainer.log_validation_samples=true to enable)"
            )
            logger.info("=" * 70)
            return

        sample_limit = max(0, int(
            OmegaConf.select(
                self.config,
                "trainer.log_validation_samples_limit",
                default=min(len(sample_scores), 8) if sample_scores else 0,
            )
        ))

        # Per-sample results. Keep the old visible information, but emit it as
        # one record so Ray stdout backpressure cannot stall validation for
        # seconds per sample.
        lines = ["-" * 70, "[Per-Sample Results]"]
        if sample_scores:
            for i, (inp, out, score) in enumerate(
                zip(sample_inputs, sample_outputs, sample_scores)
            ):
                if i >= sample_limit:
                    remaining = len(sample_scores) - sample_limit
                    if remaining > 0:
                        lines.append(f"  ... skipped {remaining} additional samples")
                    break
                status = "PASS" if score > 0 else "FAIL"
                inp_preview = inp[:80] + "..." if len(inp) > 80 else inp
                out_preview = out[:80] + "..." if len(out) > 80 else out
                lines.append(f"  [{i+1}] {status} reward={score:.4f}")
                lines.append(f"      Input:  {inp_preview}")
                lines.append(f"      Output: {out_preview}")
        else:
            lines.append("  No results to display")

        lines.append("=" * 70)
        logger.info("\n{}", "\n".join(lines))

    def _val_before_train(self, tracking_logger):
        """Run initial validation before training and log results."""
        if not (self.val_reward_fn is not None
                and self.config.trainer.get("val_before_train", True)):
            return False

        logger.info("=" * 70)
        logger.info("[val_before_train] Running initial validation...")
        logger.info("=" * 70)

        val_metrics = self._validate(epoch=0)
        if val_metrics:
            init_metrics = {f"init_{k}": v for k, v in val_metrics.items()}
            init_metrics["training/epoch"] = 0

            metric_lines = ["[val_before_train] Initial validation metrics:"]
            for k, v in sorted(val_metrics.items()):
                metric_lines.append(
                    f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}"
                )
            logger.info("\n{}", "\n".join(metric_lines))

            _log_t0 = time.monotonic()
            logger.info("[val_before_train] Logging initial validation metrics")
            tracking_logger.log(data=init_metrics, step=self.global_steps)
            logger.info(
                "[val_before_train] Logged prefixed validation metrics in {:.2f}s",
                time.monotonic() - _log_t0,
            )
            _log_t1 = time.monotonic()
            tracking_logger.log(data=val_metrics, step=self.global_steps)
            logger.info(
                "[val_before_train] Logged raw validation metrics in {:.2f}s",
                time.monotonic() - _log_t1,
            )

            success_rate = val_metrics.get("val/success_rate", 0)
            mean_reward = val_metrics.get("val/mean_reward", 0)
            logger.info(
                f"[val_before_train] Complete: success_rate={success_rate:.2%}, "
                f"mean_reward={mean_reward:.4f}"
            )
        else:
            logger.warning("[val_before_train] No validation metrics returned!")

        return self.config.trainer.get("val_only", False)

    def _validate_training_batch_size(
        self, batch: DataProto, metrics: dict,
    ) -> DataProto:
        """Sanity-check + filter the rollout batch for GRPO/PPO training.

        Partial GRPO groups (e.g. 5 vs 6 trajectories per prompt) are
        tolerated; only singleton groups (1 trajectory) are filtered out
        because per-group reward std is undefined on a single sample.
        Total trajectory count does not need to be a multiple of
        ``rollout_n`` or ``alignment_unit``: any shortfall is fixed up by
        ``_pad_batch_for_training`` (called from ``_generate_batch``)
        using veRL's built-in repeat-padding.

        Returns the (possibly filtered) batch; raises ``ValueError`` only
        when there is nothing left to train on (empty batch or every group
        ended up a singleton).
        """
        from collections import Counter

        current_trajectories = int(batch.batch["attention_mask"].shape[0])
        if current_trajectories <= 0:
            raise ValueError("Hybrid rollout produced an empty training batch.")

        uids = batch.non_tensor_batch.get("uid") if batch.non_tensor_batch else None
        if uids is None:
            metrics["batch_sizing/dropped_singletons"] = 0.0
            metrics["batch_sizing/dropped_singleton_trajectories"] = 0.0
        else:
            uid_list = uids.tolist() if hasattr(uids, "tolist") else list(uids)
            group_counts = Counter(uid_list)
            singletons = {gid for gid, n in group_counts.items() if n < 2}
            if singletons:
                keep_indices = [
                    i for i, uid in enumerate(uid_list) if uid not in singletons
                ]
                dropped_trajs = current_trajectories - len(keep_indices)
                singleton_preview = list(singletons)[:10]
                logger.warning(
                    "Dropping {} singleton GRPO group(s) ({} trajectories): "
                    "{}{} -- per-group reward std is undefined on 1 sample. "
                    "Remaining {} trajectories from {} groups will train.",
                    len(singletons), dropped_trajs,
                    singleton_preview,
                    "..." if len(singletons) > 10 else "",
                    len(keep_indices), len(group_counts) - len(singletons),
                )
                metrics["batch_sizing/dropped_singletons"] = float(len(singletons))
                metrics["batch_sizing/dropped_singleton_trajectories"] = float(dropped_trajs)

                if not keep_indices:
                    raise ValueError(
                        f"All {len(group_counts)} GRPO group(s) collapsed to 1 "
                        f"trajectory after rollout failures; cannot compute "
                        f"any per-group advantage. Check rollout health "
                        f"(exec_timeout, model degeneration, env failures)."
                    )

                batch = batch[keep_indices]
                # Mirror the filter on per-row meta_info lists so downstream
                # ``global_token_num``-based loss aggregation stays aligned.
                for key in ("global_token_num", "trajectory_param_versions"):
                    values = batch.meta_info.get(key)
                    if isinstance(values, list) and len(values) == current_trajectories:
                        batch.meta_info[key] = [values[i] for i in keep_indices]

                # Recompute group stats post-filter for downstream metrics.
                uid_list = [uid_list[i] for i in keep_indices]
                group_counts = Counter(uid_list)
                current_trajectories = len(keep_indices)
            else:
                metrics["batch_sizing/dropped_singletons"] = 0.0
                metrics["batch_sizing/dropped_singleton_trajectories"] = 0.0

            metrics["batch_sizing/num_groups"] = float(len(group_counts))
            metrics["batch_sizing/min_group_size"] = float(min(group_counts.values()))
            metrics["batch_sizing/max_group_size"] = float(max(group_counts.values()))

        expected = self.global_trajectory_minibatch
        metrics["batch_sizing/collected_trajectories"] = float(current_trajectories)
        metrics["batch_sizing/expected_trajectories"] = float(expected)
        metrics["batch_sizing/num_missing"] = float(max(0, expected - current_trajectories))
        metrics["batch_sizing/global_trajectory_minibatch"] = self.global_trajectory_minibatch
        metrics["batch_sizing/local_actor_minibatch"] = self.local_actor_minibatch
        metrics["batch_sizing/alignment_unit"] = self.alignment_unit
        return batch

    def _pad_batch_for_training(self, batch: DataProto, metrics: dict) -> DataProto:
        """Pad batch to ``global_trajectory_minibatch`` using veRL's repeat-pad.

        Hybrid Megatron is double-strict about batch sizing:

        1. ``dispatch_nd_compute_dataproto`` calls
           ``data.chunk(chunks=dp_size)`` (the **strict** variant - see
           ``verl/single_controller/base/decorator.py:_split_args_kwargs_data_proto``)
           and asserts ``batch_size % dp_size == 0``. A shortfall here
           crashes before the optimizer step.
        2. Inside each rank, ``megatron_actor.make_minibatch_iterator``
           calls ``data.make_iterator(mini_batch_size=ppo_mini_batch_size)``
           (see ``verl/protocol.py:make_iterator``) which asserts
           ``local_batch % per_rank_mini_batch == 0``.

        Padding to ``global_trajectory_minibatch`` (= prompt_mini *
        rollout_n) satisfies both constraints because
        ``MCPBatchSizing`` validates ``global_trajectory_minibatch %
        dp_size == 0`` at trainer init.

        Why pad instead of trim: when rollout collects fewer than one
        full mini-batch (e.g. 358/360), trimming to a multiple of
        ``global_trajectory_minibatch`` yields zero usable trajectories.
        ``pad_dataproto_to_divisor`` uses **repeat-padding** - it copies
        the first ``pad_size`` real trajectories to the tail (see
        ``verl/protocol.py:pad_dataproto_to_divisor``). The repeated
        samples contribute 2x gradient weight; for a typical 358-of-360
        shortfall this is a 0.56% per-step bias, far below PPO's
        intrinsic gradient noise.
        """
        divisor = max(1, int(self.global_trajectory_minibatch))
        current = int(batch.batch["attention_mask"].shape[0])
        if current <= 0:
            raise ValueError("Hybrid rollout produced an empty training batch.")

        metrics["batch_sizing/collected_trajectories"] = float(current)
        if current % divisor == 0:
            metrics["batch_sizing/pad_size"] = 0.0
            metrics["batch_sizing/aligned_trajectories"] = float(current)
            metrics["batch_sizing/pad_ratio"] = 0.0
            return batch

        batch_padded, pad_size = pad_dataproto_to_divisor(batch, divisor)
        new_size = int(batch_padded.batch["attention_mask"].shape[0])
        pad_ratio = float(pad_size) / float(new_size)

        metrics["batch_sizing/aligned_trajectories"] = float(new_size)
        metrics["batch_sizing/pad_size"] = float(pad_size)
        metrics["batch_sizing/pad_ratio"] = pad_ratio

        # Guard: if rollout massively under-collected (e.g. system-wide failure
        # left us with 100 of 360 trajectories), pad-by-repeat would assign
        # every real sample a 3-4x gradient weight and the step would be
        # dominated by a handful of trajectories. Abort instead of polluting
        # the optimizer.
        if pad_ratio > self._max_pad_ratio:
            metrics["batch_sizing/skipped_excessive_pad"] = 1.0
            raise ExcessivePaddingException(
                pad_size=pad_size, batch_size=new_size, threshold=self._max_pad_ratio,
            )

        for key in ("global_token_num", "trajectory_param_versions"):
            values = batch_padded.meta_info.get(key)
            if isinstance(values, list) and 0 < len(values) < new_size:
                pad_values = [values[i % len(values)] for i in range(new_size - len(values))]
                batch_padded.meta_info[key] = list(values) + pad_values

        logger.warning(
            "Padded hybrid rollout batch from {} to {} trajectories "
            "(pad_size={}, ratio={:.3f}, threshold={:.3f}, repeats first "
            "{} sample(s)) to satisfy global_trajectory_minibatch={} "
            "alignment. Padded entries are real trajectories duplicated "
            "from the start (not zero-pad); they contribute 2x gradient "
            "weight.",
            current, new_size, pad_size, pad_ratio, self._max_pad_ratio,
            pad_size, divisor,
        )
        return batch_padded

    def _generate_batch(self, gen_batch, metrics, timing_raw):
        """Generate trajectories and compute rewards/advantages. Returns batch."""
        with marked_timer("gen", timing_raw, color="red"):
            update_t0 = time.monotonic()
            logger.info("Training update_weights starting")
            self.checkpoint_manager.update_weights()
            logger.info(
                "Training update_weights completed in {:.2f}s",
                time.monotonic() - update_t0,
            )
            if not self.async_rollout_mode:
                gen_t0 = time.monotonic()
                logger.info("Training actor_rollout_wg.generate_sequences starting")
                batch = self.actor_rollout_wg.generate_sequences(gen_batch)
                logger.info(
                    "Training actor_rollout_wg.generate_sequences completed in {:.2f}s",
                    time.monotonic() - gen_t0,
                )
            else:
                gen_t0 = time.monotonic()
                logger.info("Training async_rollout_manager.generate_sequences starting")
                if self._hybrid_per_instance_postprocess_enabled():
                    logger.warning(
                        "mcp_agent.hybrid_per_instance_postprocess is ignored with "
                        "the GitHub-aligned rollout path."
                    )
                batch = self.async_rollout_manager.generate_sequences(gen_batch)
                logger.info(
                    "Training async_rollout_manager.generate_sequences completed in {:.2f}s",
                    time.monotonic() - gen_t0,
                )
                batch = self._concat_rollout_dataprotos(
                    batch,
                    context="Training rollout",
                )
            self._sleep_replicas_after_rollout("training rollout", batch)

            timing_raw.update(batch.meta_info.get("timing", {}))
            if "rollout_metrics" in batch.meta_info:
                rollout_metrics = reduce_metrics(batch.meta_info["rollout_metrics"])
                metrics.update(rollout_metrics)
                logger.info(f"Rollout metrics: {rollout_metrics}")

        batch_size = len(batch.batch) if batch.batch is not None else 0
        logger.info(f"Batch size after rollout: {batch_size}")

        if "response_mask" not in batch.batch:
            _mask_t0 = time.monotonic()
            logger.info("Computing response_mask for rollout batch")
            batch.batch["response_mask"] = compute_response_mask(batch)
            logger.info("Computed response_mask in {:.2f}s", time.monotonic() - _mask_t0)
        else:
            logger.info("Using response_mask from rollout postprocess")

        _validate_t0 = time.monotonic()
        logger.info("Validating training batch size")
        batch = self._validate_training_batch_size(batch, metrics)
        logger.info("Validated training batch size in {:.2f}s", time.monotonic() - _validate_t0)

        # Pad batch up to one full ``global_trajectory_minibatch`` so veRL's
        # strict Megatron dispatch (``data.chunk(dp_size)``) and per-rank
        # ``make_iterator(ppo_mini_batch_size)`` both succeed. Tolerates the
        # common case where rollout drops a few trajectories due to per-
        # trajectory init/exec failures (e.g. 358 collected vs 360 expected
        # with rollout_n=6); we repeat-pad the tail instead of crashing.
        batch = self._pad_batch_for_training(batch, metrics)

        self._maybe_balance_rollout_batch(batch, metrics)

        if "global_token_num" not in batch.meta_info:
            _token_num_t0 = time.monotonic()
            logger.info("Computing global_token_num for rollout batch")
            batch.meta_info["global_token_num"] = torch.sum(
                batch.batch["attention_mask"], dim=-1,
            ).tolist()
            logger.info("Computed global_token_num in {:.2f}s", time.monotonic() - _token_num_t0)
        else:
            logger.info("Using global_token_num from rollout postprocess")
        return batch

    def _compute_training_signals(self, batch, metrics, timing_raw):
        """Compute rewards, log probs, values, and advantages."""
        logger.info("Computing training signals")
        with marked_timer("reward", timing_raw, color="yellow"):
            _reward_t0 = time.monotonic()
            logger.info("Computing reward tensor")
            if self.use_rm:
                reward_tensor = self.rm_wg.compute_rm_score(batch)
                batch = batch.union(reward_tensor)
            if "rm_scores" not in batch.batch:
                batch.batch["rm_scores"] = self.reward_fn(batch)
            reward_tensor, reward_extra_info = extract_reward(batch)
            logger.info("Computed reward tensor in {:.2f}s", time.monotonic() - _reward_t0)

        with marked_timer("old_log_prob", timing_raw, color="blue"):
            _old_log_prob_t0 = time.monotonic()
            logger.info("Computing old_log_prob")
            old_log_prob = self.actor_rollout_wg.compute_log_prob(batch)
            pop_entropy_metric_if_present(
                old_log_prob=old_log_prob,
                batch=batch,
                actor_config=self.config.actor_rollout_ref.actor,
                metrics=metrics,
                agg_loss=agg_loss,
            )
            batch = batch.union(old_log_prob)
            logger.info("Computed old_log_prob in {:.2f}s", time.monotonic() - _old_log_prob_t0)

        if self.use_reference_policy:
            with marked_timer("ref", timing_raw, color="olive"):
                _ref_t0 = time.monotonic()
                logger.info("Computing reference log_prob")
                if not self.ref_in_actor:
                    ref_log_prob = self.ref_policy_wg.compute_ref_log_prob(batch)
                else:
                    ref_log_prob = self.actor_rollout_wg.compute_ref_log_prob(batch)
                batch = batch.union(ref_log_prob)
                logger.info("Computed reference log_prob in {:.2f}s", time.monotonic() - _ref_t0)

        if self.use_critic:
            with marked_timer("values", timing_raw, color="cyan"):
                _values_t0 = time.monotonic()
                logger.info("Computing critic values")
                values = self.critic_wg.compute_values(batch)
                batch = batch.union(values)
                logger.info("Computed critic values in {:.2f}s", time.monotonic() - _values_t0)

        with marked_timer("adv", timing_raw, color="brown"):
            _adv_t0 = time.monotonic()
            logger.info("Computing advantages")
            batch.batch["token_level_scores"] = reward_tensor
            if reward_extra_info:
                batch.non_tensor_batch.update({
                    k: np.array(v) for k, v in reward_extra_info.items()
                })
            if self.config.algorithm.use_kl_in_reward:
                batch, kl_metrics = self._apply_kl_penalty(batch)
                metrics.update(kl_metrics)
            else:
                batch.batch["token_level_rewards"] = batch.batch["token_level_scores"]

            adv_estimator = self.config.algorithm.adv_estimator.upper()
            n = self.config.actor_rollout_ref.rollout.get("n", 1)
            num_repeat = n if adv_estimator in ["GRPO", "RLOO"] else 1
            batch = compute_advantage(
                batch,
                adv_estimator=self.config.algorithm.adv_estimator,
                gamma=self.config.algorithm.gamma,
                lam=self.config.algorithm.lam,
                num_repeat=num_repeat,
                config=self.config.algorithm,
            )
            logger.info("Computed advantages in {:.2f}s", time.monotonic() - _adv_t0)

        return batch

    def _update_models(self, batch, metrics, timing_raw):
        """Update critic and actor models."""
        if self.use_critic:
            with marked_timer("update_critic", timing_raw, color="pink"):
                _critic_t0 = time.monotonic()
                logger.info("Updating critic")
                critic_output = self.critic_wg.update_critic(batch)
                logger.info("Updated critic in {:.2f}s", time.monotonic() - _critic_t0)
            metrics.update(reduce_metrics(critic_output.meta_info["metrics"]))

        if self.config.trainer.critic_warmup <= self.global_steps:
            with marked_timer("update_actor", timing_raw, color="red"):
                _actor_t0 = time.monotonic()
                logger.info("Updating actor")
                batch.meta_info["multi_turn"] = (
                    self.config.actor_rollout_ref.rollout
                    .get("multi_turn", {}).get("enable", False)
                )
                actor_output = self.actor_rollout_wg.update_actor(batch)
                logger.info("Updated actor in {:.2f}s", time.monotonic() - _actor_t0)
            metrics.update(reduce_metrics(actor_output.meta_info["metrics"]))

    def _maybe_validate_and_save(self, _batch, metrics, timing_raw, is_last_step):
        """Run validation and save checkpoint if conditions are met."""
        if (
            self.val_reward_fn is not None
            and self.config.trainer.test_freq > 0
            and (is_last_step or self.global_steps % self.config.trainer.test_freq == 0)
        ):
            with marked_timer("testing", timing_raw, color="green"):
                val_metrics = self._validate()
            metrics.update(val_metrics)

        if (
            self.config.trainer.save_freq > 0
            and (
                is_last_step
                or self.global_steps % self.config.trainer.save_freq == 0
                or should_save_ckpt_esi(
                    max_steps_duration=self.max_steps_duration,
                    redundant_time=self.config.trainer.esi_redundant_time,
                )
            )
        ):
            with marked_timer("save_checkpoint", timing_raw, color="green"):
                self._save_checkpoint()

    def _shutdown_async_rollout_manager(self):
        """Explicitly release MCP rollout resources owned by this trainer."""
        manager = getattr(self, "async_rollout_manager", None)
        if manager is None:
            return
        shutdown = getattr(manager, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()  # pylint: disable=not-callable
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to shutdown MCPLoopManager: {}", exc)

    def fit(self):
        """Main training loop for MCP PPO."""
        tracking_logger = Tracking(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
            default_backend=self.config.trainer.logger,
            config=OmegaConf.to_container(self.config, resolve=True),
        )
        _wrap_slow_tracking_backends(tracking_logger, self.config)

        self.global_steps = 0
        self._load_checkpoint()

        if self._val_before_train(tracking_logger):
            self._shutdown_async_rollout_manager()
            return

        logger.info("Starting MCP PPO training loop: total_steps={}", self.total_training_steps)
        progress_bar = tqdm(
            total=self.total_training_steps,
            initial=self.global_steps,
            desc="MCP PPO Training",
        )

        self.global_steps += 1
        self.max_steps_duration = 0

        for epoch in range(self.config.trainer.total_epochs):
            _epoch_iter_t0 = time.monotonic()
            logger.info("[Epoch {}] Creating train dataloader iterator", epoch)
            train_dataloader_iter = iter(self.train_dataloader)
            logger.info(
                "[Epoch {}] Train dataloader iterator ready in {:.2f}s",
                epoch, time.monotonic() - _epoch_iter_t0,
            )

            for batch_dict in train_dataloader_iter:
                logger.info("[Step {}] Received training dataloader batch", self.global_steps)
                metrics = {}
                timing_raw = {}

                non_tensor_batch = (
                    batch_dict["non_tensor_batch"]
                    if "non_tensor_batch" in batch_dict
                    else batch_dict
                )

                gen_batch = DataProto(
                    batch=None,
                    non_tensor_batch={
                        k: np.array(v, dtype=object) if isinstance(v, list) else v
                        for k, v in non_tensor_batch.items()
                    },
                    meta_info={
                        "eos_token_id": self.tokenizer.eos_token_id,
                        "pad_token_id": self.tokenizer.pad_token_id,
                        "global_steps": self.global_steps,
                    },
                )

                if self.global_steps == 1:
                    instructions = non_tensor_batch.get("instruction", [])
                    if instructions:
                        logger.info(f"Sample prompts: {instructions[:2]}")

                is_last_step = self.global_steps >= self.total_training_steps

                try:
                    with marked_timer("step", timing_raw):
                        batch = self._generate_batch(gen_batch, metrics, timing_raw)
                        batch = self._compute_training_signals(batch, metrics, timing_raw)
                        self._update_models(batch, metrics, timing_raw)
                        self._maybe_validate_and_save(batch, metrics, timing_raw, is_last_step)
                except ExcessivePaddingException as exc:
                    # Rollout under-collected so badly that pad-by-repeat
                    # would dominate the gradient with duplicate samples.
                    # Drop this step's compute (rollout already happened),
                    # log diagnostics, and let the next dataloader batch
                    # try again with fresh prompts.
                    metrics["batch_sizing/skipped_excessive_pad"] = 1.0
                    metrics["batch_sizing/skipped_pad_ratio"] = float(exc.pad_ratio)
                    metrics["batch_sizing/skipped_pad_size"] = float(exc.pad_size)
                    metrics["batch_sizing/skipped_pad_threshold"] = float(exc.threshold)
                    logger.warning(
                        "Skipping PPO step {} due to excessive padding: {}. "
                        "Advancing to next dataloader batch.",
                        self.global_steps, exc,
                    )
                    tracking_logger.log(data=metrics, step=self.global_steps)
                    progress_bar.update(1)
                    self.global_steps += 1
                    if is_last_step:
                        progress_bar.close()
                        self._shutdown_async_rollout_manager()
                        return
                    continue

                steps_duration = timing_raw.get("step", 0)
                self.max_steps_duration = max(self.max_steps_duration, steps_duration)

                metrics.update({
                    "training/global_step": self.global_steps,
                    "training/epoch": epoch,
                })
                metrics.update(compute_data_metrics(batch=batch, use_critic=self.use_critic))
                metrics.update(compute_timing_metrics(batch=batch, timing_raw=timing_raw))

                n_gpus = self.resource_pool_manager.get_n_gpus()
                metrics.update(compute_throughout_metrics(
                    batch=batch, timing_raw=timing_raw, n_gpus=n_gpus,
                ))

                tracking_logger.log(data=metrics, step=self.global_steps)

                progress_bar.update(1)
                self.global_steps += 1

                if is_last_step:
                    progress_bar.close()
                    self._shutdown_async_rollout_manager()
                    return

            # End of Epoch Validation
            if self.val_reward_fn is not None:
                logger.info("=" * 70)
                logger.info(
                    f"[Epoch {epoch + 1}/{self.config.trainer.total_epochs}] "
                    "Running end-of-epoch validation..."
                )
                logger.info("=" * 70)

                with marked_timer("epoch_validation", {}):
                    epoch_val_metrics = self._validate(epoch=epoch + 1)

                if epoch_val_metrics:
                    epoch_metrics = {
                        f"epoch_{k}": v for k, v in epoch_val_metrics.items()
                    }
                    epoch_metrics["training/epoch"] = epoch + 1
                    tracking_logger.log(data=epoch_metrics, step=self.global_steps)

                    success_rate = epoch_val_metrics.get("val/success_rate", 0)
                    mean_reward = epoch_val_metrics.get("val/mean_reward", 0)
                    logger.info(
                        f"[Epoch {epoch + 1}] Validation complete: "
                        f"success_rate={success_rate:.2%}, "
                        f"mean_reward={mean_reward:.4f}"
                    )

        self._shutdown_async_rollout_manager()

    def _apply_kl_penalty(self, batch: DataProto) -> tuple:
        """Apply KL penalty to rewards."""
        from verl.trainer.ppo.core_algos import kl_penalty  # pylint: disable=import-outside-toplevel

        old_log_probs = batch.batch["old_log_probs"]
        ref_log_probs = batch.batch["ref_log_probs"]
        response_mask = batch.batch["response_mask"]

        kl = old_log_probs - ref_log_probs
        kl_reward = kl_penalty(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
            kl,
            kl_ctrl=self.kl_ctrl_in_reward,
            kl_penalty=self.config.algorithm.kl_penalty,
        )

        batch.batch["token_level_rewards"] = batch.batch["token_level_scores"] - kl_reward

        kl_masked = kl * response_mask
        kl_mean = kl_masked.sum() / response_mask.sum()

        return batch, {"kl/mean": kl_mean.item()}
