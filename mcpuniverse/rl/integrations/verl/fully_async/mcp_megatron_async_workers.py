# pylint: disable=too-many-ancestors

"""
Megatron worker classes for MCP fully async training.

Megatron counterparts of MCPAsyncRolloutWorker and MCPDetachActorWorker.
These extend the upstream Megatron DetachNcclSync-based classes instead
of the FSDP ones, enabling Megatron training strategy in fully async mode.

Weight sync flow (Megatron):
  1. Actor workers extract weights via Bridge (mcore -> HF format),
     broadcast converted tensors via NCCL collective
  2. MCPMegatronAsyncRolloutWorker receives each tensor via NCCL and
     immediately yields it to ServerAdapter.update_weights() (CUDA IPC)
  3. ServerAdapter pushes each bucket to the inference server via CUDA IPC

The rollout-side receive logic is strategy-agnostic: both FSDP and Megatron
produce the same _weights_info format and NCCL broadcast protocol. The base
class difference (Megatron DetachAsyncRolloutWorker vs FSDP) handles
init_model() and Megatron-specific worker initialization internally.
"""

import gc
import logging
import os
import time

import torch
from ray.util.collective import collective

from verl.experimental.fully_async_policy.megatron_worker import (
    DetachActorWorker as MegatronDetachActorWorker,
    DetachAsyncRolloutWorker as MegatronDetachAsyncRolloutWorker,
)
from verl.single_controller.base.decorator import Dispatch, make_nd_compute_dataproto_dispatch_fn, register
from verl.utils.device import get_torch_device, is_npu_available

# Megatron runtime monkey-patches were moved into the shared
# ``..mcp_megatron_patches`` module so the hybrid trainer can import them
# without reaching into the fully-async subpackage. The names are re-exported
# here for backwards compatibility with any external code that imported them
# from this module historically.
from ..mcp_megatron_patches import (
    _patch_gpt_oss_sink_attention,
    _patch_megatron_compute_log_prob_for_zero_entropy,
    _patch_megatron_ep_export_for_local_experts,
    _patch_megatron_fused_logprob_entropy,
    _patch_megatron_vocab_parallel_entropy_for_memory,
)

# Worker-side defensive flatten of any nested tensor/array metric values
# emitted inside a single worker. This alone is insufficient to fix the
# cross-rank ``inhomogeneous shape`` crash in ``reduce_metrics`` because
# ``DataProto.concat`` re-nests per-worker lists during ray dispatch
# collection -- the real fix lives in ``MCPFullyAsyncTrainer._fit_update_actor``
# on the trainer (controller) side. Worker-side wrapper is kept as a
# defense-in-depth layer for any in-worker reducer that might run before
# concat (e.g. micro-batch internal aggregation).
from ..utils import flatten_dataproto_metrics_inplace as _flatten_dataproto_metrics_inplace

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "INFO"))


