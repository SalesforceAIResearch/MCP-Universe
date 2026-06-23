"""Hybrid veRL worker subclasses used by MCP training."""

import os
import socket
import time

import torch
import torch.distributed as dist

from verl.single_controller.base.decorator import make_nd_compute_dataproto_dispatch_fn, register
from verl.workers.fsdp_workers import (
    ActorRolloutRefWorker as FSDPActorRolloutRefWorker,
    AsyncActorRolloutRefWorker as FSDPAsyncActorRolloutRefWorker,
)

from ..mcp_log_prob_entropy import (
    fsdp_compute_log_prob_without_entropy,
    megatron_compute_log_prob_without_entropy,
    should_skip_entropy_for_log_prob,
)

try:
    from verl.workers.megatron_workers import (
        ActorRolloutRefWorker as MegatronActorRolloutRefWorker,
        AsyncActorRolloutRefWorker as MegatronAsyncActorRolloutRefWorker,
    )
except ImportError:  # pragma: no cover - only needed in Megatron-capable envs.
    MegatronActorRolloutRefWorker = None
    MegatronAsyncActorRolloutRefWorker = None

# Patch helpers shared with the fully-async workers. ``_stash_fsdp_dp_group_from_worker``
# is also re-exported here for backwards compatibility with historical imports.
from ..mcp_fsdp_patches import (
    _patch_fsdp_dynamic_bsz_sync,
    stash_fsdp_dp_group_from_worker as _stash_fsdp_dp_group_from_worker,
)
from ..mcp_megatron_patches import _patch_megatron_vocab_parallel_entropy_for_memory


def _log_prob_diag_enabled() -> bool:
    """Return whether to print per-rank ENTER/EXIT diagnostics.

    Default-on so we always have a record of which rank reached
    ``compute_log_prob`` and which one didn't, paired with the NCCL flight
    recorder dump on timeout. Set ``MCP_LOG_PROB_DIAG=0`` to silence once we
    no longer need it.
    """
    return os.environ.get("MCP_LOG_PROB_DIAG", "1") not in ("0", "false", "False", "")


def _emit_log_prob_diag(stage: str, data, t0: float | None = None) -> float:
    """Print a single-line diag with rank + host + batch + elapsed.

    Uses ``print(..., flush=True)`` instead of ``logger`` so the line
    survives stdout/log buffering when the rank later hangs in a NCCL
    collective and the process is eventually SIGABRT-ed by the watchdog.
    """
    if not _log_prob_diag_enabled():
        return time.monotonic()
    try:
        rank = dist.get_rank() if dist.is_initialized() else -1
    except Exception:  # pylint: disable=broad-exception-caught
        rank = -1
    host = socket.gethostname()
    pid = os.getpid()
    batch_size = -1
    try:
        if hasattr(data, "batch") and data.batch is not None:
            batch_size = int(data.batch.batch_size[0])
        elif hasattr(data, "__len__"):
            batch_size = len(data)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    cuda_gb = -1.0
    try:
        if torch.cuda.is_available():
            cuda_gb = torch.cuda.memory_allocated() / (1024 ** 3)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    now = time.monotonic()
    elapsed = "" if t0 is None else f" elapsed={now - t0:.2f}s"
    print(
        f"[MCP-LOG-PROB-DIAG] {stage} rank={rank} host={host} pid={pid} "
        f"batch={batch_size} cuda_alloc={cuda_gb:.2f}GiB t={now:.3f}{elapsed}",
        flush=True,
    )
    return now


class _MCPFSDPLogProbMixin:  # pylint: disable=too-few-public-methods
    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def compute_log_prob(self, data):
        """Compute log-probs with the FSDP cross-DP num_micro_batches sync patch.

        Patches verl's ``dp_actor.prepare_dynamic_batch`` to all-reduce
        ``num_micro_batches`` across DP ranks before slicing; without it,
        ``use_dynamic_bsz`` on multi-DP FSDP deadlocks because each rank
        enqueues a different count of per-layer all-gather collectives. The
        patch is idempotent + cheap (early-return after first apply).
        """
        _patch_fsdp_dynamic_bsz_sync()
        _stash_fsdp_dp_group_from_worker(self)

        t0 = _emit_log_prob_diag("ENTER", data)
        try:
            if should_skip_entropy_for_log_prob(self.config.actor):
                return fsdp_compute_log_prob_without_entropy(self, data)
            return super().compute_log_prob(data)
        finally:
            _emit_log_prob_diag("EXIT", data, t0=t0)


class _MCPMegatronLogProbMixin:  # pylint: disable=too-few-public-methods
    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def compute_log_prob(self, data):
        """Compute log-probs with the Megatron vocab-parallel entropy memory patch."""
        _patch_megatron_vocab_parallel_entropy_for_memory()
        t0 = _emit_log_prob_diag("ENTER", data)
        try:
            if should_skip_entropy_for_log_prob(self.config.actor):
                return megatron_compute_log_prob_without_entropy(self, data)
            return super().compute_log_prob(data)
        finally:
            _emit_log_prob_diag("EXIT", data, t0=t0)


class MCPHybridFSDPActorRolloutRefWorker(_MCPFSDPLogProbMixin, FSDPActorRolloutRefWorker):
    """FSDP actor/rollout/ref worker with the MCP log-prob entropy override."""


class MCPHybridFSDPAsyncActorRolloutRefWorker(_MCPFSDPLogProbMixin, FSDPAsyncActorRolloutRefWorker):
    """Async FSDP actor/rollout/ref worker with the MCP log-prob entropy override."""


if MegatronActorRolloutRefWorker is not None:

    class MCPHybridMegatronActorRolloutRefWorker(_MCPMegatronLogProbMixin, MegatronActorRolloutRefWorker):
        """Megatron actor/rollout/ref worker with the MCP log-prob entropy override."""

    class MCPHybridMegatronAsyncActorRolloutRefWorker(  # pylint: disable=too-many-ancestors
        _MCPMegatronLogProbMixin, MegatronAsyncActorRolloutRefWorker
    ):
        """Async Megatron actor/rollout/ref worker with the MCP log-prob entropy override."""
