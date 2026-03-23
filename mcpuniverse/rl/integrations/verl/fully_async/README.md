> **Contributor: Ziyang Luo**

# MCP Fully Async Training Mode

Fully Async mode completely decouples the Rollouter and Trainer onto separate GPU pools, communicating via a MessageQueue. The Rollouter continuously generates MCP agent trajectories and pushes them to the queue; the Trainer pulls batches from the queue for PPO updates. Both run in parallel, eliminating idle GPU time.

## Architecture

```
MCPFullyAsyncRollouter (Rollout GPUs)        MCPFullyAsyncTrainer (Training GPUs)
  │                                            │
  ├─ MCPLoopManager (text/TITO)                ├─ Pull batches from MessageQueue
  ├─ Per-instance async tasks                  ├─ MCPRewardManager
  ├─ Partial rollout (cancel on pause)         ├─ PPO: log_prob -> advantage -> update
  └─ Push to MessageQueue ──────────────────>  └─ Trigger ParameterSynchronizer
                                                    │
       ┌────────────────────────────────────────────┘
       v
  ParameterSynchronizer (NCCL)
    ├─ Pause rollouter
    ├─ Broadcast weights: Trainer -> Rollouter
    └─ Resume rollouter
```

### Weight Sync Flow

The two-engine problem: rollout GPUs run two processes — a `DetachAsyncRolloutWorker` (with `ServerAdapter` client stub, no local vLLM engine) and a separate `vLLMHttpServerForPartial` Ray actor (with its own `AsyncLLM` engine). Upstream `sync_rollout_weights()` fails because `ServerAdapter` has no `inference_engine`.

Solution:
```
Actor FSDP → full_tensor() → NCCL broadcast → MCPAsyncRolloutWorker
  → ServerAdapter.update_weights() → CUDA IPC → vLLMHttpServerForPartial
  → model.load_weights()
```

- `MCPAsyncRolloutWorker` overrides `sync_rollout_weights()`: receives NCCL broadcast, pushes to vLLM server via `ServerAdapter.update_weights()` (CUDA IPC)
- `MCPParameterSynchronizer` overrides `sync_weights()`: performs the actual NCCL sync call

## Files

```
fully_async/
├── __init__.py              # Lazy imports, exports public API
├── mcp_async_main.py        # Orchestrator: wires Rollouter + Trainer + MessageQueue + ParamSync
├── mcp_async_rollouter.py   # MCPFullyAsyncRollouter — continuous trajectory generation
├── mcp_async_trainer.py     # MCPFullyAsyncTrainer — queue-consuming PPO pipeline
├── mcp_async_workers.py     # MCPDetachActorWorker, MCPAsyncRolloutWorker (weight sync overrides)
├── mcp_async_data.py        # MCPRolloutSample, padding helpers, assemble_mcp_training_batch
├── mcp_param_sync.py        # MCPParameterSynchronizer (NCCL broadcast)
└── README.md                # This file
```

### mcp_async_main.py — Orchestrator

Entry point for Fully Async training. Responsibilities:
- Parses Hydra config, initializes Ray cluster
- Creates separate resource pools for Trainer GPUs and Rollout GPUs
- Instantiates `MCPFullyAsyncTrainer` and `MCPFullyAsyncRollouter` as Ray actors
- Sets up `MCPParameterSynchronizer` for NCCL weight broadcast
- Manages the training loop: signals rollouter to start/pause, triggers param sync after N training steps
- Handles validation (can be done by either rollouter or trainer, controlled by `use_trainer_do_validate`)

### mcp_async_rollouter.py — MCPFullyAsyncRollouter

A Ray actor that continuously generates trajectories:
- Initializes `MCPLoopManager` with `hybrid_engine=False` and `server_addresses` (vLLM HTTP endpoints)
- Runs async tasks per instance, each producing an `MCPRolloutSample`
- Pushes completed samples to the shared MessageQueue
- Supports `partial_rollout`: cancels in-progress generation when paused for parameter sync
- Tracks param version per sample for staleness detection

### mcp_async_trainer.py — MCPFullyAsyncTrainer

A Ray actor that consumes batches from the queue:
- Pulls `require_batches` mini-batches per training step
- Calls `assemble_mcp_training_batch()` to concatenate samples with re-padding
- Runs the full PPO pipeline: log_prob → advantage → critic update → actor update
- Triggers `MCPParameterSynchronizer` every `trigger_parameter_sync_step` steps
- Manages checkpointing and WandB logging

### mcp_async_workers.py — Custom Workers

**MCPDetachActorWorker**: Extends VERL's `FSDPActorWorker`. Used for the training-side actor. No special overrides beyond proper initialization.

**MCPAsyncRolloutWorker**: Extends VERL's `DetachAsyncRolloutWorker`. Key override:
- `sync_rollout_weights()`: Receives NCCL broadcast from trainer, then pushes weights to vLLM HTTP server via `ServerAdapter.update_weights()` (CUDA IPC transfer)
- Uses COLOCATED mode with `load_format=auto` (not `dummy`) for initial weight loading

### mcp_async_data.py — Data Classes & Batch Assembly

**MCPRolloutSample**: Wraps a single instance's rollout output (DataProto + metadata: param_version, processing_time, instance_id).

