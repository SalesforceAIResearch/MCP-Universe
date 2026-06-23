> **Contributor: Ziyang Luo**

# VERL Integration for MCP-Universe

Integrates MCP-Universe agent training with the [VERL](https://github.com/volcengine/verl) framework for distributed PPO training of LLM agents that interact with tools via MCP (Model Context Protocol).

## Training Modes

| Feature | Hybrid | Fully Async |
|---------|--------|-------------|
| GPU allocation | Shared | Separate pools |
| Execution | Synchronous (rollout then train) | Fully asynchronous (parallel) |
| Trainer waits for rollout | Yes | No |
| Minimum GPUs | 1 | 2 |

## Directory Structure

```
verl/
├── config/                    # Hydra configs (copy an *_example.yaml and edit)
│   ├── mcp_harmony_tito_example.yaml              #   Hybrid template (gpt-oss + TITO)
│   ├── mcp_fully_async_harmony_tito_example.yaml  #   Fully Async template (gpt-oss + TITO)
│   └── ...                                        #   + Megatron / Gemma variants
│
├── hybrid/                    # Hybrid training mode
│   ├── mcp_main_ppo.py        #   Hydra entry point
│   ├── mcp_trainer.py         #   MCPPPOTrainer (extends RayPPOTrainer)
│   └── mcp_workers.py         #   Hybrid FSDP / Megatron worker subclasses
│
├── fully_async/               # Fully Async training mode
│   ├── mcp_async_main.py      #   Orchestrator entry point
│   ├── mcp_async_trainer.py   #   Queue-consuming PPO Trainer
│   ├── mcp_async_rollouter.py #   Continuous-generation Rollouter
│   ├── mcp_async_workers.py   #   FSDP workers (weight sync)
│   ├── mcp_megatron_async_workers.py  # Megatron workers (weight sync)
│   ├── mcp_async_data.py      #   Data classes + batch assembly
│   ├── mcp_async_queue.py     #   Queue consumption helpers
│   └── mcp_param_sync.py      #   Parameter synchronizer (NCCL)
│
├── scripts/                   # Launch / operational scripts (single & multi-node)
│
├── mcp_loop_manager.py        # Shared: multi-turn tool-call loop (core)
├── mcp_reward_manager.py      # Shared: evaluator-based reward computation
├── mcp_dataset.py             # Shared: JSON dataset loading
├── mcp_config_adapter.py      # Shared: veRL config -> RolloutConfig adapter
├── data_proto_adapter.py      # Shared: DataProto <-> rollout-type adapters
├── data_proto_padding.py      # Shared: DataProto padding helpers
├── mcp_batch_sizing.py        # Shared: batch-sizing helpers
├── mcp_log_prob_entropy.py    # Shared: memory-aware log-prob / entropy
├── mcp_fsdp_patches.py        # Shared: FSDP runtime patches
├── mcp_megatron_patches.py    # Shared: Megatron runtime patches
├── async_bridge.py            # Shared: asyncio / event-loop bridge
└── utils.py                   # Shared: utilities
```

## Shared Components

- **MCPLoopManager** — Manages the multi-turn tool-call loop for MCP agents. Supports both text (HTTP API) and token-level (TITO) rollout modes.
- **MCPRewardManager** — Computes ground-truth rewards via MCP-Universe evaluators instead of a learned reward model.
- **MCPDataset** — Loads JSON training data containing task instructions, MCP server configs, and evaluator definitions.
- **data_proto_adapter** — Converts veRL `DataProto` batches to root `RolloutSample` objects and converts neutral `TokenizedRolloutBatch` results back to `DataProto`.

## Quick Start

```bash
# Hybrid mode
python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \
    --config-path=config --config-name=mcp_harmony_tito_example \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json

# Fully Async mode
python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path=config --config-name=mcp_fully_async_harmony_tito_example \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json \
    trainer.n_gpus_per_node=4 rollout.n_gpus_per_node=4

# Multi-node
bash scripts/start_multinode.sh       # Hybrid
bash scripts/start_multinode_async.sh  # Fully Async
```

See the READMEs in `hybrid/` and `fully_async/` for detailed documentation.

## Inference Backend (vLLM or SGLang)

Both training modes support **vLLM** (default) and **SGLang** for the
inference / rollout side. Switching backends does NOT require code changes,
only one config field + one env var.

### Via config

```yaml
# config/mcp_*.yaml
actor_rollout_ref:
  rollout:
    name: vllm   # or "sglang"
```

### Via launch scripts (`BACKEND=` env var)

The 4 main launch scripts (`run_gpt_oss_multinode_train_tito[_megatron].sh`,
`run_fully_async[_megatron]_train.sh`) accept ``BACKEND``:

```bash
# Default vLLM
bash scripts/start_multinode_async.sh

# Switch to SGLang
BACKEND=sglang bash scripts/start_multinode_async.sh
```

Launch scripts set ``VLLM_USE_V1=1`` for vLLM and unset it for SGLang, then
pass ``actor_rollout_ref.rollout.name=${BACKEND}`` to the Hydra entry point.

### Prerequisites for `BACKEND=sglang`

SGLang's `sgl_kernel` (the C++ extension that holds the per-architecture
custom CUDA ops) **dynamically links `libnuma.so.1`**. If this system
library is missing, the very first SGLang Engine import inside the Ray
rollout worker fails with::

    ImportError: libnuma.so.1: cannot open shared object file: No such file or directory
    [sgl_kernel] CRITICAL: Could not load any common_ops library!

