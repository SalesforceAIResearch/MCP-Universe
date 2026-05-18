# OpenSeeker Deep Research — RL Training Setup

Fully async GRPO training with MCP agent tool-calling on 8x H200 GPUs.

**Architecture**: 4 rollout GPUs (vLLM, TITO mode) + 4 training GPUs (FSDP2), connected via async message queue with NCCL weight synchronization.

**Agent**: HarmonyReAct with 3 MCP tools (serper-search, jina-scrape-llm-summary, python-code-sandbox), each trajectory running in an isolated Docker container via the env pool.

## Quick Start

```bash
# 1. Build Docker gateway image
docker build -t mcp-universe/gateway:latest -f docker/gateway/Dockerfile .

# 2. Prepare gcloud credentials for Vertex AI auth in containers
cp ~/.config/gcloud/application_default_credentials.json /tmp/gcloud_adc.json
chmod 644 /tmp/gcloud_adc.json

# 3. Export API keys
export SERPER_API_KEY="..."
export JINA_API_KEY="..."
export OPENAI_API_KEY="..."           # LLM-as-judge reward (hle_llm_as_a_judge)
export SUMMARY_LLM_BASE_URL="..."     # Vertex AI endpoint for jina summarization
export SUMMARY_LLM_MODEL_NAME="gemini-2.5-flash"

# 4. Launch training (also prepares train/val splits on first run)
#    Required env vars: MODEL_PATH, OPENSEEKER_INPUT_DIR, and the API keys above.
bash scripts/run_openseeker_training.sh
```

## Code Changes from Upstream

Four files are modified from the upstream MCP-Universe repo. All changes are required for the training to run without crashes.

### a) `docker/gateway/Dockerfile` — Fix MCP Gateway Container

| Change | Reason |
|---|---|
| Base image `python:3.10-slim` (was 3.11) | Python 3.11 + `PYTHONUNBUFFERED=1` causes stray `print()` calls to corrupt the JSON-RPC stdio stream between the gateway and MCP servers |
| Remove `PYTHONUNBUFFERED=1` | Same stdio corruption issue |
| Install `gcloud CLI` | Required by jina-scrape-llm-summary server for Vertex AI authentication via Application Default Credentials |
| Pin `starlette==0.52.1`, `pydantic==2.13.3` | Starlette 0.46.x closes SSE connections prematurely; starlette 1.0+ crashes with cancel scope errors |

### b) `mcpuniverse/rl/integrations/verl/mcp_loop_manager.py` — Fix env_vars/volumes Passthrough

The YAML config defines `env_vars` (API keys) and `volumes` (gcloud credentials) under `mcp_agent.env_pool`, but they weren't reaching the Docker containers due to two issues:

1. **`_parse_mcp_config`** didn't include `env_vars` or `volumes` in the parsed dict — added both fields.
2. **`_acquire_env_for_trajectory`** read `env_vars` from the top-level `env_pool_cfg`, but `EnvPoolConfig` nests them under `resources.env_vars` (via `_env_pool_from_dict` in `config.py`). Fixed to read from `resources_cfg.env_vars` with OmegaConf-to-dict conversion to resolve `${oc.env:...}` interpolations.

### c) `mcpuniverse/rl/integrations/verl/fully_async/mcp_async_trainer.py` — Fix Batch Size Assertion

The async message queue collects trajectories until `total >= required_samples`, but each queue item may contain a variable number of trajectories. The final batch can overshoot (e.g., 287 instead of 256). FSDP's `DataProto.chunk()` requires `len(batch) % n_gpus == 0`, causing an assertion error.

Fix: truncate the assembled batch to the nearest lower multiple of `n_gpus` before passing to the training step.

### d) `mcpuniverse/rl/integrations/verl/fully_async/mcp_async_workers.py` — Fix NCCL Deadlock in Weight Sync

**Problem**: After each PPO update, the trainer broadcasts updated model weights to the rollout workers via `sync_rollout_weights`. The upstream implementation interleaves two types of NCCL operations in a single loop over all weight tensors:

```
for each weight tensor:
    1. FSDP all-gather (FSDP NCCL communicator) — gathers the full parameter from shards across 4 training GPUs
    2. Ray collective broadcast (Ray NCCL communicator) — broadcasts the gathered parameter to rollout GPUs
```

This interleaving creates a cross-communicator dependency: FSDP's NCCL kernels and Ray's NCCL kernels share the same GPU streams. NCCL operations are non-blocking on the GPU — they enqueue work on CUDA streams and return immediately. When two independent NCCL communicators enqueue operations on overlapping streams, the GPU scheduler can form a circular wait: FSDP's all-gather on stream A waits for Ray's broadcast on stream B, while Ray's broadcast waits for the next FSDP all-gather. This deadlock manifests as an indefinite GPU spin-wait with no error output.

**Fix**: Split into two strict sequential phases with a GPU synchronization barrier between them:

```
Phase 1 (FSDP NCCL only):
    for each weight tensor:
        FSDP all-gather → copy to CPU (rank 0 only)
    torch.cuda.synchronize()  # drain all FSDP NCCL work

Phase 2 (Ray NCCL only):
    for each weight tensor:
        rank 0: copy from CPU → GPU
        Ray collective broadcast to all ranks (training + rollout)
```

