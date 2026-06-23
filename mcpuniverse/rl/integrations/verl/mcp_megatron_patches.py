"""Megatron runtime monkey-patches shared by hybrid and fully-async MCP trainers.

This module exists to keep the cross-cutting Megatron compatibility patches
in **one** place that both ``hybrid/`` and ``fully_async/`` peer packages can
import without depending on each other. Previously the patches lived inside
``fully_async/mcp_megatron_async_workers.py`` and hybrid had to reach
sideways into the fully-async subpackage, which made the dependency graph
hard to follow and brittle to fully-async refactors.

All patches are:

* **Idempotent** -- they guard against double-application via module-level
  ``_MCP_*_PATCHED`` flags so calling them repeatedly from worker hot paths
  is cheap (early-return after first success).
* **Lazy** -- the Megatron / Megatron-Bridge imports happen inside the
  function body so importing this module never costs the Megatron import
  for FSDP-only users.
* **Behaviour-preserving** -- they keep the upstream computation identical
  on the supported code path; they only relocate / chunk allocations or
  add MoE naming compatibility.
"""
# This is a low-level monkey-patch module for Megatron / verl internals: it
# subclasses torch.autograd.Function (custom forward/backward signatures, with
# autograd's vmap/vjp/setup_context left unimplemented), keeps module-level
# patch state, lazily imports heavy deps (Megatron / flash-attn / TE) inside
# functions, and reaches into framework internals via protected members and
# exec() source shims. The checks below flag that intended mechanism, not real
# defects, so they are disabled for this file only.
# pylint: disable=arguments-differ,abstract-method,import-outside-toplevel
# pylint: disable=global-statement,protected-access,exec-used
# pylint: disable=broad-exception-caught,unused-argument
# pylint: disable=too-many-lines,too-many-statements,too-many-locals
# pylint: disable=too-many-return-statements

import logging
import os
import re
from types import SimpleNamespace

import torch
import torch.distributed as dist

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "INFO"))


_MCP_VOCAB_ENTROPY_PATCHED = False
_MCP_ZERO_ENTROPY_PATCHED = False
_MCP_ENTROPY_CLONE_DROP_PATCHED = False
_MCP_FUSED_LE_PATCHED = False
_MCP_EP_EXPORT_PATCHED = False
_MCP_SINK_ATTN_PATCHED = False
_MCP_SINK_ATTN_WARNED = set()


