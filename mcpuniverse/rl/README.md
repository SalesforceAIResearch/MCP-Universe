> **Contributor: Ziyang Luo**

# MCP-Universe RL

Reinforcement learning for LLM agents that interact with tools via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). The agent acts inside real tool environments. Each trajectory is a multi-turn conversation where the model makes tool calls, receives results, and continues reasoning until it completes the task or hits the iteration limit. Rewards are computed by task-specific evaluators.

## How It Works

At a high level, training follows the standard online RL loop:

```
Generate trajectories  →  Compute rewards  →  Update model weights  →  repeat
```

Each trajectory is a complete agent episode:

1. The model receives a task instruction and available MCP server list.
2. It generates a reasoning trace and tool calls (e.g. [HarmonyReAct](https://www.notion.so/Unlocking-the-Potential-of-GPT-OSS-with-a-Co-Designed-Agent-Framework-2718397721c0803fbd7fca65072550a3) format).
3. MCP tools are executed; results are appended to the context.
4. Steps 2–3 repeat until the task is done or `max_iterations` is reached.
5. An evaluator checks the final answer and returns a scalar reward.

The training algorithm is **GRPO** (Group Relative Policy Optimization): multiple trajectories are generated per prompt, and advantages are normalized within each group. No learned critic or reward model is needed.

## Key Components

### MCPLoopManager

The core of the rollout pipeline. Drives the multi-turn tool-call loop for a batch of instances in parallel. Supports two rollout modes:

- **Text mode**: calls the model via HTTP API (vLLM/sglang server); works with both Hybrid and Fully Async training.
- **TITO mode** (Token In Token Out) — passes token IDs directly to the vLLM/SGLang engine, skipping redundant tokenization/detokenization. More efficient when the model and rollout engine are co-located.

### MCPRewardManager

Computes rewards using MCP-Universe's built-in evaluators instead of a learned reward model. Evaluators are defined per task in the training data JSON and can check structured outputs, numeric answers, code execution results, etc.

### MCP Transport Modes

Controls how the agent's tool calls reach MCP server processes:


| Mode          | Description                                                                                                                                                                                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `stdio`       | Spawns a fresh MCP server process per trajectory. Simple and isolated; good for most cases.                                                                                                                                                                              |
| `sse`         | Routes tool calls through a shared MCP Gateway. Lower per-call overhead when many trajectories run in parallel.                                                                                                                                                          |
| `docker_pool` | Each trajectory gets its own isolated container from an environment pool (backend: **Docker** or **Apptainer**), running an MCP server inside. Tools execute in a fully isolated, reproducible environment. Useful for stateful tasks where trajectories must not interfere with each other (e.g. filesystem/database tasks). |


### Agent Modes & Formatters

- **Harmony** (`agent_mode: harmony`) — HarmonyReAct agent with `<think>` / tool-call interleaving. Requires `formatter_type: gpt_oss` and a `reasoning` sampling parameter.
- **ReAct** (`agent_mode: react_train`) — standard ReAct-style agent.

Formatters (`gpt_oss`, `qwen3`, `gemma4`) handle model-specific prompt construction and output parsing.

[WIP] More Agent modes and formats will be supported.

## Training Modes

### Hybrid Mode

Actor, Rollout (vLLM), and Critic all share the same GPU pool. The rollout and training phases alternate synchronously each step. Simpler to set up — works on a single GPU.

```
[Rollout phase] → [Training phase] → [Rollout phase] → ...
     vLLM awake        FSDP awake         vLLM awake
```

Entry point: `mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo,`see `[integrations/verl/hybrid/](integrations/verl/hybrid/)`

### Fully Async Mode

Rollouter and Trainer run on **separate GPU pools** and communicate via a message queue. The Rollouter continuously generates trajectories; the Trainer consumes batches and runs PPO updates independently. Eliminates idle GPU time on both sides.

```
Rollouter (Rollout GPUs) ──[MessageQueue]──► Trainer (Training GPUs)
        ▲                                            │
        └──────────── ParameterSynchronizer ─────────┘
                           (NCCL broadcast)
```

After every N training steps, the Trainer broadcasts updated weights to the Rollouter via NCCL. The Rollouter pauses briefly, loads the new weights into its vLLM engine, and resumes.

Entry point: `mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main`, see `[integrations/verl/fully_async/](integrations/verl/fully_async/)`

### Comparison


|                  | Hybrid                          | Fully Async            |
| ---------------- | ------------------------------- | ---------------------- |
| GPU pools        | Shared                          | Separate               |
| Execution        | Synchronous                     | Parallel               |
| Minimum GPUs     | 1                               | 2 (recommended 8, 4+4) |
| GPU utilization  | Lower (rollout/train alternate) | Higher (always busy)   |
| Setup complexity | Simple                          | More involved          |


## Training Data Format

Each training instance is a JSON object:

```json
{
  "instance_id": "task_001",
  "instruction": "Calculate the final value if I invested $25,000 in MSFT...",
  "output_format": {"total value": "[NUMBER]"},
  "mcp_servers": [{"name": "yfinance"}, {"name": "calculator"}],
  "dockerfile_path": "/path/to/Dockerfile",
  "evaluators": [{
    "func": "json",
    "op": "yfinance.check_portfolio_task_output",
    "op_args": {"tickers": ["MSFT"], "start_date": "2023-01-09"},
    "desc": "Check whether the final portfolio value is correct."
  }]
}
```

- `mcp_servers` — which MCP servers the agent can use for this task.
- `dockerfile_path` — Dockerfile for the Docker environment (used with `docker_pool` transport).
- `evaluators` — defines how the agent's final answer is scored.

## Quick Start

```bash
# Hybrid mode
python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo \
    --config-path=integrations/verl/config \
    --config-name=mcp_harmony_tito_example \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json \
    data.val_files=/path/to/val.json

# Fully Async mode
python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path=integrations/verl/config \
    --config-name=mcp_fully_async_harmony_tito_example \
    actor_rollout_ref.model.path=/path/to/model \
    data.train_files=/path/to/train.json \
    data.val_files=/path/to/val.json \
    trainer.n_gpus_per_node=4 \
    rollout.n_gpus_per_node=4

# Multi-node (Fully Async, two pods)
bash integrations/verl/scripts/start_multinode_async.sh
```

### Standalone rollout (evaluation / data generation)

To run rollouts without a trainer — e.g. for evaluation or trajectory collection — drive the engine directly. See the runnable notebooks in [`examples/`](examples/) for end-to-end vLLM / SGLang usage.

```python
from mcpuniverse.rl import RolloutEngine

engine = RolloutEngine.from_config("rollout_config.yaml")
output = await engine.run([{"instruction": "What's the weather in Tokyo?"}])
```

## Directory Structure

```
mcpuniverse/rl/
│
├── __init__.py            # Public API (RolloutEngine, RolloutConfig, RolloutPipeline, ...)
├── runner.py              # RolloutEngine - in-process rollout entry point
│
├── core/                  # Framework-agnostic rollout core
│   ├── config.py          # RolloutConfig and related dataclasses
│   ├── pipeline.py        # RolloutPipeline - three-stage init -> run -> eval
│   ├── rollout.py         # Rollout orchestration helpers
│   ├── trajectory.py      # Trajectory - one multi-turn agent episode
│   ├── types.py           # Core data types (RolloutSample, TokenizedRolloutBatch, ...)
│   ├── env_pool_runtime.py  # Docker / Apptainer environment-pool runtime
│   ├── postprocess.py     # Tokenization + metrics collection
│   ├── trace_logger.py    # JSONL trace logging for trajectory inspection
│   └── formatters/        # Model-specific prompt/output formatters
│       ├── base.py
│       ├── gpt_oss.py     # GPT-OSS / HarmonyReAct format
│       ├── qwen3.py
│       └── gemma4.py
│
├── data/                  # Dataset-prep scripts + sample data
├── examples/              # Runnable notebooks (vLLM / SGLang, text & TITO)
│
└── integrations/
    ├── verl/              # VERL integration (Hybrid + Fully Async PPO)
    └── slime/             # slime integration
```

For detailed documentation on each training mode, see:

- `[integrations/verl/hybrid/README.md](integrations/verl/hybrid/README.md)` — Hybrid mode details
- `[integrations/verl/fully_async/README.md](integrations/verl/fully_async/README.md)` — Fully Async mode details