By never mixing FSDP and Ray NCCL operations in the same phase, we eliminate the cross-communicator circular dependency. The CPU staging between phases is the key — it forces a clean handoff point where all FSDP work completes before any Ray work begins.

The rollout-side receiver (`MCPAsyncRolloutWorker._weight_receiver`) already does plain per-weight Ray broadcasts in the same `_weights_info` order, so it matches without modification.

## Critical Launch Script Overrides

The YAML configs set base parameters, but several Hydra CLI overrides in the launch script are required to prevent OOM and NCCL errors during `compute_log_prob` (the forward pass that recomputes old log probabilities for PPO's importance ratio).

### Memory Problem

After loading the 20B model (FSDP-sharded) + Adam optimizer states on 4 training GPUs, each GPU has only ~21GB free out of 140GB. The `compute_log_prob` forward pass must fit within this budget.

Two memory-intensive operations in the default config:

1. **Logits materialization**: The model's `lm_head` produces `[seq_len, vocab_size]` logits. With vocab_size=131072 and a 128K-token sequence, this tensor alone is `128K × 131K × 4 bytes = 62.5GB` — impossible to fit.

2. **Dynamic micro-batching**: verl's `prepare_dynamic_batch` packs sequences into micro-batches up to `log_prob_max_token_len_per_gpu` total tokens. The default (inherited from `ppo_max_token_len_per_gpu`) packs multiple sequences together, exceeding GPU memory.

### The Overrides

```bash
# --- Solve logits OOM ---
actor_rollout_ref.model.use_fused_kernels=true
++actor_rollout_ref.model.fused_kernel_options.impl_backend=torch
# FusedLinearForPPO fuses lm_head + log_softmax + gather into one op.
# Never materializes the full [seq_len, vocab_size] logits tensor.
# Output is just [seq_len] log_probs + [seq_len] entropy.

# --- Solve micro-batch OOM + FSDP desync ---
actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=false
actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1
# Dynamic batching creates different micro-batch counts per FSDP worker
# (sequences have different lengths → different packing). Worker A does
# 17 forward passes, worker B does 14 → worker B finishes early →
# worker A's 15th forward calls FSDP all-gather → worker B isn't
# participating → 10-minute NCCL timeout.
# Fixed micro_batch_size=1: every worker does exactly batch_size/n_gpus
# forward passes, all synchronized.

# --- Cap sequence length ---
data.max_prompt_length=81920
data.max_response_length=81920
actor_rollout_ref.rollout.prompt_length=81920
actor_rollout_ref.rollout.response_length=81920
actor_rollout_ref.rollout.max_model_len=81920
actor_rollout_ref.actor.ppo_max_token_len_per_gpu=81920
# Sequences longer than 81920 tokens are trimmed. With fused kernels
# and micro_batch_size=1, a single 80K-token forward pass needs ~14GB,
# well within the 21GB free per training GPU.

# --- PPO training micro-batch ---
actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1
# During the PPO forward/backward pass (not compute_log_prob), process
# 1 sequence at a time per GPU to stay within memory budget.
```

### Alternatives Considered

| Approach | Outcome |
|---|---|
| `optimizer_offload=true` (verl built-in) | Frees ~39GB by moving Adam states to CPU. Works for 2 PPO steps, then NCCL timeout on step 3 due to memory fragmentation from repeated CPU↔GPU transfers |
| Manual optimizer offload in `compute_log_prob` | Same fragmentation issue + race condition where workers reload at different speeds |
| `bypass_mode=true` (skip `compute_log_prob`) | Works perfectly but loses the 3-policy PPO setup (uses rollout log_probs as old_log_probs). Standard for async PPO but less precise |
| Liger Kernel (`use_liger=true`) | Not installed in the conda env. `use_fused_kernels` achieves the same effect with verl's built-in FusedLinearForPPO |

## Config File

### `openseeker_deepresearch_async.yaml`

Key values:
- `ppo_mini_batch_size: 256`, `max_parallel_agents: 32`, `max_iterations: 100`
- `staleness_threshold: 1` (rollout pauses if it gets more than one step ahead)
- `n: 8` (GRPO trajectories per prompt)
- `max_pool_size: 35` (Docker container pool ceiling)

## Known Issues

1. **Docker init timeouts**: Under high parallelism (96 agents), some Docker containers take >300s to start, causing agent-level errors. Non-fatal — training continues with fewer trajectories per batch.

2. **`_postprocess` latency**: Varies from 10s (small batch) to 650s (large batch with long sequences). This is CPU-bound log-prob recomputation via vLLM on the rollout GPUs.

3. **`metric_utils.py` empty tensor crash**: `torch.max(valid_adv)` in `src/verl/verl/trainer/ppo/metric_utils.py` crashes when all GRPO advantages are zero (common when the base model gets 0 reward on all trajectories). Not yet patched.

## Monitoring

```bash
# Watch training progress
tail -f outputs/*.log | grep -E "(global_steps|done.*errors|success_rate|OOM|NCCL)"

# Check GPU utilization
watch -n 5 nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader

# Check Docker container pool
docker ps --filter "label=mcp.managed=true" --format "{{.Names}}\t{{.Status}}" | wc -l

# WandB dashboard
# Project: openseeker_deepresearch
# Experiment: harmony_3tools_async
```