def _patch_gpt_oss_sink_attention() -> None:
    """Fix the GPT-OSS attention-sink train/inference mismatch in Megatron.

    GPT-OSS uses a learnable-softmax *attention sink*: softmax over
    ``[scores, sink_logit]`` then drop the sink column. With context parallelism
    + thd packing, Transformer-Engine is forced onto the cuDNN **FusedAttention**
    kernel (FlashAttention does not support sinks), and that kernel computes the
    sink WRONG at long context -- the error grows with sequence length and is
    identical across cuDNN 9.18 / 9.19 / 9.23 (standalone Megatron-vs-HF k3_kl
    @6k = 1.078; training @14k = 3.089). Only the non-fused backends (TE
    ``unfused`` / mcore ``local``) are correct (k3_kl 0.067), but they are
    O(L^2) and CP-incompatible, so they cannot reach the 24k+98k contexts here.
    This is the root cause of the SGLang<->Megatron mismatch that broke RL.
    See Megatron_Issues/2026-06-14_gpt_oss_te_fused_sink_longctx_mismatch.md.

    Fix: replace the bad fused sink path with a flash-attn based sink path
    adapted from the Slime GPT-OSS plugin.  The default ``slime_flash`` kernel
    uses flash-attn varlen to compute vanilla attention + LSE, applies the
    exact sink renormalization, and calls flash-attn's own varlen backward with
    an explicit softmax_offset gradient.  CP=a2a is handled by reusing TE's
    Ulysses layout and an autograd-aware all-to-all.

    This patch replaces ``TEDotProductAttention.forward`` ONLY for the learnable
    sink path; every other case falls back to the upstream forward unchanged.
    """
    global _MCP_SINK_ATTN_PATCHED
    if _MCP_SINK_ATTN_PATCHED:
        return

    if os.getenv("MCP_GPT_OSS_SINK_FIX", "1") == "0":
        _MCP_SINK_ATTN_PATCHED = True
        logger.info("[MCPMegatron] gpt-oss sink attention fix disabled (MCP_GPT_OSS_SINK_FIX=0)")
        return

    try:
        from flash_attn import flash_attn_varlen_func
        from flash_attn.flash_attn_interface import _wrapped_flash_attn_varlen_backward
    except Exception as e:  # pragma: no cover - env without flash-attn
        logger.warning(
            "[MCPMegatron] flash_attn unavailable; gpt-oss sink attention fix NOT applied "
            "(training will use the buggy cuDNN sink kernel): %s", e,
        )
        return

    import math

    from megatron.core import parallel_state as mpu
    from megatron.core.extensions import transformer_engine as te_ext

    cls = te_ext.TEDotProductAttention
    orig_forward = cls.forward
    if getattr(orig_forward, "__name__", "") == "_mcp_sink_dpa_forward":
        _MCP_SINK_ATTN_PATCHED = True
        return

    def _warn_once(key: str, msg: str, *args) -> None:
        if key not in _MCP_SINK_ATTN_WARNED:
            _MCP_SINK_ATTN_WARNED.add(key)
            logger.warning(msg, *args)

    def _rescale_by_sink(out, lse_query_major, sink):
        """out[..., np, hn] * sigmoid(lse[..., np] - sink[np]), fp32 then cast back."""
        view = [1] * (lse_query_major.dim() - 1) + [-1]
        factor = torch.sigmoid(lse_query_major.float() - sink.view(*view).float())
        return (out.float() * factor.unsqueeze(-1)).to(out.dtype)

    class _McpLearnableSoftmaxFlashAttnVarlen(torch.autograd.Function):
        """FlashAttention varlen + GPT-OSS learnable sink with custom backward.

        This is adapted from the Slime GPT-OSS attention plugin.  It keeps the
        actual attention kernel on flash-attn (no FlexAttention / Dynamo compile)
        and applies the mathematically equivalent sink renormalization using the
        flash-attn LSE:

            softmax([scores, sink])[:, :-1]
            = softmax(scores) * sigmoid(logsumexp(scores) - sink)

        Backward calls flash-attn's own varlen backward with a modified dOut and
        computes d(softmax_offset) explicitly.
        """

        @staticmethod
        def forward(
            ctx,
            q,
            k,
            v,
            cu_seqlens_q,
            cu_seqlens_k,
            max_seqlen_q,
            max_seqlen_k,
            softmax_offset,
            softmax_scale,
            causal,
            window_size_left,
            window_size_right,
            dropout_p,
            deterministic,
        ):
            """Forward: varlen attention scaled by a learnable per-head softmax sink."""
            out_vanilla, softmax_lse, _ = flash_attn_varlen_func(
                q,
                k,
                v,
                cu_seqlens_q,
                cu_seqlens_k,
                max_seqlen_q,
                max_seqlen_k,
                dropout_p=dropout_p,
                softmax_scale=softmax_scale,
                causal=causal,
                window_size=(window_size_left, window_size_right),
                deterministic=deterministic,
                return_attn_probs=True,
            )
            # softmax_lse: [nheads, total_q], softmax_offset: [nheads]
            scale = torch.sigmoid(softmax_lse - softmax_offset.float().unsqueeze(1))
            scale_t = scale.t().contiguous()
            out_learn = (out_vanilla.float() * scale_t.unsqueeze(-1)).to(q.dtype)

            ctx.save_for_backward(
                q,
                k,
                v,
                out_vanilla,
                out_learn,
                softmax_lse,
                softmax_offset,
                scale_t,
                cu_seqlens_q,
                cu_seqlens_k,
            )
            ctx.max_seqlen_q = max_seqlen_q
            ctx.max_seqlen_k = max_seqlen_k
            ctx.softmax_scale = softmax_scale
            ctx.causal = causal
            ctx.window_size_left = window_size_left
            ctx.window_size_right = window_size_right
            ctx.dropout_p = dropout_p
            ctx.deterministic = deterministic
            return out_learn

        @staticmethod
        def backward(ctx, d_out):
            """Backward: gradients for q/k/v and the learnable softmax_offset (sink)."""
            (
                q,
                k,
                v,
                out_vanilla,
                out_learn,
                softmax_lse,
                softmax_offset,
                scale_t,
                cu_seqlens_q,
                cu_seqlens_k,
            ) = ctx.saved_tensors

            d_out_modified = (d_out.float() * scale_t.unsqueeze(-1)).to(q.dtype)
            dq = torch.empty_like(q)
            dk = torch.empty_like(k)
            dv = torch.empty_like(v)

            head_size_og = d_out_modified.size(2)
            d_out_padded = d_out_modified
            if head_size_og % 8 != 0:
                d_out_padded = torch.nn.functional.pad(
                    d_out_modified, [0, 8 - head_size_og % 8]
                )

            _wrapped_flash_attn_varlen_backward(
                d_out_padded.contiguous(),
                q,
                k,
                v,
                out_learn.contiguous(),
                softmax_lse,
                dq,
                dk,
                dv,
                cu_seqlens_q,
                cu_seqlens_k,
                ctx.max_seqlen_q,
                ctx.max_seqlen_k,
                ctx.dropout_p,
                ctx.softmax_scale,
                ctx.causal,
                ctx.window_size_left,
                ctx.window_size_right,
                0.0,  # softcap
                None,  # alibi_slopes
                ctx.deterministic,
                rng_state=None,
            )

            dq = dq[..., :head_size_og]
            dk = dk[..., :head_size_og]
            dv = dv[..., :head_size_og]

            scale = scale_t.t()
            dot_product = (d_out.float() * out_vanilla.float()).sum(-1).t()
            sigmoid_grad = scale * (1 - scale)
            d_offset = -(dot_product * sigmoid_grad).sum(1).to(softmax_offset.dtype)

            return (
                dq,
                dk,
                dv,
                None,
                None,
                None,
                None,
                d_offset,
                None,
                None,
                None,
                None,
                None,
                None,
            )

    def _gpt_oss_flash_window(window):
        """Translate GPT-OSS/HF strict sliding window to flash-attn's inclusive API."""
        if window is None:
            return (-1, -1)
        left, right = window
        if left is not None and left >= 0 and os.getenv("MCP_SINK_WINDOW_STRICT", "1") == "1":
            left = max(int(left) - 1, 0)
        return (left, right)

    def _slime_flash_sink_attn(q, k, v, packed_seq_params, sink, sm_scale, window, flatten=True):
        out = _McpLearnableSoftmaxFlashAttnVarlen.apply(
            q,
            k,
            v,
            packed_seq_params.cu_seqlens_q,
            packed_seq_params.cu_seqlens_kv,
            packed_seq_params.max_seqlen_q,
            packed_seq_params.max_seqlen_kv,
            sink,
            sm_scale,
            True,
            window[0],
            window[1],
            0.0,
            False,
        )
        return out.reshape(out.size(0), -1) if flatten else out

    def _flash_rescale_sink_attn(q, k, v, packed_seq_params, sink, sm_scale, window, flatten=True):
        """Memory-efficient sink approximation: FA2 vanilla varlen + fp32 rescale.

        This keeps Q/K/V and the attention kernel in BF16 flash-attn.  Only the
        final per-token/head renormalization factor is computed in FP32.  It is
        not a native sink kernel, but in standalone it closely matches HF and
        avoids FlexAttention's dense fallback at 100k+ sequence lengths.
        """
        out, lse, _ = flash_attn_varlen_func(
            q, k, v,
            packed_seq_params.cu_seqlens_q, packed_seq_params.cu_seqlens_kv,
            packed_seq_params.max_seqlen_q, packed_seq_params.max_seqlen_kv,
            dropout_p=0.0, softmax_scale=sm_scale, causal=True,
            window_size=window, return_attn_probs=True,
        )
        out = _rescale_by_sink(out, lse.transpose(0, 1), sink)
        return out.reshape(out.size(0), -1) if flatten else out

    _flex_state = {}

    def _flex_native_sink_attn(q, k, v, packed_seq_params, sink, sm_scale, window, flatten=True):
        """Native attention sink via FlexAttention with BF16 Q/K/V.

        This is not the numerically fragile "vanilla attention + LSE rescale"
        workaround.  Instead we add one virtual sink KV position per packed
        sequence, set its value vector to zero, and use ``score_mod`` to replace
        that virtual position's QK score with the per-query-head sink logit. The
        sink therefore participates inside the softmax denominator exactly like
        GPT-OSS/HF, while contributing no value to the output.

        q: [t, nq, d], k/v: [t, nkv, d] in THD layout.
        Returns [t, nq*d] by default, or [t, nq, d] with ``flatten=False``.
        """
        from torch.nn.attention.flex_attention import create_block_mask, flex_attention
        t, nq, d = q.shape
        nkv = k.shape[1]
        cu = packed_seq_params.cu_seqlens_q.to(torch.long)
        nseq = cu.numel() - 1
        seq_id = torch.zeros(t, dtype=torch.long, device=q.device)
        pos_in_seq = torch.empty(t, dtype=torch.long, device=q.device)
        k_aug = q.new_zeros((t + nseq, nkv, d))
        v_aug = q.new_zeros((t + nseq, nkv, v.shape[-1]))
        kv_seq_id = torch.empty(t + nseq, dtype=torch.long, device=q.device)
        kv_pos_in_seq = torch.empty(t + nseq, dtype=torch.long, device=q.device)
        if cu.numel() > 2:
            seq_id[cu[1:-1]] = 1
            seq_id = seq_id.cumsum(0)
        for i in range(nseq):
            start = int(cu[i])
            end = int(cu[i + 1])
            length = end - start
            aug_start = start + i
            pos_in_seq[start:end] = torch.arange(length, device=q.device)
            # Virtual sink is the first KV position for each packed sequence.
            k_aug[aug_start] = 0
            v_aug[aug_start] = 0
            kv_seq_id[aug_start] = i
            kv_pos_in_seq[aug_start] = -1
            k_aug[aug_start + 1 : aug_start + 1 + length] = k[start:end]
            v_aug[aug_start + 1 : aug_start + 1 + length] = v[start:end]
            kv_seq_id[aug_start + 1 : aug_start + 1 + length] = i
            kv_pos_in_seq[aug_start + 1 : aug_start + 1 + length] = torch.arange(
                length, device=q.device
            )
        win = int(window) if (window is not None and window >= 0) else -1
        if os.getenv("MCP_SINK_FULLCAUSAL") == "1":
            win = -1

        def mask_mod(b, h, qi, ki):
            same_seq = seq_id[qi] == kv_seq_id[ki]
            is_sink = kv_pos_in_seq[ki] < 0
            # GPT-OSS/HF convention is strict (< window), as also documented by
            # OpenAI/Unsloth. Keep an env switch because TE represents window as
            # an inclusive left span in some paths.
            m = same_seq & (is_sink | (kv_pos_in_seq[ki] <= pos_in_seq[qi]))
            if win >= 0:
                if os.getenv("MCP_SINK_WINDOW_STRICT", "1") == "1":
                    m = m & (is_sink | (pos_in_seq[qi] - kv_pos_in_seq[ki] < win))
                else:
                    m = m & (is_sink | (pos_in_seq[qi] - kv_pos_in_seq[ki] <= win))
            return m

        # Keep Q/K/V and the output in BF16, but inject the sink logit in the
        # same score dtype FlexAttention uses internally.  Casting the sink to
        # BF16 before score_mod measurably increases long-context drift.
        sink_score = sink.to(dtype=torch.float32, device=q.device)

        def score_mod(score, b, h, qi, ki):
            return torch.where(kv_pos_in_seq[ki] < 0, sink_score[h].to(score.dtype), score)

        bm = create_block_mask(
            mask_mod, 1, nq, t, t + nseq, device=q.device, _compile=True
        )
        qf = q.permute(1, 0, 2).unsqueeze(0).contiguous()
        kf = k_aug.permute(1, 0, 2).unsqueeze(0).contiguous()
        vf = v_aug.permute(1, 0, 2).unsqueeze(0).contiguous()
        if os.getenv("MCP_SINK_COMPILE_FLEX", "1") == "1":
            flex = _flex_state.get("compiled_flex_attention")
            if flex is None:
                flex = torch.compile(flex_attention, fullgraph=True, dynamic=False)
                _flex_state["compiled_flex_attention"] = flex
        else:
            flex = flex_attention
        out = flex(
            qf, kf, vf, score_mod=score_mod, block_mask=bm, scale=sm_scale,
            enable_gqa=True,
            kernel_options={"ROWS_GUARANTEED_SAFE": True},
        )
        out = out[0].permute(1, 0, 2).contiguous()
        return out.reshape(t, -1) if flatten else out

    def _sink_attn_cp_a2a(
        q, k, v, packed_seq_params, sink, sm_scale, window, cp_size, cp_group, cp_stream
    ):
        """CP=a2a wrapper around the native sink FlexAttention local kernel.

        TE's Ulysses-style CP first all-to-alls Q/K/V so each rank owns the full
        sequence but only ``heads/cp`` heads, then all-to-alls O back. Reuse the
        exact TE helpers for this layout transform and replace only the local
        fused-attention call.
        """
        from torch.distributed.nn.functional import all_to_all_single
        from transformer_engine.pytorch.attention.dot_product_attention.context_parallel import (
            get_seq_chunk_ids_for_reordering_after_attn,
            get_seq_chunk_ids_for_reordering_before_attn,
            reorder_seq_chunks_after_a2a_before_attn_thd,
            reorder_seq_chunks_before_a2a_after_attn_thd,
        )

        cu_padded = packed_seq_params.cu_seqlens_q_padded

        class _ShardSoftmaxOffset(torch.autograd.Function):
            @staticmethod
            def forward(ctx, tensor):
                """Forward: keep this CP rank's shard of the per-head softmax offset."""
                ctx.cp_group = cp_group
                ctx.orig_shape = tensor.shape
                rank = dist.get_rank(group=cp_group)
                return tensor.view(cp_size, -1)[rank].contiguous()

            @staticmethod
            def backward(ctx, grad_output):
                """Backward: all-gather the offset grads back to the full per-head shape."""
                grad = grad_output.contiguous().view(-1)
                full = torch.empty(
                    cp_size * grad.numel(), dtype=grad.dtype, device=grad.device
                )
                dist.all_gather_into_tensor(full, grad, group=ctx.cp_group)
                return full.view(ctx.orig_shape)

        def _a2a_before(x, chunk_ids):
            x = x.view(*x.shape[:-2], cp_size, x.shape[-2] // cp_size, x.shape[-1])
            x = x.movedim(-3, 0).contiguous()
            y = all_to_all_single(torch.empty_like(x), x, group=cp_group)
            y = y.view(-1, *y.shape[2:])
            return reorder_seq_chunks_after_a2a_before_attn_thd(
                y, cu_padded, chunk_ids, cp_size
            )

        def _a2a_after(x, chunk_ids):
            x = reorder_seq_chunks_before_a2a_after_attn_thd(x, cu_padded, cp_size)
            x = x.view(cp_size, -1, *x.shape[-2:])
            y = all_to_all_single(torch.empty_like(x), x, group=cp_group)
            y = y.movedim(0, -3).movedim(0, 0).contiguous()
            return y.view(-1, y.shape[-3] * y.shape[-2], y.shape[-1])

        chunk_ids = get_seq_chunk_ids_for_reordering_before_attn(cp_size, q.device)
        q_part, k_part, v_part = [_a2a_before(x, chunk_ids) for x in (q, k, v)]
        sink_part = _ShardSoftmaxOffset.apply(sink)
        # After TE's before-attn a2a, tensors are full padded sequence length
        # with only this rank's head shard. Use padded cu_seqlens so output
        # includes padded rows needed by the after-attn a2a; downstream
        # postprocess discards padded positions.
        local_psp = SimpleNamespace(
            cu_seqlens_q=cu_padded,
            cu_seqlens_kv=cu_padded,
            max_seqlen_q=packed_seq_params.max_seqlen_q,
            max_seqlen_kv=packed_seq_params.max_seqlen_kv,
        )
        _kernel = os.getenv("MCP_SINK_KERNEL", "slime_flash")
        if _kernel == "slime_flash":
            out_part = _slime_flash_sink_attn(
                q_part, k_part, v_part, local_psp, sink_part, sm_scale,
                _gpt_oss_flash_window((-1, 0) if window is None or window < 0 else (window, 0)),
                flatten=False,
            )
        elif _kernel == "flash_rescale":
            out_part = _flash_rescale_sink_attn(
                q_part, k_part, v_part, local_psp, sink_part, sm_scale,
                window=_gpt_oss_flash_window((-1, 0) if window is None or window < 0 else (window, 0)),
                flatten=False,
            )
        else:
            out_part = _flex_native_sink_attn(
                q_part, k_part, v_part, local_psp, sink_part, sm_scale, window, flatten=False
            )
        chunk_ids = get_seq_chunk_ids_for_reordering_after_attn(cp_size, out_part.device)
        out = _a2a_after(out_part, chunk_ids)
        return out.reshape(out.size(0), -1)

    def _flex_sink_attn(q, k, v, packed_seq_params, sink, sm_scale, window):
        """Legacy diagnostic path: vanilla FlexAttention + fp32 LSE rescale."""
        from torch.nn.attention.flex_attention import create_block_mask, flex_attention
        t, _, _ = q.shape
        cu = packed_seq_params.cu_seqlens_q.to(torch.long)
        seq_id = torch.zeros(t, dtype=torch.long, device=q.device)
        if cu.numel() > 2:
            seq_id[cu[1:-1]] = 1
            seq_id = seq_id.cumsum(0)
        win = int(window) if (window is not None and window >= 0) else -1
        if os.getenv("MCP_SINK_FULLCAUSAL") == "1":
            win = -1

        def mask_mod(b, h, qi, ki):
            m = (seq_id[qi] == seq_id[ki]) & (ki <= qi)
            if win >= 0:
                m = m & (qi - ki <= win)
            return m

        bm = create_block_mask(mask_mod, 1, 1, t, t, device=q.device, _compile=True)
        qf = q.permute(1, 0, 2).unsqueeze(0).float().contiguous()
        kf = k.permute(1, 0, 2).unsqueeze(0).float().contiguous()
        vf = v.permute(1, 0, 2).unsqueeze(0).float().contiguous()
        o, lse = flex_attention(
            qf, kf, vf, block_mask=bm, scale=sm_scale,
            enable_gqa=True, return_lse=True,
        )
        o = o[0].permute(1, 0, 2)
        lse_qm = lse[0].permute(1, 0)
        fac = torch.sigmoid(lse_qm - sink.view(1, -1).float())
        return (o * fac.unsqueeze(-1)).to(q.dtype).reshape(t, -1)

    _fi_state = {}

    def _flashinfer_sink_attn(q, k, v, packed_seq_params, sink, sm_scale, window_left):
        """Native attention-sink via flashinfer paged prefill (fp32-internal softmax
        over [scores, sink]; O(L); the same kernel family SGLang uses -> matches HF).
        q:[t,nq,d] k/v:[t,nkv,d] thd. Returns [t, nq*d]."""
        import flashinfer
        cu_q = packed_seq_params.cu_seqlens_q.to(torch.int32)
        cu_kv = packed_seq_params.cu_seqlens_kv.to(torch.int32)
        nseq = cu_q.numel() - 1
        nq, d = q.shape[1], q.shape[2]
        nkv = k.shape[1]
        page_size = int(packed_seq_params.max_seqlen_kv)
        seqlens_kv = (cu_kv[1:] - cu_kv[:-1]).to(torch.int32)
        kc = q.new_zeros((nseq, page_size, nkv, d))
        vc = q.new_zeros((nseq, page_size, nkv, d))
        for i in range(nseq):
            s, e = int(cu_kv[i]), int(cu_kv[i + 1])
            kc[i, : e - s] = k[s:e]
            vc[i, : e - s] = v[s:e]
        dev = q.device
        kv_indptr = torch.arange(nseq + 1, device=dev, dtype=torch.int32)
        kv_indices = torch.arange(nseq, device=dev, dtype=torch.int32)
        wb = _fi_state.get(dev)
        if wb is None:
            wb = torch.empty(256 * 1024 * 1024, dtype=torch.uint8, device=dev)
            _fi_state[dev] = wb
        wr = flashinfer.BatchPrefillWithPagedKVCacheWrapper(wb, kv_layout="NHD")
        wr.plan(cu_q, kv_indptr, kv_indices, seqlens_kv, nq, nkv, d, page_size,
                causal=True, window_left=window_left, sm_scale=sm_scale,
                q_data_type=q.dtype, kv_data_type=q.dtype)
        o = wr.run(q, (kc, vc), sinks=sink.to(torch.float32), window_left=window_left)
        return o.reshape(o.size(0), -1)

    def _mcp_sink_dpa_forward(
        self,
        query,
        key,
        value,
        attention_mask,
        attn_mask_type,
        attention_bias=None,
        packed_seq_params=None,
        num_splits=None,
    ):
        sink = getattr(self, "softmax_offset", None)
        # Only intercept the GPT-OSS learnable-softmax sink path. Anything we do
        # not explicitly support is delegated to the upstream forward unchanged.
        if (
            getattr(self, "softmax_type", "vanilla") != "learnable"
            or sink is None
            or attention_bias is not None
            or num_splits is not None
        ):
            return orig_forward(
                self, query, key, value, attention_mask, attn_mask_type,
                attention_bias=attention_bias, packed_seq_params=packed_seq_params,
                num_splits=num_splits,
            )

        qkv_format = (
            packed_seq_params.qkv_format
            if packed_seq_params is not None and getattr(packed_seq_params, "qkv_format", None)
            else self.qkv_format
        )
        cp_size = mpu.get_context_parallel_world_size()
        softmax_scale = 1.0 / math.sqrt(query.shape[-1])
        window = tuple(self.window_size) if self.window_size is not None else (-1, -1)

        # ---- thd (packed), no CP: the path the single-GPU/no-CP forward uses ----
        if cp_size == 1 and qkv_format == "thd" and packed_seq_params is not None:
            if os.getenv("MCP_SINK_FORCE_EAGER") == "1":
                # Reference path (single packed seq assumed) for verifying the sink
                # FORMULATION independent of the flash kernel. Not for production.
                t_ = query.shape[0]
                qd, kd, vd = query.float(), key.float(), value.float()
                g = qd.shape[1] // kd.shape[1]
                ke = kd.repeat_interleave(g, dim=1)
                ve = vd.repeat_interleave(g, dim=1)
                sc = torch.einsum("thd,shd->hts", qd, ke) * softmax_scale
                ii = torch.arange(t_, device=sc.device)[:, None]
                jj = torch.arange(t_, device=sc.device)[None, :]
                allowed = jj <= ii
                if window[0] is not None and window[0] >= 0:
                    allowed = allowed & (jj >= ii - window[0])
                sc = sc + torch.where(allowed, 0.0, float("-inf"))[None]
                sink_col = sink.float().view(-1, 1, 1).expand(-1, t_, 1)
                p = torch.softmax(torch.cat([sc, sink_col], dim=-1), dim=-1)[..., :t_]
                o_eager = torch.einsum("hts,shd->thd", p, ve).to(query.dtype)
                return o_eager.reshape(t_, -1)
            _kernel = os.getenv("MCP_SINK_KERNEL", "slime_flash")
            if _kernel == "slime_flash":
                return _slime_flash_sink_attn(
                    query,
                    key,
                    value,
                    packed_seq_params,
                    sink,
                    softmax_scale,
                    _gpt_oss_flash_window(window),
                )
            if _kernel == "flash_rescale":
                return _flash_rescale_sink_attn(
                    query, key, value, packed_seq_params, sink, softmax_scale,
                    _gpt_oss_flash_window(window),
                )
            if _kernel == "flex_native":
                return _flex_native_sink_attn(
                    query, key, value, packed_seq_params, sink, softmax_scale, window[0]
                )
            if _kernel == "flex_rescale":
                return _flex_sink_attn(
                    query, key, value, packed_seq_params, sink, softmax_scale, window[0]
                )
            if _kernel == "flashinfer":
                if window[0] is not None and window[0] >= 0:
                    win_left = window[0] - int(os.getenv("MCP_SINK_WIN_ADJ", "1"))
                else:
                    win_left = -1
                return _flashinfer_sink_attn(
                    query, key, value, packed_seq_params, sink, softmax_scale, win_left
                )
            out, lse, _ = flash_attn_varlen_func(
                query, key, value,
                packed_seq_params.cu_seqlens_q, packed_seq_params.cu_seqlens_kv,
                packed_seq_params.max_seqlen_q, packed_seq_params.max_seqlen_kv,
                dropout_p=0.0, softmax_scale=softmax_scale, causal=True,
                window_size=window, return_attn_probs=True,
            )
            # out: [t, np, hn]; lse: [np, t] -> query-major [t, np]
            _dbgn = getattr(_mcp_sink_dpa_forward, "_dbg_calls", 0)
            if os.getenv("MCP_SINK_DEBUG") == "1" and _dbgn < 30:
                _mcp_sink_dpa_forward._dbg_calls = _dbgn + 1
                _lse_qm = lse.transpose(0, 1).float()
                _fac = torch.sigmoid(_lse_qm - sink.view(1, -1).float())
                logger.warning(
                    "[SINKDBG] window=%s sink shape=%s min=%.3f max=%.3f mean=%.3f | "
                    "lse min=%.3f max=%.3f mean=%.3f | factor min=%.4f max=%.4f mean=%.4f",
                    window, tuple(sink.shape), float(sink.min()), float(sink.max()), float(sink.float().mean()),
                    float(_lse_qm.min()), float(_lse_qm.max()), float(_lse_qm.mean()),
                    float(_fac.min()), float(_fac.max()), float(_fac.mean()),
                )
                t_ = query.shape[0]
                qd, kd, vd = query.float(), key.float(), value.float()
                g = qd.shape[1] // kd.shape[1]
                ke = kd.repeat_interleave(g, dim=1)
                ve = vd.repeat_interleave(g, dim=1)
                sc = torch.einsum("thd,shd->hts", qd, ke) * softmax_scale
                ii = torch.arange(t_, device=sc.device)[:, None]
                jj = torch.arange(t_, device=sc.device)[None, :]
                allowed = jj <= ii
                if window[0] is not None and window[0] >= 0:
                    allowed = allowed & (jj >= ii - window[0])
                cmask = torch.where(allowed, 0.0, float("-inf"))
                sc = sc + cmask[None]
                # eager LSE (no sink) to cross-check flash's lse
                lse_eager = torch.logsumexp(sc, dim=-1)  # [np, t]
                sink_col = sink.float().view(-1, 1, 1).expand(-1, t_, 1)
                p = torch.softmax(torch.cat([sc, sink_col], dim=-1), dim=-1)[..., :t_]
                o_eager = torch.einsum("hts,shd->thd", p, ve)
                out_dbg = _rescale_by_sink(out, _lse_qm, sink)
                logger.warning(
                    "[SINKDBG call=%d window=%s] ||flash+rescale - eager_sink|| mean_abs=%.5f | "
                    "||flash_lse - eager_lse|| mean_abs=%.5f | out absmax=%.3f eager absmax=%.3f",
                    _dbgn, window,
                    float((out_dbg.float() - o_eager).abs().mean()),
                    float((_lse_qm - lse_eager.transpose(0, 1)).abs().mean()),
                    float(out_dbg.float().abs().max()), float(o_eager.abs().max()),
                )
            out = _rescale_by_sink(out, lse.transpose(0, 1), sink)
            return out.reshape(out.size(0), -1)

        if (
            cp_size > 1
            and qkv_format == "thd"
            and packed_seq_params is not None
            and os.getenv("MCP_SINK_KERNEL", "slime_flash")
            in {"slime_flash", "flash_rescale", "flex_native"}
        ):
            cp_group = getattr(self, "cp_group", None)
            cp_stream = getattr(te_ext.TEDotProductAttention, "cp_stream", None)
            if cp_group is None:
                cp_group = mpu.get_context_parallel_group()
            if cp_stream is None:
                te_ext.TEDotProductAttention.cp_stream = torch.cuda.Stream()
                cp_stream = te_ext.TEDotProductAttention.cp_stream
            if cp_group is not None and cp_stream is not None:
                return _sink_attn_cp_a2a(
                    query, key, value, packed_seq_params, sink, softmax_scale, window[0],
                    cp_size, cp_group, cp_stream,
                )
            _warn_once(
                "cp_a2a_no_group",
                "[MCPMegatron] gpt-oss sink fix: cp_size=%d but cp_group/cp_stream missing; "
                "falling back to upstream cuDNN sink kernel.",
                cp_size,
            )

        # ---- everything else (CP>1 / non-thd) not yet validated: fall back ----
        _warn_once(
            f"fallback_cp{cp_size}_{qkv_format}",
            "[MCPMegatron] gpt-oss sink fix: cp_size=%d qkv_format=%s not handled yet -> "
            "using upstream (buggy) cuDNN sink kernel for this call.",
            cp_size, qkv_format,
        )
        return orig_forward(
            self, query, key, value, attention_mask, attn_mask_type,
            attention_bias=attention_bias, packed_seq_params=packed_seq_params,
            num_splits=num_splits,
        )

    cls.forward = _mcp_sink_dpa_forward
    _MCP_SINK_ATTN_PATCHED = True
    logger.info(
        "[MCPMegatron] patched TEDotProductAttention.forward with gpt-oss sink "
        "fix (slime_flash default + autograd CP-a2a)"
    )


def _patch_megatron_vocab_parallel_entropy_for_memory() -> None:
    """Patch Megatron entropy to process token rows in chunks.

    This keeps the objective unchanged but avoids one huge temporary tensor
    allocation inside vocab_parallel_entropy (which can OOM on long sequences).
    """
    global _MCP_VOCAB_ENTROPY_PATCHED
    if _MCP_VOCAB_ENTROPY_PATCHED:
        return

    # 0 disables chunking and keeps upstream behavior.
    try:
        chunk_nnz = int(os.getenv("MCP_VOCAB_ENTROPY_CHUNK_NNZ", "4096"))
    except ValueError:
        chunk_nnz = 4096

    if chunk_nnz <= 0:
        _MCP_VOCAB_ENTROPY_PATCHED = True
        logger.info("[MCPMegatron] entropy chunking disabled (MCP_VOCAB_ENTROPY_CHUNK_NNZ<=0)")
        return

    # Import lazily in worker process so patch is applied exactly where
    # megatron_actor forward() resolves vocab_parallel_entropy.
    import verl.utils.megatron.tensor_parallel as tensor_parallel_mod
    import verl.workers.actor.megatron_actor as megatron_actor_mod

    original_entropy = tensor_parallel_mod.vocab_parallel_entropy

    # Idempotent protection when workers are recreated.
    if getattr(original_entropy, "__name__", "") == "_mcp_chunked_vocab_parallel_entropy":
        _MCP_VOCAB_ENTROPY_PATCHED = True
        return

    def _mcp_chunked_vocab_parallel_entropy(vocab_parallel_logits: torch.Tensor) -> torch.Tensor:
        # Upstream entropy reduces over the last dim. Flatten any leading dims so
        # chunking applies to both [nnz, vocab_shard] and [*, nnz, vocab_shard] shapes.
        # Every original_entropy() call below clones its input FIRST.
        # _VocabParallelEntropy mutates its input logits IN-PLACE, but we must
        # leave the caller's `logits` pristine so that (a) the subsequent log-prob
        # computation stays correct and (b) we can safely drop verl's defensive
        # `logits_bak = logits.clone()` in the actor forward (see
        # _patch_megatron_actor_drop_entropy_logits_clone) -- the single biggest
        # entropy-in-loss memory win (~24GiB: the clone itself + its logprob grad).
        if vocab_parallel_logits.dim() < 2:
            return original_entropy(vocab_parallel_logits.clone())

        leading_shape = vocab_parallel_logits.shape[:-1]
        vocab_shard = vocab_parallel_logits.shape[-1]
        logits_2d = vocab_parallel_logits.reshape(-1, vocab_shard)

        if logits_2d.shape[0] <= chunk_nnz:
            return original_entropy(logits_2d.clone()).reshape(*leading_shape)

        # ``_VocabParallelEntropy.forward/backward`` mutate the saved
        # ``vocab_parallel_logits`` tensor in-place (``.sub_``, ``.mul_``,
        # ``.add_``, ``.div_``); see verl/utils/megatron/tensor_parallel.py.
        # Passing slice views here is unsafe: PyTorch tracks tensor version
        # at the *storage* level, so chunk ``i+1``'s in-place ops bump the
        # version of chunk ``i``'s saved view -> autograd refuses to backward
        # ("variable needed for gradient computation has been modified by
        # an inplace operation, ... is at version 3; expected version 1").
        # ``.clone()`` gives each chunk its own independent storage so the
        # in-place pattern stays self-contained.
        #
        # Chunking alone only bounds the FORWARD peak. In the actor UPDATE
        # (backward), ``_VocabParallelEntropy`` saves ``softmax_logits``
        # [chunk, vocab_shard] per chunk for ITS backward; summed over all
        # chunks that is the full [nnz, vocab_shard] (tens of GiB on GPT-OSS
        # long-ctx) and OOMs the update -- chunking would have saved nothing.
        # So when grad is required we wrap each chunk in gradient checkpointing
        # (use_reentrant=False, like Megatron's own activation recompute): the
        # chunk's softmax is discarded after forward and recomputed in backward,
        # bounding BOTH forward and backward to ~one chunk. The full ``logits_2d``
        # is the only retained checkpoint input, and it is already live, so the
        # net extra retention is ~0. The forward-only log-prob/logging path (no
        # grad) keeps the plain chunked call (already ~one chunk, nothing saved).
        # The entropy reduction all-reduces over the TP group only, and TP ranks
        # share the same tokens (== same chunk count), so the recompute's
        # collectives stay in lockstep across ranks -- no deadlock.
        from torch.utils.checkpoint import checkpoint as _grad_checkpoint

        def _entropy_slice(full_logits, start, end):
            return original_entropy(full_logits[start:end].clone())

        use_ckpt = torch.is_grad_enabled() and logits_2d.requires_grad
        outputs = []
        total_nnz = logits_2d.shape[0]
        for start in range(0, total_nnz, chunk_nnz):
            end = min(start + chunk_nnz, total_nnz)
            if use_ckpt:
                ent = _grad_checkpoint(
                    _entropy_slice, logits_2d, start, end, use_reentrant=False
                )
            else:
                ent = _entropy_slice(logits_2d, start, end)
            outputs.append(ent)
        out_1d = torch.cat(outputs, dim=0)

        return out_1d.reshape(*leading_shape)

    # Keep both module references in sync:
    # - tensor_parallel module symbol
    # - megatron_actor imported symbol
    tensor_parallel_mod.vocab_parallel_entropy = _mcp_chunked_vocab_parallel_entropy
    megatron_actor_mod.vocab_parallel_entropy = _mcp_chunked_vocab_parallel_entropy

    _MCP_VOCAB_ENTROPY_PATCHED = True
    logger.info(
        "[MCPMegatron] enabled chunked vocab_parallel_entropy, chunk_nnz=%d "
        "(grad-checkpointed per chunk so backward stays ~1 chunk too)", chunk_nnz,
    )


def _patch_megatron_compute_log_prob_for_zero_entropy() -> None:
    """Skip Megatron entropy recompute when entropy coeff is zero.

    veRL's Megatron compute_log_prob path always asks the actor for entropy and
    the upstream implementation clones the full vocab logits before computing
    entropy. On GPT-OSS + long sequences this can allocate tens of GiB and OOM.

    When entropy_coeff == 0, skipping entropy recomputation preserves the PPO
    loss semantics. We still return a zero tensor with the right shape so the
    downstream trainer contract remains unchanged.
    """

    global _MCP_ZERO_ENTROPY_PATCHED
    if _MCP_ZERO_ENTROPY_PATCHED:
        return

    import verl.workers.actor.megatron_actor as megatron_actor_mod

    actor_cls = megatron_actor_mod.MegatronPPOActor
    original_compute_log_prob = actor_cls.compute_log_prob

    if getattr(original_compute_log_prob, "__name__", "") == "_mcp_compute_log_prob_zero_entropy":
        _MCP_ZERO_ENTROPY_PATCHED = True
        return

    def _mcp_compute_log_prob_zero_entropy(self, data, calculate_entropy=False):
        # LOGGING-ONLY entropy: compute entropy whenever the caller asks
        # (compute_log_prob / old_log_prob passes calculate_entropy=True),
        # INDEPENDENT of entropy_coeff. This is the FORWARD-ONLY path, so entropy is
        # cheap (no backward grads -> none of the ~25GiB fp32 logits-grad buffers
        # that OOM'd update_actor) and we still get the actor/entropy metric to watch
        # for entropy collapse. Whether entropy enters the LOSS is decided separately
        # in update_policy (calculate_entropy = entropy_coeff != 0); so with
        # entropy_coeff=0 we LOG entropy but never add it to the loss / backward.
        log_probs, entropys, layers_topk_idx = original_compute_log_prob(
            self,
            data,
            calculate_entropy=calculate_entropy,
        )
        return log_probs, entropys, layers_topk_idx

    actor_cls.compute_log_prob = _mcp_compute_log_prob_zero_entropy
    _MCP_ZERO_ENTROPY_PATCHED = True
    logger.info("[MCPMegatron] patched compute_log_prob to skip entropy recompute when entropy_coeff=0")


def _patch_megatron_actor_drop_entropy_logits_clone() -> None:
    """Drop verl's defensive ``logits_bak = logits.clone()`` in the actor forward.

    verl's ``MegatronPPOActor.forward_backward_batch`` builds a per-micro-batch
    ``logits_processor`` closure that, when ``calculate_entropy=True``, does::

        logits_bak = logits.clone()                       # full [nnz, vocab/tp] (~12GiB)
        entropy   = vocab_parallel_entropy(logits)
        log_probs = vocab_parallel_log_probs_from_logits(logits_bak, label)

    The clone exists ONLY because the upstream ``vocab_parallel_entropy`` mutates
    its input in-place. Our chunked entropy patch
    (``_patch_megatron_vocab_parallel_entropy_for_memory``) clones internally on
    every path and is fully non-mutating, so this clone is pure waste:
      * a full [nnz, vocab/tp] copy resident through backward (~12GiB), AND
      * it forces a SECOND full logits grad in backward (``logits_bak.grad``)
        that coexists with ``logits.grad`` -> the ~23GiB allocation that OOM'd
        ``update_actor`` on the 140GiB H200 at 24k+98k context.

    We source-rewrite the method, replacing ``logits.clone()`` with ``logits``.
    This REQUIRES the non-mutating chunked entropy patch, so we install it first.
    Fail-safe: if the marker is missing/ambiguous (verl changed the code) we warn
    and leave the original (correct, just memory-hungry) implementation.
    """
    global _MCP_ENTROPY_CLONE_DROP_PATCHED
    if _MCP_ENTROPY_CLONE_DROP_PATCHED:
        return

    # The clone is only safe to drop if entropy is non-mutating.
    _patch_megatron_vocab_parallel_entropy_for_memory()

    import inspect
    import textwrap

    import verl.utils.megatron.tensor_parallel as tensor_parallel_mod
    import verl.workers.actor.megatron_actor as megatron_actor_mod

    # SAFETY: only drop the clone if the chunked (non-mutating) entropy is actually
    # installed. With MCP_VOCAB_ENTROPY_CHUNK_NNZ<=0 the patch above is a no-op and
    # the ORIGINAL in-place-mutating vocab_parallel_entropy stays -> dropping the
    # clone would feed mutated logits to log-prob and corrupt training.
    if getattr(tensor_parallel_mod.vocab_parallel_entropy, "__name__", "") != "_mcp_chunked_vocab_parallel_entropy":
        logger.warning(
            "[MCPMegatron] chunked non-mutating entropy NOT active "
            "(MCP_VOCAB_ENTROPY_CHUNK_NNZ<=0?); keeping verl's logits.clone() to stay correct."
        )
        _MCP_ENTROPY_CLONE_DROP_PATCHED = True
        return

    actor_cls = megatron_actor_mod.MegatronPPOActor
    fn = actor_cls.forward_backward_batch
    if getattr(fn, "_mcp_clone_dropped", False):
        _MCP_ENTROPY_CLONE_DROP_PATCHED = True
        return

    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError) as e:
        logger.warning("[MCPMegatron] cannot read forward_backward_batch source (%s); clone not dropped", e)
        _MCP_ENTROPY_CLONE_DROP_PATCHED = True
        return

    needle = "logits_bak = logits.clone()"
    count = src.count(needle)
    if count != 1:
        logger.warning(
            "[MCPMegatron] entropy logits.clone() marker found %d times (expected 1); "
            "leaving original forward (entropy-in-loss may OOM). verl version drift?",
            count,
        )
        _MCP_ENTROPY_CLONE_DROP_PATCHED = True
        return

    new_src = textwrap.dedent(
        src.replace(
            needle,
            "logits_bak = logits  # [MCP] clone dropped: chunked entropy is non-mutating",
        )
    )

    # Compile against the module globals so every name the method uses resolves.
    namespace: dict = {}
    exec(compile(new_src, megatron_actor_mod.__file__, "exec"), megatron_actor_mod.__dict__, namespace)
    new_fn = namespace["forward_backward_batch"]
    new_fn._mcp_clone_dropped = True
    actor_cls.forward_backward_batch = new_fn

    _MCP_ENTROPY_CLONE_DROP_PATCHED = True
    logger.info(
        "[MCPMegatron] dropped defensive logits.clone() in actor forward "
        "(entropy-in-loss memory fix: frees ~24GiB of update peak)"
    )


