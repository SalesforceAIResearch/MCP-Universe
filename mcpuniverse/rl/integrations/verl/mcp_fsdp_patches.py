"""FSDP runtime monkey-patches for MCP training.

Currently houses the cross-DP ``num_micro_batches`` sync fix that veRL's
FSDP path forgets to enable. See ``_patch_fsdp_dynamic_bsz_sync`` for
the full rationale; in short, without this patch
``actor.use_dynamic_bsz=true`` deadlocks on multi-DP FSDP runs because
different DP ranks enqueue different counts of per-layer all-gather
collectives during ``compute_log_prob`` / ``update_policy``.

Mirrors the structure of ``mcp_megatron_patches``: idempotent flags,
lazy imports inside the patch function so importing this module never
costs the heavy ``verl.workers.actor.dp_actor`` import for callers who
don't need it.
"""

import logging
import os
from typing import Optional

import torch.distributed as dist

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "INFO"))


_MCP_FSDP_DYNAMIC_BSZ_PATCHED = False
_MCP_FSDP_DP_GROUP: Optional[dist.ProcessGroup] = None


def set_fsdp_dp_group(group: Optional[dist.ProcessGroup]) -> None:
    """Stash the FSDP data-parallel process group for later use.

    The patched ``prepare_dynamic_batch`` calls this group's all-reduce to
    make every DP rank pick the same ``num_micro_batches`` (MAX across
    ranks). Worker classes set this once they finish building their
    ``ulysses_device_mesh`` / ``device_mesh`` (i.e. after ``init_model``).
    ``None`` is allowed - the patched function falls back to
    ``dist.group.WORLD`` so single-node / no-SP runs still get sync.
    """
    global _MCP_FSDP_DP_GROUP  # pylint: disable=global-statement
    _MCP_FSDP_DP_GROUP = group


def _patch_fsdp_dynamic_bsz_sync() -> None:
    """Replace ``dp_actor.prepare_dynamic_batch`` with a DP-syncing wrapper.

    veRL bug being fixed:
        ``verl/workers/actor/dp_actor.py`` calls
        ``prepare_dynamic_batch(data, max_token_len=...)`` from both
        ``compute_log_prob`` (line ~468) and ``update_policy``
        (line ~560), **without** passing ``dp_group``.
        ``prepare_dynamic_batch`` has built-in cross-DP sync that
        all-reduces ``num_micro_batches`` (MAX op) when ``dp_group`` is
        provided - but it's a no-op when ``dp_group is None``
        (see ``verl/utils/seqlen_balancing.py:rearrange_micro_batches``,
        lines around 391-394).

    Failure mode without sync:
        Each DP rank computes ``num_micro_batches`` from its local token
        count, so DP ranks with shorter sequences get fewer micro-batches.
        FSDP forward triggers per-layer all-gather of sharded params,
        which is a DP-group NCCL collective. Different counts of
        micro-batches -> different counts of all-gather collectives ->
        cross-rank deadlock -> NCCL watchdog timeout 10 min later.

    Why Megatron doesn't hit this:
        Megatron's forward uses PP/TP/EP groups, not the DP group.
        DP-group collectives only happen at step-end gradient all-reduce
        (which runs once after all micro-batches per rank), so different
        micro-batch counts are tolerated.

    Patch mechanism:
        Replace the imported ``prepare_dynamic_batch`` symbol *inside*
        ``verl.workers.actor.dp_actor``'s namespace with a thin wrapper
        that auto-injects ``dp_group=_MCP_FSDP_DP_GROUP`` (or
        ``dist.group.WORLD`` fallback). Other modules that import
        ``prepare_dynamic_batch`` directly are untouched.

    The patch is idempotent (early-return after first apply) and safe to
    call from every ``compute_log_prob`` invocation. Megatron is **not**
    patched here - see ``mcp_megatron_patches`` for that family.
    """
    global _MCP_FSDP_DYNAMIC_BSZ_PATCHED  # pylint: disable=global-statement
    if _MCP_FSDP_DYNAMIC_BSZ_PATCHED:
        return

    # Lazy import so this module doesn't pay verl's heavy FSDP import cost
    # for callers that only want set_fsdp_dp_group().
    import verl.workers.actor.dp_actor as dp_actor_mod  # pylint: disable=import-outside-toplevel
    from verl.utils.seqlen_balancing import prepare_dynamic_batch as original  # pylint: disable=import-outside-toplevel

    current = getattr(dp_actor_mod, "prepare_dynamic_batch", None)
    if (
        current is not None
        and getattr(current, "__name__", "") == "_mcp_prepare_dynamic_batch_with_dp_sync"
    ):
        _MCP_FSDP_DYNAMIC_BSZ_PATCHED = True
        return

    def _mcp_prepare_dynamic_batch_with_dp_sync(
        data, max_token_len, dp_group=None, **kwargs,
    ):
        if dp_group is None:
            dp_group = _MCP_FSDP_DP_GROUP
            if dp_group is None and dist.is_initialized():
                # Fallback: WORLD group. Correct for runs without Ulysses
                # sequence parallel; for SP>1 this over-syncs across SP
                # ranks too, which is wasteful but harmless (all SP ranks
                # process the same data anyway).
                dp_group = dist.group.WORLD
        return original(data, max_token_len=max_token_len, dp_group=dp_group, **kwargs)

    dp_actor_mod.prepare_dynamic_batch = _mcp_prepare_dynamic_batch_with_dp_sync
    _MCP_FSDP_DYNAMIC_BSZ_PATCHED = True
    logger.info(
        "[MCPFSDP] patched dp_actor.prepare_dynamic_batch to enable cross-DP "
        "num_micro_batches sync (fixes multi-DP NCCL hang with use_dynamic_bsz)",
    )


def stash_fsdp_dp_group_from_worker(worker) -> None:
    """Best-effort: hand the worker's FSDP DP group to ``set_fsdp_dp_group``.

    Call this from each ``compute_log_prob`` / ``update_actor`` entry path
    so the patched ``prepare_dynamic_batch`` has the correct group to
    all-reduce ``num_micro_batches`` on. Failures are swallowed because the
    patch falls back to ``WORLD`` if no group has been stashed.

    Resolution order (first that works wins):
    1. ``worker.ulysses_device_mesh["dp"].get_group()`` -- when Ulysses
       sequence parallel is enabled, this is the *pure* DP group (already
       factored out of the SP dimension), which is exactly what
       ``prepare_dynamic_batch`` wants.
    2. ``worker.device_mesh.get_group()`` -- fallback when SP is not in
       use; for plain FSDP this collapses to the DP group anyway.

    Used by both hybrid (``hybrid/mcp_workers.py``) and fully-async
    (``fully_async/mcp_async_workers.py``) FSDP worker classes; sharing
    the helper here avoids cross-package imports.
    """
    ulysses_mesh = getattr(worker, "ulysses_device_mesh", None)
    if ulysses_mesh is not None:
        try:
            set_fsdp_dp_group(ulysses_mesh["dp"].get_group())
            return
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    device_mesh = getattr(worker, "device_mesh", None)
    if device_mesh is not None:
        try:
            set_fsdp_dp_group(device_mesh.get_group())
            return
        except Exception:  # pylint: disable=broad-exception-caught
            pass