class MCPMegatronAsyncRolloutWorker(MegatronDetachAsyncRolloutWorker):
    """Megatron rollout worker that syncs weights to inference servers via ServerAdapter.

    Identical streaming pattern as MCPAsyncRolloutWorker (FSDP version):
    NCCL recv -> yield -> IPC push, one tensor at a time.

    The only difference from the FSDP MCPAsyncRolloutWorker is the base
    class, which handles Megatron-specific model initialization internally.
    """

    @register(dispatch_mode=Dispatch.ONE_TO_ALL, blocking=False)
    def warmup_nccl_group(self, sync_group_name="actor_rollout"):
        """Dummy broadcast to pre-create the NCCL communicator during init.

        Ray collective lazily creates NCCL communicators on first broadcast.
        The rendezvous has a hard 180s timeout.  If the actor side is slow
        (model offload reload + Bridge conversion), the rollout side times
        out before rank 0 ever calls broadcast.  Running a tiny warmup
        broadcast while all workers are idle avoids this.
        """
        dummy = torch.zeros(1, device=get_torch_device().current_device())
        if is_npu_available:
            self._weight_sync_group.broadcast(
                dummy, src=0, stream=get_torch_device().current_stream(),
            )
        else:
            collective.broadcast(dummy, src_rank=0, group_name=sync_group_name)

    @register(dispatch_mode=Dispatch.ONE_TO_ALL)
    def free_fsdp_model(self):
        """Free the unused model shard to reclaim GPU memory.

        Named free_fsdp_model for interface compatibility with
        MCPFullyAsyncRollouter (which calls rollout_wg.free_fsdp_model()),
        though in Megatron mode it frees the Megatron model shard.
        """
        freed = []
        for attr in ("actor_module_fsdp", "actor_module"):
            if hasattr(self, attr) and getattr(self, attr) is not None:
                setattr(self, attr, None)
                freed.append(attr)
        gc.collect()
        get_torch_device().empty_cache()

        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else 0
        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3)
        logger.info(
            "[MCPMegatronAsyncRolloutWorker] rank=%d freed model (%s), GPU allocated: %.2f GiB",
            rank, ', '.join(freed) or 'nothing to free', alloc_gb,
        )

    @register(dispatch_mode=Dispatch.ONE_TO_ALL, blocking=False)
    def sync_rollout_weights(self, sync_group_name="actor_rollout"):
        """Stream weights from actor workers via NCCL to inference server via IPC.

        Same streaming pattern as the FSDP version: receive one tensor via
        NCCL broadcast and immediately yield to ServerAdapter.update_weights()
        so only one weight tensor lives on GPU at a time (~100MB vs ~42GB).
        """
        assert self._is_rollout and not self.config.hybrid_engine
        assert hasattr(self, "_weights_info") and self._weights_info is not None

        start_time = time.time()
        n_weights = len(self._weights_info)
        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else 0

        def _weight_receiver():
            """Generator: receive each weight via NCCL broadcast and yield immediately."""
            for key, shape, dtype in self._weights_info:
                tensor = torch.empty(
                    shape, dtype=dtype, device=get_torch_device().current_device(),
                )
                if is_npu_available:
                    self._weight_sync_group.broadcast(
                        tensor, src=0, stream=get_torch_device().current_stream(),
                    )
                else:
                    collective.broadcast(
                        tensor, src_rank=0, group_name=sync_group_name,
                    )
                yield (key, tensor)

        logger.info(
            "[MCPMegatronAsyncRolloutWorker] rank=%d streaming %d weight "
            "tensors: NCCL recv -> IPC push (one at a time)",
            rank, n_weights,
        )

        self._run_async_safely(
            self.rollout.update_weights(_weight_receiver())
        )

        get_torch_device().empty_cache()

        total_time = time.time() - start_time
        logger.info(
            "[MCPMegatronAsyncRolloutWorker] sync_rollout_weights done: "
            "%d tensors in %.2fs",
            n_weights, total_time,
        )