**Padding helpers** (`_left_pad`, `_right_pad`, `_lr_pad`): Different `generate_sequences()` calls produce DataProtos with different seq_lens (dynamic padding). Before `DataProto.concat()`, they must be re-padded to uniform dimensions:
- Prompts: left-padded to `max_prompt_len`
- Responses + response_mask: right-padded to `max_response_len`
- Full-seq tensors (input_ids, attention_mask, position_ids): left+right padded so the prompt/response split point stays aligned

**`assemble_mcp_training_batch()`**: Concatenates multiple `MCPRolloutSample` objects:
1. Filters out failed rollouts (null data)
2. Re-pads via `_repad_data_protos()`
3. Reconciles conflicting `meta_info` keys across samples
4. `DataProto.concat()` into a single batch
5. Recomputes `response_mask` if missing
6. Adds async metadata: param versions, processing time stats, staleness info

### mcp_param_sync.py — MCPParameterSynchronizer

Extends VERL's `ParameterSynchronizer`. Key override:
- `sync_weights()`: Performs the actual NCCL broadcast (upstream has it commented out)
- Coordinates pause/resume of the rollouter during weight sync

## Training Data Format

JSON file where each entry contains:

```json
{
  "instance_id": "yf_train_0001",
  "category": "financial_analysis",
  "instruction": "Calculate the final value if I invested $25,000 in MSFT...",
  "output_format": {"total value": "[NUMBER]"},
  "dockerfile_path": "/path/to/Dockerfile.base",
  "mcp_servers": [{"name": "yfinance"}, {"name": "calculator"}],
  "evaluators": [{
    "func": "json",
    "op": "yfinance.check_portfolio_task_output",
    "op_args": {"tickers": ["MSFT"], "start_date": "2023-01-09", ...},
    "desc": "Whether the final value and total percentage return are correct."
  }]
}
```

Fields:
- `instance_id` — unique identifier
- `instruction` — task instruction (concatenated with `output_format` if present)
- `output_format` — expected output structure (optional)
- `dockerfile_path` — Dockerfile for Docker environment (`docker_pool` transport)
- `mcp_servers` — list of MCP servers by registered name
- `evaluators` — evaluator configs for reward computation (`func` type + `op` function + `op_args`)

## Key Configuration

Default config: `../config/mcp_fully_async.yaml`

### async_training

```yaml
async_training:
  trigger_parameter_sync_step: 1  # sync weights every N training steps (higher = more off-policy)
  require_batches: 1              # mini-batches to pull per training step
  staleness_threshold: 1          # max allowed stale sample ratio
  partial_rollout: true           # cancel in-progress trajectories on pause
  use_trainer_do_validate: false  # who runs validation (false = rollouter)
```

### mcp_agent

```yaml
mcp_agent:
  agent_mode: harmony           # harmony, react_train, etc.
  rollout_mode: text            # text (HTTP API) or token (TITO)
  mcp_transport: stdio          # stdio, sse, or docker_pool
  num_trajectories: 1           # per prompt (GRPO needs > 1)
  max_iterations: 12            # max tool-call rounds per trajectory
  max_parallel_agents: 16       # concurrent MCP agent tasks
  llm_config:
    model_name: /path/to/model
    temperature: 0.7
  val_llm_config:
    temperature: 0.0            # greedy for validation
```

### GPU Allocation

Trainer and Rollouter use **separate GPU pools**:

```yaml
trainer:
  n_gpus_per_node: 4    # GPUs for PPO gradient updates
  nnodes: 1

rollout:
  n_gpus_per_node: 4    # GPUs for vLLM inference
  nnodes: 1
```

Example on 8-GPU machine: GPUs 0-3 for Trainer, GPUs 4-7 for Rollouter.

### Checkpointing

```yaml
trainer:
  save_freq: 5                          # save every N param_versions
  default_local_dir: checkpoints/mcp_async
  resume_mode: auto                     # auto, disable, or resume_path
```

Checkpoints include: actor weights, critic weights (if enabled), dataloader state.
Training auto-resumes from the latest checkpoint when `resume_mode: auto`.

## Usage

```bash
# Single node
python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path=config \
    --config-name=mcp_fully_async \
    actor_rollout_ref.model.path=/path/to/model \
    mcp_agent.llm_config.model_name=/path/to/model \
    data.train_files=/path/to/train.json \
    data.val_files=/path/to/val.json \
    trainer.n_gpus_per_node=4 \
    rollout.n_gpus_per_node=4

# Multi-node
python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path=config \
    --config-name=mcp_fully_async \
    actor_rollout_ref.model.path=/path/to/model \
    mcp_agent.llm_config.model_name=/path/to/model \
    data.train_files=/path/to/train.json \
    trainer.n_gpus_per_node=4 trainer.nnodes=2 \
    rollout.n_gpus_per_node=4 rollout.nnodes=2

# Or use the one-click script
bash scripts/start_multinode_async.sh
```

## FAQ

**Q: What does `staleness_threshold` control?**
Higher values allow more stale samples (greater off-policy degree). Start with 1; lower it if training becomes unstable.

**Q: Should `partial_rollout` be enabled?**
Enabling it cancels unfinished trajectories during parameter sync, reducing pause time but wasting already-spent compute. Recommended when trajectories are long (> 1 min).

**Q: Minimum GPU requirement?**
2 GPUs (1 Trainer + 1 Rollouter). Recommended 8 (4+4). Rollouter GPU count depends on model size (vLLM tensor parallelism).