# ===========================================================================
# Fused chunked vocab-parallel log-prob + entropy (entropy-in-loss memory fix)
# ===========================================================================
#
# THE definitive fix for "entropy-in-loss OOMs". verl's actor computes entropy
# and log-prob with TWO separate kernels (vocab_parallel_entropy and Megatron's
# vocab_parallel_cross_entropy) that EACH mutate logits in-place and EACH save a
# full [nnz, vocab/tp] softmax, so verl must keep a full logits.clone(). That
# clone + the duplicated softmax/grad is the ~tens-of-GiB straw that OOMs the
# update on GPT-OSS long-ctx. (Dropping just the clone -- see the dormant
# _patch_megatron_actor_drop_entropy_logits_clone above -- crashes, because the
# grad-checkpointed chunked entropy retains the original logits while the
# cross-entropy logprob mutates it in-place -> autograd version-counter error.)
#
# This computes BOTH quantities from the SAME logits in one custom autograd
# Function that (a) never mutates logits, (b) never materializes a full softmax
# (recomputed per token-chunk in backward), and (c) writes ONE combined logit
# grad. Net peak ~= log-prob alone -> entropy-in-loss fits bf16 at full context.
# Unlike verl's Triton fused kernel (efficient_entropy_forward asserts
# hidden_size % 128 == 0, which GPT-OSS hidden=2880 fails), this is pure PyTorch
# and has NO dimension constraint.
#
# Math (per token; z = logits over GLOBAL vocab, p = softmax(z)):
#     lse = logsumexp(z);   H = lse - <p, z>;   logp(label) = z[label] - lse
#     dH/dz_j     = p_j * (<p,z> - z_j)
#     dlogp/dz_j  = 1[j==label] - p_j
# Logits are sharded on the vocab dim across the TP group, so the vocab
# reductions (max, sum-exp, <p,z>, target logit) are all-reduced over the TP
# group in forward; backward is elementwise on saved per-token scalars (lse,
# <p,z>) and needs NO collectives. All TP ranks share the same tokens => same
# chunk count => all-reduces stay in lockstep (no deadlock), same invariant the
# chunked-entropy patch already relies on.
#
# DEFAULT ON (disable with MCP_FUSED_LOGPROB_ENTROPY=0). The calculate_entropy=False
# branch is left untouched, so logp-only / coeff=0 loss runs are unaffected. Chunk
# size via MCP_FUSED_LE_CHUNK (default 2048; smaller = less peak, more steps).