The cluster image typically does NOT ship `libnuma1`, so install it on
**every node that runs a Ray worker** (both trainer and rollout pools).

```bash
# Debian / Ubuntu (mcp3 base image)
sudo apt-get update && sudo apt-get install -y libnuma1

# RHEL / CentOS
sudo yum install -y numactl-libs
```

Verify before launching::

    ldconfig -p | grep libnuma   # should print at least libnuma.so.1
    python -c "from sglang.srt.entrypoints.engine import Engine; print('ok')"
    python -c "from verl.experimental.fully_async_policy.sglang_rollout.sglang_async_server import FullyAsyncSGLangReplica; print('ok')"

Other SGLang env requirements (already satisfied in mcp3 env at
sglang==0.5.9, see `pyproject.toml` for pins): a CUDA-matched `sgl_kernel`
prebuilt for your GPU compute capability (SM90 / Hopper on this cluster).
Major version skew between `sglang` and `sgl_kernel` causes the same
`Could not load any common_ops` error; resolution is `pip install --upgrade
sgl_kernel` from the sglang index.

### What works on each backend

| Path | vLLM | SGLang | Notes |
|------|:---:|:---:|---|
| Fully-async rollouter + trainer | ✓ | ✓ | Same Ray actor dispatch; backend chosen by ``rollout.name`` |
| **Hybrid trainer (TITO)** | ✓ | **✗ (rejected at launch)** | **See "Hybrid + SGLang is unsupported" below** |
| NCCL → IPC weight sync | ✓ | ✓ | ``ServerAdapter.update_weights(weights: Generator[tuple[str, torch.Tensor], ...], **kwargs)`` — bit-identical signature on both backends |
| TITO prompt_ids on the wire | list[int] | list[int] | Despite veRL's misleading ``SGLangHttpServer.generate(prompt_ids: torch.Tensor)`` type hint, SGLang's ``GenerateReqInput`` uses ``isinstance(input_ids[0], int)`` to detect single vs batch — a tensor breaks that check. ``TITOLLMWrapper._call_ray`` always sends ``list[int]`` for both backends. See ``tests/llm/test_tito_wrapper_ray_marshalling.py`` for the regression contract. |
| Standalone ``RolloutEngine`` / notebook (token mode, no veRL) | ``AsyncVLLMEngine`` | ``AsyncSGLangEngine`` | Same async ``generate`` contract |

### Hybrid + SGLang is unsupported (use fully_async instead)

Running ``BACKEND=sglang`` with ``run_gpt_oss_multinode_train_tito[_megatron].sh``
exits with::

    ERROR: BACKEND=sglang is not supported in hybrid mode.

Why we hard-block this combination:

- veRL implements **colocated workers only for vLLM**: in hybrid mode
  ``MCPHybridFSDPActorRolloutRefWorker`` carries an in-process
  ``inference_engine`` attribute that points at the same model class
  the actor is training. vLLM's ``update_weights_from_ipc`` then rebuilds
  the IPC handle in-place and replaces vLLM's weight tensor with a view
  on the actor's bf16 tensor — **zero extra GPU memory**.
- SGLang has no colocated worker upstream. It always runs as a
  **standalone HTTP server actor** in its own process and CUDA context.
  ``actor.rollout`` is a ``ServerAdapter`` HTTP client, not an
  in-process engine. So the model is loaded **twice** on the same GPU:
  once for the actor (Megatron / FSDP), once for SGLang (~40 GiB at
  bf16 for gpt-oss-20b).
- On top of the double-load, ``update_weights`` on the SGLang side runs
  ``bridge.stream_weights_megatron_to_hf → maybe_modify_converted_hf_weight
  → torch.cat(...)`` on the **actor's** GPU to merge mcore TP/EP shards
  into HF format before bucketing into ServerAdapter. With SGLang already
  squatting on the GPU (gpu_memory_utilization ≈ 0.6 × 140 GiB = 84 GiB)
  this 1 GiB transient ``torch.cat`` deterministically OOMs at the very
  first ``update_weights`` call (e.g. ``val_before_train=true``).
- ``sleep`` and ``release_memory_occupation`` cannot avoid this: SGLang
  ``sleep`` only releases KV cache, not weights; vLLM ``sleep_level=2``
  fully unloads weights — another reason vLLM hybrid works.

The fully-async path bypasses all of this by giving actor and rollout
**separate GPU pools**, so the double-load is no longer "on the same
GPU". Switch with one env var::

    BACKEND=sglang bash scripts/start_multinode_async.sh
    # which dispatches to run_fully_async_train.sh or
    # run_fully_async_megatron_train.sh based on your config.

If upstream veRL ever adds ``SGLangColocatedRolloutWorker``, this
restriction can be lifted — search ``_normalize_hybrid_rollout_lifecycle_config``
in ``hybrid/mcp_trainer.py`` for the hard-stop to remove.

### MCP-specific lifecycle config (backend-neutral key names)

These two MCP-private config keys were renamed when SGLang support landed.
Legacy names still work (with a one-time deprecation warning logged on read):

| New name (preferred) | Legacy name (still honored) |
|---|---|
| ``mcp_agent.direct_rollout_sleep_handoff`` | ``mcp_agent.direct_vllm_sleep_handoff`` |
| ``mcp_agent.suspend_rollout_workers_during_postprocess`` | ``mcp_agent.suspend_vllm_workers_during_postprocess`` |

Both apply to vLLM and SGLang fast-paths (``_ROLLOUT_FAST_PATH_BACKENDS`` in
``hybrid/mcp_trainer.py``).
