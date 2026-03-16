# MCP Hybrid Training Mode

In Hybrid mode, Actor, Rollout (vLLM), and Critic all share the same set of GPUs. Training alternates synchronously between rollout and parameter updates.

## Architecture

```
GPU 0-7 (shared, single resource pool)
┌────────────────────────────────────────────────────────┐
│  Actor (FSDP) + Rollout (vLLM) + Critic (FSDP)         │
│                                                        │
│  Rollout ──► Train ──► Rollout ──► Train ──► ...       │
│  (vLLM      (FSDP      (vLLM      (FSDP                │
│   awake)     awake)      awake)     awake)             │
└────────────────────────────────────────────────────────┘
```

The rollout and training phases alternate via VERL's `CheckpointEngineManager`:

1. `update_weights()` — syncs FSDP weights to vLLM, wakes up vLLM replicas
2. Rollout phase — `MCPLoopManager.generate_sequences()` drives the multi-turn MCP agent loop
3. `sleep_replicas()` — frees vLLM GPU memory for training
4. Training phase — log_prob, advantage estimation, critic update, actor update (PPO)

## Files

```
hybrid/
├── __init__.py        # Exports MCPPPOTrainer
├── mcp_main_ppo.py    # Hydra entry point: Ray init, model loading, worker setup
└── mcp_trainer.py     # MCPPPOTrainer(RayPPOTrainer)
```

### mcp_main_ppo.py

The Hydra entry point. Key responsibilities:

- Initializes Ray cluster via `init_ray()` (handles existing clusters and env vars)
- Loads model, tokenizer, and processor
- Sets up worker classes based on strategy (`fsdp`/`fsdp2`; Megatron not yet supported)
- Creates a single `global_pool` resource pool (all roles share GPUs)
- Instantiates `MCPRewardManager` for both training and validation
- Supports both `MCPDataset` (JSON) and VERL's standard `create_rl_dataset` (parquet)
- Launches `MCPPPOTrainer.init_workers()` + `fit()` inside a Ray `TaskRunner`

### mcp_trainer.py — MCPPPOTrainer

Extends VERL's `RayPPOTrainer`. Key differences:

`**init_workers()**`

- Creates colocated worker groups (actor_rollout, critic, ref, rm) in the shared resource pool
- Initializes `MCPLoopManager` for async rollout mode (`actor_rollout_ref.rollout.mode == "async"`)
- Sets up `CheckpointEngineManager` for FSDP-to-vLLM weight sync

`**fit()` — Main training loop**

1. Optional `val_before_train` validation
2. For each batch:
  - `update_weights()` → `generate_sequences()` → `sleep_replicas()`
  - Compute `response_mask` (fallback; MCPLoopManager usually provides it)
  - Compute rewards via `MCPRewardManager` (reads pre-computed rewards from `non_tensor_batch["rewards"]`)
  - Compute old log probs + entropy
  - Compute reference log probs (if KL is used)
  - Compute values (if critic is used)
  - Compute advantages (supports GAE, GRPO, RLOO)
  - Update critic, then actor
  - Periodic validation and checkpoint saving
3. End-of-epoch validation

`**_validate()`**

- Iterates over `val_dataloader`, builds `DataProto` with `non_tensor_batch`
- Temporarily overrides temperature if `val_llm_config.temperature` differs from training
- Calls `MCPLoopManager.generate_sequences()` with `validate=True`
- Expands `non_tensor_batch` fields to match `val_num_trajectories` for reward computation
- Logs per-sample results, success rate, mean reward

**Advantage estimation**

- For GRPO/RLOO: sets `num_repeat = rollout.n` (group-based advantage using `uid`)
- For GAE: `num_repeat = 1` (standard PPO)
- `MCPLoopManager` sets `uid` in `_postprocess()` so VERL can group trajectories correctly

## Configuration

Uses Hydra configs from `../config/mcp_gptoss_harmony_tito.yaml`. Key sections:

```yaml
actor_rollout_ref:
  model:
    path: /path/to/model
  actor:
    strategy: fsdp          # fsdp or fsdp2 (megatron not yet supported)
    loss_agg_mode: token_mean
  rollout:
    mode: async             # "async" enables MCPLoopManager
    n: 4                    # trajectories per prompt (for GRPO)

trainer:
  n_gpus_per_node: 8        # all GPUs in the shared pool
  nnodes: 1
  total_epochs: 3
  test_freq: 10             # validate every N steps
  save_freq: 50
  val_before_train: true

algorithm:
  adv_estimator: grpo       # grpo, rloo, gae
  use_kl_in_reward: false

mcp_agent:
  agent_mode: harmony
  rollout_mode: text        # text or token (TITO)
  mcp_transport: stdio      # stdio, sse, or docker_pool
  max_iterations: 12
  max_parallel_agents: 16
```

## Usage

```bash
python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \
    --config-path=config \
    --config-name=mcp_gptoss_harmony_tito \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json \
    data.val_files=/path/to/val.json
```

Multi-node:

```bash
bash scripts/start_multinode.sh
```