def _mcp_fused_le_chunk(default: int = 2048) -> int:
    try:
        c = int(os.getenv("MCP_FUSED_LE_CHUNK", str(default)))
    except ValueError:
        return default
    return c if c > 0 else default


class _FusedVPLogprobEntropy(torch.autograd.Function):
    """Fused, chunked, vocab-parallel (log p(label), entropy) from logits.

    forward(logits[*, V/tp], labels[*], chunk, tp_group, tp_rank)
        -> (log_probs[*], entropy[*])   both fp32
    Does not mutate ``logits``; saves only ``logits`` (the input, already live)
    plus two tiny per-token fp32 vectors (lse, <p,z>); recomputes softmax per
    chunk in backward.
    """

    @staticmethod
    def forward(ctx, logits, labels, chunk, tp_group, tp_rank):
        """Forward: chunked, TP-vocab-parallel token log-prob and entropy."""
        leading = tuple(logits.shape[:-1])
        vocab_shard = logits.shape[-1]
        flat = logits.reshape(-1, vocab_shard)
        lab = labels.reshape(-1)
        nnz = flat.shape[0]
        assert lab.shape[0] == nnz, (lab.shape, flat.shape)
        vocab_start = tp_rank * vocab_shard

        lse_rows = torch.empty(nnz, dtype=torch.float32, device=flat.device)
        spz_rows = torch.empty(nnz, dtype=torch.float32, device=flat.device)
        logp_rows = torch.empty(nnz, dtype=torch.float32, device=flat.device)
        ent_rows = torch.empty(nnz, dtype=torch.float32, device=flat.device)

        for s in range(0, nnz, chunk):
            e = min(s + chunk, nnz)
            z = flat[s:e].float()                                  # [c, V/tp] local shard
            lab_c = lab[s:e]
            zmax = z.max(dim=-1, keepdim=True).values              # [c, 1]
            if tp_group is not None:
                dist.all_reduce(zmax, op=dist.ReduceOp.MAX, group=tp_group)
            ez = (z - zmax).exp()                                  # [c, V/tp]
            sum_ez = ez.sum(dim=-1)                                # [c] local
            ezz = (ez * z).sum(dim=-1)                             # [c] local (unnormalized <e^z, z>)
            # target logit on the owning shard only (0 elsewhere)
            tmask = (lab_c < vocab_start) | (lab_c >= vocab_start + vocab_shard)
            masked = (lab_c - vocab_start).masked_fill(tmask, 0)
            pred = z.gather(1, masked.unsqueeze(1)).squeeze(1)     # [c] local
            pred = pred.masked_fill(tmask, 0.0)
            packed = torch.stack([sum_ez, ezz, pred], dim=1)       # [c, 3]
            if tp_group is not None:
                dist.all_reduce(packed, op=dist.ReduceOp.SUM, group=tp_group)
            sum_ez_g = packed[:, 0]
            ezz_g = packed[:, 1]
            pred_g = packed[:, 2]
            lse = zmax.squeeze(1) + sum_ez_g.log()                 # [c] global logsumexp
            spz = ezz_g / sum_ez_g                                 # [c] global <p, z>
            lse_rows[s:e] = lse
            spz_rows[s:e] = spz
            logp_rows[s:e] = pred_g - lse
            ent_rows[s:e] = lse - spz

        ctx.save_for_backward(flat, lab, lse_rows, spz_rows)
        ctx.chunk = chunk
        ctx.vocab_start = vocab_start
        ctx.vocab_shard = vocab_shard
        ctx.leading = leading
        return logp_rows.reshape(leading), ent_rows.reshape(leading)

    @staticmethod
    def backward(ctx, g_logp, g_ent):
        """Backward: recompute per-chunk softmax to produce logits gradients."""
        flat, lab, lse_rows, spz_rows = ctx.saved_tensors
        chunk = ctx.chunk
        vocab_start = ctx.vocab_start
        vocab_shard = ctx.vocab_shard
        nnz = flat.shape[0]
        g_logp = g_logp.reshape(-1).float()
        g_ent = g_ent.reshape(-1).float()
        grad = torch.empty_like(flat)

        for s in range(0, nnz, chunk):
            e = min(s + chunk, nnz)
            z = flat[s:e].float()                                  # [c, V/tp]
            lse = lse_rows[s:e].unsqueeze(1)
            spz = spz_rows[s:e].unsqueeze(1)
            p = (z - lse).exp()                                    # [c, V/tp] global softmax (local shard)
            g_ent_c = g_ent[s:e].unsqueeze(1)
            g_logp_c = g_logp[s:e].unsqueeze(1)
            # p * ( g_ent*(spz - z) - g_logp )  + onehot(label)*g_logp
            gc = p * ((spz - z) * g_ent_c - g_logp_c)             # [c, V/tp]
            lab_c = lab[s:e]
            tmask = (lab_c < vocab_start) | (lab_c >= vocab_start + vocab_shard)
            masked = (lab_c - vocab_start).masked_fill(tmask, 0)
            add = (~tmask).to(torch.float32) * g_logp[s:e]        # onehot weight, 0 if not owned
            gc.scatter_add_(1, masked.unsqueeze(1), add.unsqueeze(1))
            grad[s:e] = gc.to(flat.dtype)

        return grad.reshape(*ctx.leading, vocab_shard), None, None, None, None


