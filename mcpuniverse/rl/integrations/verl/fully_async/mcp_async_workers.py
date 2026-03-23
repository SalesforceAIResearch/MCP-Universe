# pylint: disable=too-many-ancestors

"""
Custom worker classes for MCP fully async training.

MCPAsyncRolloutWorker overrides sync_rollout_weights to push weights
to the inference server via ServerAdapter.update_weights() (CUDA IPC),
since the standard get_inference_model() fails for ServerAdapter
(ServerAdapter is a client stub with no local inference engine).

Supports both vLLM and SGLang backends — both implement the same
ServerAdapter.update_weights() interface (BaseRollout).

Weight sync flow:
  1. Actor workers broadcast FSDP weights via NCCL collective
  2. MCPAsyncRolloutWorker receives each tensor via NCCL and immediately
     yields it to ServerAdapter.update_weights() (streaming, not accumulating)
  3. ServerAdapter pushes each bucket to the inference server via CUDA IPC

Memory optimization:
  - Weights are streamed one-at-a-time through a generator, never accumulated.
    This uses ~100MB (1 tensor + IPC buffer) instead of ~42GB (all tensors).
  - The FSDP model shard (~5GB) loaded by init_model() is freed after init
    since inference goes through the server, not the FSDP model.
"""

import gc
import logging
import os
import time

import torch
from ray.util.collective import collective

from verl.experimental.fully_async_policy.fsdp_workers import (
    DetachActorWorker,
    DetachAsyncRolloutWorker,
)
from verl.single_controller.base.decorator import Dispatch, make_nd_compute_dataproto_dispatch_fn, register
from verl.utils.device import get_torch_device, is_npu_available

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("VERL_LOGGING_LEVEL", "WARN"))


class MCPAsyncRolloutWorker(DetachAsyncRolloutWorker):
    """Rollout worker that syncs weights to inference servers via ServerAdapter.

    In fully async mode, DetachAsyncRolloutWorker's ``self.rollout`` is a
    ``ServerAdapter`` (client stub), NOT a local inference engine.
    The upstream ``sync_rollout_weights()`` calls
    ``get_inference_model(self.rollout)`` which fails because ServerAdapter
    has no ``inference_engine`` attribute.

    This override:
      - Streams weights via a generator: NCCL recv → yield → IPC push,
        one tensor at a time (never accumulates all weights in GPU memory)
      - Pushes to the inference server via ServerAdapter.update_weights()
        which uses CUDA IPC / shared memory to transfer to the server process

    Works with both vLLM and SGLang ServerAdapter implementations.
    """

    @register(dispatch_mode=Dispatch.ONE_TO_ALL)
    def free_fsdp_model(self):
        """Free the unused FSDP model shard to reclaim GPU memory.

        In fully async mode, inference goes through the inference server
        (via ServerAdapter), not through the FSDP model.  The FSDP model
        is loaded by init_model() but never used afterward, wasting ~5GB
        per rollout GPU.  Call this after init_model() completes.
        """
        # init_model() loads the FSDP shard only to populate _weights_info
        # (weight name/shape/dtype metadata for NCCL receive buffers).
        # Once extracted, the shard itself is never needed again.
        freed = []
        for attr in ("actor_module_fsdp", "actor_module"):
            if hasattr(self, attr) and getattr(self, attr) is not None:
                setattr(self, attr, None)
                freed.append(attr)
        gc.collect()
        get_torch_device().empty_cache()

        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else 0
        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3)
        print(
            f"[MCPAsyncRolloutWorker] rank={rank} freed FSDP model "
            f"({', '.join(freed) or 'nothing to free'}), "
            f"GPU allocated: {alloc_gb:.2f} GiB"
        )

    # blocking=False: lets the caller overlap other work on the actor side.
    # ONE_TO_ALL: every rollout worker must participate in NCCL broadcast.
    @register(dispatch_mode=Dispatch.ONE_TO_ALL, blocking=False)
    def sync_rollout_weights(self, sync_group_name="actor_rollout"):
        """Stream weights from actor workers via NCCL to inference server via IPC.

        Instead of accumulating all weight tensors in GPU memory (which would
        use ~42GB), we use a generator that receives one tensor via NCCL and
        immediately yields it to ServerAdapter.update_weights().  The IPC
        layer copies each tensor into a 2GB bucket buffer and flushes when
        full.  This way we only hold 1 weight tensor + 1 IPC buffer at a time.
        """
        assert self._is_rollout and not self.config.hybrid_engine
        # _weights_info is populated by init_model() from the FSDP shard;
        # each entry is (name, shape, dtype) used to allocate NCCL recv buffers.
        assert hasattr(self, "_weights_info") and self._weights_info is not None

        start_time = time.time()
        n_weights = len(self._weights_info)
        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else 0

        def _weight_receiver():
            """Generator: receive each weight via NCCL broadcast and yield immediately.

            Using a generator (not a list) ensures only one tensor lives on GPU
            at a time. The caller (ServerAdapter) drains the generator and copies
            each tensor into an IPC bucket before requesting the next one.
            """
            for key, shape, dtype in self._weights_info:
                tensor = torch.empty(
                    shape, dtype=dtype, device=get_torch_device().current_device(),
                )
                if is_npu_available:
                    # NPU uses a custom sync group instead of Ray collective.
                    self._weight_sync_group.broadcast(
                        tensor, src=0, stream=get_torch_device().current_stream(),
                    )
                else:
                    collective.broadcast(
                        tensor, src_rank=0, group_name=sync_group_name,
                    )
                yield (key, tensor)

        print(
            f"[MCPAsyncRolloutWorker] rank={rank} streaming {n_weights} weight "
            f"tensors: NCCL recv → IPC push (one at a time)"
        )

        # _run_async_safely runs the async ServerAdapter.update_weights() in a
        # synchronous context. ServerAdapter drains the generator via async for,
        # copying each tensor into a ~2GB IPC bucket and flushing when full.
        self._run_async_safely(
            self.rollout.update_weights(_weight_receiver())
        )

        get_torch_device().empty_cache()

        total_time = time.time() - start_time
        print(
            f"[MCPAsyncRolloutWorker] sync_rollout_weights done: "
            f"{n_weights} tensors in {total_time:.2f}s"
        )