class MCPMegatronDetachActorWorker(MegatronDetachActorWorker):
    """Megatron DetachActorWorker with debug logging for GPU utilization diagnosis.

    Logs entry/exit of compute_log_prob and update_actor to verify all
    workers in the Megatron parallel group are receiving Ray remote calls.

    Megatron collectives (TP AllReduce, PP send/recv) require all ranks
    to participate. Entry/exit logs make it easy to spot which rank is
    absent or stalled.
    """

    @register(dispatch_mode=Dispatch.ONE_TO_ALL, blocking=False)
    def warmup_nccl_group(self, sync_group_name="actor_rollout"):
        """Dummy broadcast to pre-create the NCCL communicator during init."""
        dummy = torch.zeros(1, device=get_torch_device().current_device())
        if is_npu_available:
            self._weight_sync_group.broadcast(
                dummy, src=0, stream=get_torch_device().current_stream(),
            )
        else:
            collective.broadcast(dummy, src_rank=0, group_name=sync_group_name)

    def _get_actor_params_generator(self):
        _patch_megatron_ep_export_for_local_experts()
        return super()._get_actor_params_generator()

    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def compute_log_prob(self, data):
        """Compute log probabilities with entry/exit GPU memory diagnostics."""
        _patch_megatron_vocab_parallel_entropy_for_memory()
        _patch_megatron_compute_log_prob_for_zero_entropy()
        _patch_megatron_fused_logprob_entropy()
        _patch_gpt_oss_sink_attention()

        if not getattr(self, '_alloc_conf_logged', False):
            _conf = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "<not set>")
            logger.info("[MCPMegatronDetachActorWorker] PYTORCH_CUDA_ALLOC_CONF=%s", _conf)
            self._alloc_conf_logged = True  # pylint: disable=attribute-defined-outside-init

        gc.collect()
        if torch.cuda.is_available():
            get_torch_device().empty_cache()

        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else -1
        device = torch.cuda.current_device() if torch.cuda.is_available() else "N/A"
        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3) if torch.cuda.is_available() else 0
        batch_size = len(data) if hasattr(data, '__len__') else "?"
        logger.info(
            "[MCPMegatronDetachActorWorker] compute_log_prob ENTER: "
            "rank=%d, cuda_device=%s, batch_size=%s, "
            "gpu_alloc=%.2fGiB, offload=%s",
            rank, device, batch_size, alloc_gb, self._is_offload_param,
        )

        start = time.time()
        result = super().compute_log_prob(data)
        elapsed = time.time() - start

        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3) if torch.cuda.is_available() else 0
        logger.info(
            "[MCPMegatronDetachActorWorker] compute_log_prob EXIT: "
            "rank=%d, cuda_device=%s, elapsed=%.2fs, "
            "gpu_alloc=%.2fGiB",
            rank, device, elapsed, alloc_gb,
        )
        return result

    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def update_actor(self, data):
        """Update actor weights with entry/exit rank diagnostics."""
        _patch_megatron_vocab_parallel_entropy_for_memory()
        _patch_megatron_compute_log_prob_for_zero_entropy()
        _patch_megatron_fused_logprob_entropy()
        _patch_gpt_oss_sink_attention()
        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else -1
        device = torch.cuda.current_device() if torch.cuda.is_available() else "N/A"
        batch_size = len(data) if hasattr(data, '__len__') else "?"

        # Clear allocator cache before the peak-memory actor update path.
        gc.collect()
        if torch.cuda.is_available():
            get_torch_device().empty_cache()

        logger.info(
            "[MCPMegatronDetachActorWorker] update_actor ENTER: "
            "rank=%d, cuda_device=%s, batch_size=%s",
            rank, device, batch_size,
        )

        start = time.time()
        original_actor_mini_batch = getattr(self.actor.config, "ppo_mini_batch_size", None)
        data_len = len(data) if hasattr(data, "__len__") else 0
        adjusted_mini_batch = None
        if (
            original_actor_mini_batch
            and data_len > 0
            and data_len % int(original_actor_mini_batch) != 0
        ):
            adjusted_mini_batch = data_len
            logger.warning(
                "[MCPMegatronDetachActorWorker] local batch_size=%s is not divisible by "
                "ppo_mini_batch_size=%s; using one minibatch of size %s for this update",
                data_len, original_actor_mini_batch, adjusted_mini_batch,
            )
            self.actor.config.ppo_mini_batch_size = adjusted_mini_batch
        try:
            result = super().update_actor(data)
        finally:
            if adjusted_mini_batch is not None:
                self.actor.config.ppo_mini_batch_size = original_actor_mini_batch
        elapsed = time.time() - start

        # Sanitize per-worker metrics that DataProto.concat will flatten via
        # list_of_dict_to_dict_of_list. With dynamic_bsz on Megatron, different
        # DP ranks can split into different numbers of micro-batches, producing
        # value lists of different lengths per rank. After concat that becomes
        # ``[[r0_m0, r0_m1, ...], [r1_m0, r1_m1]]`` (inhomogeneous), and verl's
        # ``reduce_metrics`` blows up with::
        #   ValueError: setting an array element with a sequence.
        #   The detected shape was (2,) + inhomogeneous part.
        # Flatten any nested list/array values into a flat numeric list so the
        # downstream ``np.mean / np.max / np.min`` calls work regardless of
        # cross-rank micro-batch count imbalance.
        _flatten_dataproto_metrics_inplace(result)

        logger.info(
            "[MCPMegatronDetachActorWorker] update_actor EXIT: "
            "rank=%d, cuda_device=%s, elapsed=%.2fs",
            rank, device, elapsed,
        )
        return result
