# W&D: Scaling Parallel Tool Calling for Efficient Deep Research Agents

Reproduce results from the paper [**W&D: Scaling Parallel Tool Calling for Efficient Deep Research Agents**](https://arxiv.org/pdf/2602.07359) using this benchmark and configuration suite.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Data Preparation](#data-preparation)
- [Tool calling setup](#tool-calling-setup)
- [Running the Benchmark](#running-the-benchmark)
- [Model Configuration](#model-configuration)
- [Tool Calling & Scheduler](#tool-calling--scheduler)

---

## Quick Start

1. **Prepare data** for your target dataset (see [Data Preparation](#data-preparation)).
2. **Run the benchmark** with a config from `mcpuniverse/benchmark/configs/deepresearch/configs/<dataset>/` (see [Running the Benchmark](#running-the-benchmark)).

Pre-built configs are available under `mcpuniverse/benchmark/configs/deepresearch/configs/` for:

| Dataset     | Directory    | Example configs                                      |
|------------|--------------|------------------------------------------------------|
| BrowseComp | `configs/browsecomp/` | `agent_wide_research_bc_gpt5.yaml`, `_gemini3pro.yaml`, `_claude45sonnet.yaml` |
| GAIA       | `configs/gaia/`      | `agent_wide_research_gaia_gpt5.yaml`, …             |
| HLE        | `configs/hle/`      | `agent_wide_research_hle_gpt5.yaml`, …              |

---

## Data Preparation

From the **repository root**, run:

```bash
# BrowseComp
python3 mcpuniverse/benchmark/configs/deepresearch/prepare_deep_research_data.py \
  --dataset browse_comp \
  --tools serper-search,jina-scrape-llm-summary \
  --exclude_output_format

# GAIA
python3 mcpuniverse/benchmark/configs/deepresearch/prepare_deep_research_data.py \
  --dataset gaia \
  --tools serper-search,jina-scrape-llm-summary \
  --exclude_output_format

# HLE (includes code sandbox)
python3 mcpuniverse/benchmark/configs/deepresearch/prepare_deep_research_data.py \
  --dataset hle \
  --tools serper-search,jina-scrape-llm-summary,python-code-sandbox \
  --exclude_output_format
```

---

## Tool calling setup

Copy the environment template and set the variables needed by the tools:

```bash
cp .env.example .env
```

Then configure the following in `.env` (or your shell) for the tools used by the benchmark:

| Tool | Environment variable | Required | Description |
|------|----------------------|----------|-------------|
| **serper-search** | `SERPER_API_KEY` | Yes | API key for [SerpAPI/Google Serper](https://serper.dev/) web search. |
| **jina-scrape-llm-summary** | `JINA_API_KEY` | Yes | API key for [Jina Reader](https://jina.ai/reader/) (URL scraping). |
| **jina-scrape-llm-summary** | `SUMMARY_LLM_BASE_URL` | Yes | Base URL of the LLM used for page summarization (see below). |
| **jina-scrape-llm-summary** | `SUMMARY_LLM_MODEL_NAME` | Yes | Model name for summarization (e.g. `gpt-4o-mini`, `gemini-2.0-flash`). |
| **jina-scrape-llm-summary** | `SUMMARY_LLM_API_KEY` | Yes* | API key for the summary LLM. *Not needed for Vertex AI (uses `gcloud auth`). |
| **python-code-sandbox** | `SANDBOX_ADDRESS` | No (default: `localhost`) | Host where the sandbox HTTP server runs. |
| **python-code-sandbox** | `SANDBOX_HOST_PORT` | No (default: `18080`) | Port of the sandbox HTTP server. |

**Summary LLM (jina-scrape-llm-summary):** We support **OpenRouter** (set base URL to OpenRouter endpoint and use `SUMMARY_LLM_API_KEY`), **Google Vertex AI** (use a Vertex-style base URL and ensure `gcloud auth application-default login`; no `SUMMARY_LLM_API_KEY` needed), and **Google official API** (use `https://generativelanguage.googleapis.com/...` and `x-goog-api-key` via `SUMMARY_LLM_API_KEY`).

For **python-code-sandbox** (e.g. for the HLE dataset), you also need to run the sandbox server in Docker. See [docs/python-sandbox-setup.md](../../../../docs/python-sandbox-setup.md) for building the image and starting the container.

---

## Running the Benchmark

From the **repository root**:

```bash
python3 tests/benchmark/deep_research/test_benchmark_deepresearch.py \
  mcpuniverse/benchmark/configs/deepresearch/configs/browsecomp/agent_wide_research_bc_gpt5.yaml
```

Use any YAML under `mcpuniverse/benchmark/configs/deepresearch/configs/<dataset>/` for that dataset and model (e.g. `agent_wide_research_bc_gemini3pro.yaml`, `agent_wide_research_gaia_claude45sonnet.yaml`).

---

## Model Configuration

To use a different model, edit the **LLM** section in the chosen agent YAML (or use the corresponding pre-built config).

**Gemini 3 Pro:**

```yaml
kind: llm
spec:
  name: llm-1
  type: gemini
  config:
    model_name: gemini-3-pro-preview
```

**Claude 4.5 Sonnet:**

```yaml
kind: llm
spec:
  name: llm-1
  type: claude_wr
  config:
    model_name: claude-sonnet-4-5
    timeout: 300
```

---

## Tool Calling & Scheduler

Agent configs use `scheduler_mode` to control **parallel tool calling** per iteration.

### Example agent config

```yaml
kind: agent
spec:
  name: function-call-agent
  type: function_call_wide_research
  config:
    llm: llm-1
    instruction: ...
    max_iterations: 100
    summarize_tool_response: false
    system_prompt: mcpuniverse/agent/configs/function_call_prompt_scheduler.j2
    scheduler_mode:
      100: 3
```

- **`scheduler_mode: 100: 3`** — **3 parallel tool calls** per step for the first 100 iterations (fixed parallel setting used in the paper).
- **No `scheduler_mode`** — single tool call per iteration (baseline).

### Scheduler variants (paper settings)

| Mode        | Description | Config |
|------------|-------------|--------|
| **Constant 1 tools**  | 3 tool calls per step for all 100 iterations | Remove `scheduler_mode` in the config |
| **Constant 3 tools**  | 3 tool calls per step for all 100 iterations | `scheduler_mode: 100: 3` (as above) |
| **Descending** | 3 → 2 → 1 tool calls over time | See below |
| **Ascending**  | 1 → 2 → 3 tool calls over time | See below |
| **Automatic**  | LLM chooses 1–4 tool calls per step | See below |

**Descending** (3 in first 25 iters, 2 in 26–50, 1 in 51–100):

```yaml
scheduler_mode:
  25: 3
  50: 2
  100: 1
```

**Ascending** (1 in first 25, 2 in 26–50, 3 in 51–100):

```yaml
scheduler_mode:
  25: 1
  50: 2
  100: 3
```

**Automatic** (LLM decides how many calls, 1–4 per step):

```yaml
scheduler_mode:
  dynamic: "At next step, if you need to make function calls, you MUST make at least 1 but not more than 4 function calls in a single response to gather information extensively. You should decide the best number of function calls for the next step by yourself based on the information you have gathered so far."
```

---

## File layout

```
deepresearch/
├── README.md
├── prepare_deep_research_data.py
├── data_utils.py
└── configs/
    ├── browsecomp/   # BrowseComp agent configs
    ├── gaia/         # GAIA agent configs
    └── hle/          # HLE agent configs
```

---

## Citation

If you use our work, please cite:

```bibtex
@misc{lin2026wdscalingparalleltoolcalling,
      title={W&D:Scaling Parallel Tool Calling for Efficient Deep Research Agents}, 
      author={Xiaoqiang Lin and Jun Hao Liew and Silvio Savarese and Junnan Li},
      year={2026},
      eprint={2602.07359},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2602.07359}, 
}
```
