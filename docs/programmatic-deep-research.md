# Programmatic deep research

The `research-primitives` MCP server lets a model write a Python program that
composes web searches, page reads, and summaries in one tool call. Only printed
findings return to the model. It works with the existing `function_call` agent
and any of its tool-capable model adapters.

## Setup

Use Python 3.10 or newer on Linux or macOS, and follow the repository's normal
installation instructions (`pip install -e .`). This runtime uses POSIX file
locks and child processes. Run the example from the repository root.

Set these variables in your environment or the repository's `.env`:

```dotenv
OPENAI_API_KEY=your-main-model-key
SERPER_API_KEY=your-search-key
JINA_API_KEY=your-reader-key
JINA_BASE_URL=https://r.jina.ai
SUMMARY_LLM_BASE_URL=https://api.openai.com/v1/chat/completions
SUMMARY_LLM_MODEL_NAME=gpt-4.1-mini
SUMMARY_LLM_API_KEY=your-summary-key
```

`SUMMARY_LLM_BASE_URL` is the complete request endpoint. The main model uses
the existing adapter's settings; for a compatible endpoint, set
`OPENAI_BASE_URL` and edit `model_name` in the example YAML. Other MCP-Universe
model adapters can be selected in that YAML. Search, reading, and summarization
make paid external requests when configured with paid services.

```bash
python -m mcpuniverse.benchmark.deep_research \
  --config examples/deep_research/benchmark.yaml \
  --output results/deep-research
```

The output contains `traces.log`, `results.json`, and per-task evaluator results
under `tasks/`. Add `--resume` to reuse completed task results with the same
configuration and task contents. The example has no evaluators and demonstrates
research execution only; it does not report an accuracy score. For evaluation,
provide your own task JSON files and their standard MCP-Universe evaluators,
then list them in the benchmark YAML. Dataset access and judge credentials are
configured separately according to the benchmark you use.

## Program contract

`run_research_program(code, timeout=240)` exposes:

| Coroutine | Result |
| --- | --- |
| `search(q, num=10, gl="us", hl="en", location=None, tbs=None)` | Search results with title, link, and snippet |
| `scrape(url, max_chars=409600)` | Page text from Jina Reader |
| `llm_summary(content, question, max_tokens=4096)` | Extracted or summarized information |

`json`, `asyncio`, and restricted Python builtins are predefined. Imports are
disabled by default. Top-level `await` is supported:

```python
groups = await asyncio.gather(search("Nobel Physics 2024"), search("Nobel Physics 2024 contributions"))
urls = list(dict.fromkeys(hit["link"] for group in groups for hit in group))[:3]
pages = await asyncio.gather(*[scrape(url, max_chars=12000) for url in urls])
sources = "\n\n".join(f"[{url}]\n{page}" for url, page in zip(urls, pages))
print(await llm_summary(sources, "Who won and why? Cite the source URLs."))
```

The response is `{"success": bool, "error": str, "stdout": str}`. Returned
stdout is capped at 16,000 characters. Search/read failures produce diagnostic
results rather than fabricated content. The inherited research filtering skips
Hugging Face dataset/Space URLs; it does not filter answer content.

Every program executes in a fresh subprocess. A parent wall-clock limit also
terminates programs that never yield. `RP_RUNNER_WORKERS` controls concurrent
children (default 32), and `RP_SUBPROCESS_OVERHEAD_S` provides startup slack
(default 30 seconds). Default program timeouts are clamped to 240 seconds;
if you raise `RP_MAX_PROGRAM_TIMEOUT`, also raise your MCP client's timeout.
Serper admission is limited across processes on the same host. This is an
AST-restricted runtime, not an operating-system security sandbox: run it under
an appropriately isolated account/container and do not expose it as a public
arbitrary-code execution service.

## Standalone server and checks

```bash
python -m mcpuniverse.mcp.servers.research_primitives
python -m mcpuniverse.mcp.servers.research_primitives --transport sse --port 8000
python -m pytest tests/mcp/servers/test_research_primitives_scrape.py \
  tests/mcp/servers/test_research_primitives_runtime.py \
  tests/benchmark/test_deep_research_cli.py
```

The tests use local processes and mocked providers; they require no API keys.
