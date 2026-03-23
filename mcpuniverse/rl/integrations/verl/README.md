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
├── config/                    # Hydra configuration files
│   ├── mcp_fully_async.yaml   #   Fully Async mode
│   └── mcp_gptoss_harmony_tito.yaml  #   Hybrid mode
│
├── hybrid/                    # Hybrid training mode
│   ├── mcp_main_ppo.py        #   Hydra entry point
│   └── mcp_trainer.py         #   MCPPPOTrainer (extends RayPPOTrainer)
│
├── fully_async/               # Fully Async training mode
│   ├── mcp_async_main.py      #   Orchestrator entry point
│   ├── mcp_async_trainer.py   #   Queue-consuming PPO Trainer
│   ├── mcp_async_rollouter.py #   Continuous-generation Rollouter
│   ├── mcp_async_workers.py   #   Custom Workers (weight sync)
│   ├── mcp_async_data.py      #   Data classes + batch assembly
│   └── mcp_param_sync.py      #   Parameter synchronizer (NCCL)
│
├── scripts/                   # Operational scripts
│   ├── start_multinode.sh     #   Multi-node Hybrid launcher
│   ├── start_multinode_async.sh  # Multi-node Fully Async launcher
│   ├── run_gpt_oss_multinode_train_tito.sh  # Hybrid training script
│   ├── run_fully_async_train.sh  # Fully Async training script
│   ├── connect_worker.sh      #   Worker node Ray connection
│   └── clean_tiktoken_cache.sh  # Tiktoken cache cleanup
│
├── mcp_loop_manager.py        # Shared: multi-turn tool-call loop (core)
├── mcp_reward_manager.py      # Shared: evaluator-based reward computation
├── mcp_dataset.py             # Shared: JSON dataset loading
├── mcp_backend.py             # Shared: data class definitions
└── utils.py                   # Shared: utilities
```

## Shared Components

- **MCPLoopManager** — Manages the multi-turn tool-call loop for MCP agents. Supports both text (HTTP API) and token-level (TITO) rollout modes.
- **MCPRewardManager** — Computes ground-truth rewards via MCP-Universe evaluators instead of a learned reward model.
- **MCPDataset** — Loads JSON training data containing task instructions, MCP server configs, and evaluator definitions.

## Quick Start

```bash
# Hybrid mode
python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \
    --config-path=config --config-name=mcp_gptoss_harmony_tito \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json

# Fully Async mode
python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path=config --config-name=mcp_fully_async \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json \
    trainer.n_gpus_per_node=4 rollout.n_gpus_per_node=4

# Multi-node
bash scripts/start_multinode.sh       # Hybrid
bash scripts/start_multinode_async.sh  # Fully Async
```

See the READMEs in `hybrid/` and `fully_async/` for detailed documentation.