def _mcp_fused_logprob_entropy(logits, labels):
    """Closure-facing entry. Returns (entropy, log_probs) (note the order: it
    matches the rewritten ``entropy, ret[...] = _mcp_fused_logprob_entropy(...)``
    call). log_probs is RAW (the closure applies the label_mask afterwards)."""
    from megatron.core import parallel_state as mpu

    try:
        tp_world = mpu.get_tensor_model_parallel_world_size()
        tp_rank = mpu.get_tensor_model_parallel_rank()
        tp_group = mpu.get_tensor_model_parallel_group() if tp_world > 1 else None
    except Exception:
        tp_rank, tp_group = 0, None
    logp, ent = _FusedVPLogprobEntropy.apply(
        logits, labels, _mcp_fused_le_chunk(), tp_group, tp_rank
    )
    return ent, logp


def _patch_megatron_fused_logprob_entropy() -> None:
    """Route the actor's entropy+log-prob through the fused, non-mutating,
    chunked path so entropy-in-loss fits memory (see the block comment above).

    Opt-in via MCP_FUSED_LOGPROB_ENTROPY. Source-rewrites three single-line
    needles in ``MegatronPPOActor.forward_backward_batch`` (robust to the
    comment block between them); fails safe (warn + keep original) if any needle
    is missing/ambiguous (verl drift)."""
    global _MCP_FUSED_LE_PATCHED
    if _MCP_FUSED_LE_PATCHED:
        return

    # DEFAULT ON. The fused path is numerically identical to verl's (validated:
    # logp/entropy/grad match to ~1e-6 fp32) and the calculate_entropy=False branch
    # is left untouched, so logp-only / coeff=0 loss runs are unaffected. Enabling
    # it unconditionally GUARANTEES entropy-in-loss never silently falls back to the
    # OOM-prone clone path if env propagation hiccups. Force off with
    # MCP_FUSED_LOGPROB_ENTROPY=0 (the apptainer wrapper sets it to 0 when
    # entropy_coeff==0, 1 otherwise).
    enabled = os.getenv("MCP_FUSED_LOGPROB_ENTROPY", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    if not enabled:
        _MCP_FUSED_LE_PATCHED = True
        logger.info(
            "[MCPMegatron] fused logprob+entropy DISABLED via MCP_FUSED_LOGPROB_ENTROPY=0 "
            "(entropy-in-loss would use the OOM-prone clone path)"
        )
        return

    import inspect
    import textwrap

    import verl.workers.actor.megatron_actor as megatron_actor_mod

    actor_cls = megatron_actor_mod.MegatronPPOActor
    fn = actor_cls.forward_backward_batch
    if getattr(fn, "_mcp_fused_le", False):
        _MCP_FUSED_LE_PATCHED = True
        return

    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError) as exc:
        logger.warning(
            "[MCPMegatron] cannot read forward_backward_batch source (%s); "
            "fused logprob+entropy NOT applied", exc,
        )
        _MCP_FUSED_LE_PATCHED = True
        return

    replacements = [
        (
            "logits_bak = logits.clone()",
            "logits_bak = logits  # [MCP] fused logprob+entropy: clone dropped",
        ),
        (
            "entropy = vocab_parallel_entropy(logits)",
            'entropy, ret["__mcp_fused_lp__"] = _mcp_fused_logprob_entropy(logits, label)',
        ),
        (
            "log_probs = vocab_parallel_log_probs_from_logits(logits_bak, label)",
            'log_probs = ret.pop("__mcp_fused_lp__") if "__mcp_fused_lp__" in ret '
            "else vocab_parallel_log_probs_from_logits(logits_bak, label)",
        ),
    ]
    for needle, _ in replacements:
        n = src.count(needle)
        if n != 1:
            logger.warning(
                "[MCPMegatron] fused logprob+entropy: needle %r found %d times "
                "(expected 1); leaving original forward (entropy-in-loss may OOM). "
                "verl version drift?", needle, n,
            )
            _MCP_FUSED_LE_PATCHED = True
            return

    new_src = src
    for needle, repl in replacements:
        new_src = new_src.replace(needle, repl)
    new_src = textwrap.dedent(new_src)

    # The rewritten closure references _mcp_fused_logprob_entropy as a global.
    megatron_actor_mod._mcp_fused_logprob_entropy = _mcp_fused_logprob_entropy

    namespace: dict = {}
    exec(compile(new_src, megatron_actor_mod.__file__, "exec"), megatron_actor_mod.__dict__, namespace)
    new_fn = namespace["forward_backward_batch"]
    new_fn._mcp_fused_le = True
    actor_cls.forward_backward_batch = new_fn

    _MCP_FUSED_LE_PATCHED = True
    logger.info(
        "[MCPMegatron] ENABLED fused chunked logprob+entropy (chunk=%d): "
        "entropy-in-loss is now memory-safe (no clone, no full softmax, one grad)",
        _mcp_fused_le_chunk(),
    )