class MCPDetachActorWorker(DetachActorWorker):
    """DetachActorWorker with debug logging for GPU utilization diagnosis.

    Logs entry/exit of compute_log_prob and update_actor to verify all
    workers in the FSDP group are receiving and executing Ray remote calls.

    FSDP collectives (AllReduce/AllGather) require all ranks to participate.
    If Ray dispatch misses any worker, the remaining ranks block indefinitely
    with no error output. Entry/exit logs make it easy to spot which rank is
    absent or stalled.
    """

    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def compute_log_prob(self, data):
        """Compute log probabilities with entry/exit GPU memory diagnostics."""
        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else -1
        device = torch.cuda.current_device() if torch.cuda.is_available() else "N/A"
        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3) if torch.cuda.is_available() else 0
        batch_size = len(data) if hasattr(data, '__len__') else "?"
        print(
            f"[MCPDetachActorWorker] compute_log_prob ENTER: "
            f"rank={rank}, cuda_device={device}, batch_size={batch_size}, "
            f"gpu_alloc={alloc_gb:.2f}GiB, offload={self._is_offload_param}",
            flush=True,
        )

        start = time.time()
        result = super().compute_log_prob(data)
        elapsed = time.time() - start

        alloc_gb = torch.cuda.memory_allocated() / (1024 ** 3) if torch.cuda.is_available() else 0
        print(
            f"[MCPDetachActorWorker] compute_log_prob EXIT: "
            f"rank={rank}, cuda_device={device}, elapsed={elapsed:.2f}s, "
            f"gpu_alloc={alloc_gb:.2f}GiB",
            flush=True,
        )
        return result

    @register(dispatch_mode=make_nd_compute_dataproto_dispatch_fn(mesh_name="actor"))
    def update_actor(self, data):
        """Update actor weights with entry/exit rank diagnostics."""
        rank = torch.distributed.get_rank() if torch.distributed.is_initialized() else -1
        device = torch.cuda.current_device() if torch.cuda.is_available() else "N/A"
        batch_size = len(data) if hasattr(data, '__len__') else "?"
        print(
            f"[MCPDetachActorWorker] update_actor ENTER: "
            f"rank={rank}, cuda_device={device}, batch_size={batch_size}",
            flush=True,
        )

        start = time.time()
        result = super().update_actor(data)
        elapsed = time.time() - start

        print(
            f"[MCPDetachActorWorker] update_actor EXIT: "
            f"rank={rank}, cuda_device={device}, elapsed={elapsed:.2f}s",
            flush=True,
        )
        return result
