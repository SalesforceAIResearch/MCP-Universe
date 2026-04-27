# MCP-Universe paper benchmark

This directory is the **isolated bundle** for the tasks and runners described in the [MCP-Universe paper](https://arxiv.org/abs/2508.14704).

## Layout

- **Runner YAML** — one file per category at this directory root (for example `web_search.yaml`, `multi_server.yaml`).
- **`task_configs/`** — JSON task definitions grouped by category (`web_search/`, `multi_server/`, …).
- **`server_list.json`** — MCP server definitions used when you run benchmarks without supplying your own `MCPManager`.
- **`evaluators/`** — `compare_func` implementations for this suite. They register when :mod:`mcpuniverse.benchmark.hooks` is loaded (via :class:`mcpuniverse.benchmark.task.Task` or :class:`mcpuniverse.benchmark.runner.BenchmarkRunner`), same pattern as MCPMark.
- **`cleanups.py`** — paper-suite `cleanup_func` handlers (GitHub, Notion, weather/maps dummies), registered via the same :mod:`mcpuniverse.benchmark.hooks` import path.

`BenchmarkRunner` resolves configs such as `mcpuniverse/web_search.yaml` to `mcpuniverse/benchmark/mcpuniverse/web_search.yaml`, infers this folder as the bundle root, and resolves each task path under `task_configs/`.

## Running

From the repository root (with dependencies and environment variables set as in the main README):

```python
from mcpuniverse.benchmark.runner import BenchmarkRunner

runner = BenchmarkRunner("mcpuniverse/web_search.yaml")
# await runner.run()
```

Use the YAML basename under `benchmark/mcpuniverse/`; legacy paths under `benchmark/configs/` are still resolved when present.