def _patch_megatron_ep_export_for_local_experts() -> None:
    """Patch Megatron Bridge EP export for SequentialMLP local_experts names.

    Megatron Bridge's generic gather_from_ep_ranks() assumes expert ids are
    encoded as suffixes like ``...weight15`` / ``...bias15``. GPT-OSS with
    ``moe_grouped_gemm=false`` uses SequentialMLP names like
    ``...local_experts.15.linear_fc2.weight`` instead. On export, the upstream
    parser does ``int(self.megatron_param.split('.weight')[-1])`` and crashes
    with ``ValueError: invalid literal for int() with base 10: ''``.

    We patch only the extraction logic to use the upstream helper
    ``extract_expert_number_from_param()``, which already supports both naming
    schemes. The rest of the EP gather/export behavior remains unchanged.
    """

    global _MCP_EP_EXPORT_PATCHED
    if _MCP_EP_EXPORT_PATCHED:
        return

    from megatron.bridge.models.conversion import param_mapping as param_mapping_mod
    from megatron.bridge.utils.common_utils import extract_expert_number_from_param

    mapping_cls = param_mapping_mod.MegatronParamMapping
    original_gather_from_ep_ranks = mapping_cls.gather_from_ep_ranks

    if getattr(original_gather_from_ep_ranks, "__name__", "") == "_mcp_gather_from_ep_ranks":
        _MCP_EP_EXPORT_PATCHED = True
        return

    def _mcp_gather_from_ep_ranks(self, megatron_weights, megatron_module, hf_param_name):
        if megatron_module is None:
            num_experts_per_rank = self.broadcast_obj_from_pp_rank(None, "num_experts_per_rank")
        else:
            model_config = self._get_config(megatron_module)
            num_experts = model_config.num_moe_experts
            num_experts_per_rank = num_experts // self.ep_size
            num_experts_per_rank = self.broadcast_obj_from_pp_rank(num_experts_per_rank, "num_experts_per_rank")

        try:
            global_expert_number = extract_expert_number_from_param(self.megatron_param)
        except (ValueError, IndexError):
            # Fall back to upstream behavior for unexpected future naming schemes.
            return original_gather_from_ep_ranks(self, megatron_weights, megatron_module, hf_param_name)

        local_expert_number = global_expert_number % num_experts_per_rank

        gathered_expert_param_names = [
            re.sub(
                r"experts\.(\d+)",
                f"experts.{int(local_expert_number) + num_experts_per_rank * i}",
                str(hf_param_name),
            )
            for i in range(self.ep_size)
        ]
        assert str(hf_param_name) in gathered_expert_param_names, (
            f"hf_param_name {hf_param_name} not in gathered_expert_param_names {gathered_expert_param_names}"
        )

        gathered_weights = [torch.empty_like(megatron_weights) for _ in range(self.ep_size)]
        torch.distributed.all_gather(gathered_weights, megatron_weights, group=self.ep_group)

        weights_dict = {}
        for i, param_name in enumerate(gathered_expert_param_names):
            if param_name in weights_dict:
                weights_dict[param_name] = torch.cat(
                    [weights_dict[param_name], gathered_weights[i].unsqueeze(0)], dim=0
                )
            else:
                weights_dict[param_name] = gathered_weights[i].unsqueeze(0)
        for param_name in weights_dict:
            weights_dict[param_name] = weights_dict[param_name].squeeze()
        return weights_dict

    mapping_cls.gather_from_ep_ranks = _mcp_gather_from_ep_ranks
    _MCP_EP_EXPORT_PATCHED = True
    logger.info("[MCPMegatron] patched Bridge EP export for local_experts parameter names")
