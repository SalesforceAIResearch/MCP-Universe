# Design: LangChain + Pydantic AI Migration

> Status: **Proposed** (grill session + PRD, June 2026)  
> Deliverable type: ADR + POC, then phased implementation

## Summary

Migrate MCP-Universe's agent and LLM layers onto mainstream open-source stacks (**Pydantic AI** for agent runtime, **LangChain Deep Agents** for sandboxes and CodeMode) while preserving the benchmark infrastructure, custom MCP client layer, tracing, and existing YAML configurations.

**Strategy: adapter-first, not rewrite.**

---

## Problem

MCP-Universe ships a custom agent framework (BaseLLM, BaseAgent, hand-rolled ReAct/function-call loops, ComponentABCMeta registry, YAML WorkflowBuilder). This works but:

- Onboarding cost is high — patterns are project-specific, not industry-standard.
- Context-window pressure from verbose MCP tool outputs requires bespoke solutions (MCP+, summarize_tool_response, in-process SafeCodeExecutor).
- Multiple parallel LLM integration paths already exist (OpenAI SDK, Anthropic, openai-agents, claude-code-sdk, TITO/vLLM direct).
- Adding LangChain + Pydantic AI as *additional* stacks without a plan increases surface area.

The assigned task is to **analyze and prove viability** of migrating to LangChain and Pydantic AI for OpenAI, OpenRouter, and local LLMs (vllm_local / sglang_local), including CodeMode and MCP+ vs code-execution (CE) tradeoffs.

---

## Goals

| Goal | Priority |
|------|----------|
| Maintainability via OSS agent frameworks | **Primary** |
| CodeMode + unified context reduction | **High** |
| Existing benchmark YAML unchanged | **High** |
| Benchmark trace/report format unchanged | **High** |
| Score parity with legacy agents | **Low** (not a gate) |

---

## Non-Goals (Phase 1)

- RL / TITO / VERL rollout engine migration
- Custom workflow orchestration (chain, router, orchestrator) → LangGraph
- Replacing MCPClient / MCPManager
- Replacing env_pool with cloud-only sandboxes
- Big-bang migration of all agent types

---

## Architecture

### Layer responsibilities

```
┌─────────────────────────────────────────────────────────────┐
│  YAML configs (unchanged externally)                      │
│  kind: llm (openai, openrouter, vllm_local, …)            │
│  kind: agent (function_call, react, …)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  WorkflowBuilder — transparent routing                      │
│  Legacy type aliases → Pydantic AI implementations            │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│ Pydantic AI   │  │ Unified       │  │ Tracing       │
│ agents        │  │ context layer │  │ (adapters)    │
│               │  │               │  │               │
│ function_call │  │ CodeMode/PTC  │  │ FileCollector │
│ react         │  │ (LangChain)   │  │ BenchmarkRpt  │
│ wide research │  │ MCP+ fallback │  │               │
└───────┬───────┘  └───────┬───────┘  └───────────────┘
        │                  │
┌───────▼──────────────────▼──────────────────────────────────┐
│  MCPClient / MCPManager (unchanged — source of truth)       │
│  Thin adapters expose MCP tools to Pydantic AI / LangChain  │
└───────┬────────────────────────────────────────────────────┘
        │
┌───────▼────────────────────────────────────────────────────┐
│  Execution environments (hybrid)                           │
│  • env_pool — Docker MCP Gateway stacks (benchmarks, RL)   │
│  • LangChain Sandboxes — CodeMode, general code execution  │
│  • python_code_sandbox MCP — legacy narrow Python exec     │
└────────────────────────────────────────────────────────────┘
```

### Framework split

| Concern | Owner | Rationale |
|---------|-------|-----------|
| Agent loop, tool calling, structured outputs | **Pydantic AI** | Native MCP client support; fits existing Pydantic v2 usage |
| LLM providers (OpenAI, OpenRouter, vLLM, SGLang) | **Pydantic AI** via provider factory | One `OpenAIProvider(base_url=…)` covers local + OpenRouter |
| Sandbox environment creation | **LangChain Deep Agents** | Setup scripts, `execute`, filesystem; provider ecosystem |
| CodeMode / PTC (context reduction) | **LangChain Deep Agents** interpreter | Agent writes code calling tools; only finals enter history |
| MCP tool transport, permissions, gateway | **Custom MCPClient** | Domain logic not in generic OSS clients |
| Benchmarks, evaluators, tasks | **Unchanged** | Only need `Executor.execute()` contract |

### env_pool vs LangChain Sandboxes

| | env_pool | LangChain Sandbox |
|---|----------|-------------------|
| **Isolates** | Full MCP stack (Gateway + servers) | Generic shell + filesystem |
| **Use for** | Playwright, Postgres, Blender benchmarks; RL docker_pool | CodeMode, ad-hoc code, setup scripts |
| **Integration** | Keep; optionally wrap as custom `BaseSandbox` backend | Use for non-MCP code execution paths |

### MCP+ vs CodeMode (CE)

| | MCP+ | CodeMode / PTC |
|---|------|----------------|
| **Layer** | MCP transport (wrapper on tool output) | Agent (interpreter middleware) |
| **Trigger** | Tool response exceeds token threshold | Model/agent supports programmatic tool calling |
| **Verdict** | **Keep** — refactor PostProcessAgent onto Pydantic AI | **Add** — not a replacement |

**Unified context layer (Decision D):** try CodeMode when supported; fall back to MCP+; deprecate duplicate `summarize_tool_response` paths over time.

### LLM provider factory (Decision D)

Single component kind with a `provider` discriminator:

| provider | Backend |
|----------|---------|
| `openai` | OpenAI API via Pydantic AI OpenAIChatModel |
| `openrouter` | OpenAI-compatible base URL |
| `vllm_local` | OpenAI-compatible local server |
| `sglang_local` | Same as vllm_local (alias, different env vars) |

WorkflowBuilder maps legacy `type: openai` → internal `pydantic_ai` + `provider: openai`.

---

## Phased delivery

### Phase 0 — POC (deliverable for analysis task)

- [ ] Provider factory: `pydantic_ai` + `provider: openai`
- [ ] Pydantic AI `function_call` agent behind legacy `type: function_call`
- [ ] MCPClient adapter as Pydantic AI toolset
- [ ] WorkflowBuilder transparent routing
- [ ] Tracing adapters at `execute()` boundary
- [ ] One benchmark domain end-to-end (financial_analysis recommended)
- [ ] MCP+ fallback only; CodeMode deferred

**POC pass:** existing pytest benchmark test passes; YAML unchanged; trace/report shape compatible.

### Phase 1 — Benchmark agents

- [ ] Migrate `react` agent (critical for local LLMs without reliable native tool calling)
- [ ] Migrate wide research agent
- [ ] All four LLM providers via factory
- [ ] Provider tests following existing LLM test patterns

### Phase 2 — Context layer

- [ ] Refactor MCP+ PostProcessAgent onto Pydantic AI
- [ ] LangChain CodeMode / PTC middleware for supported models
- [ ] Unified context middleware module (CodeMode → MCP+ fallback chain)
- [ ] Deprecation path for `summarize_tool_response`

### Phase 3 — Sandboxes

- [ ] Custom `BaseSandbox` backend wrapping env_pool
- [ ] LangChain sandbox integration for CodeMode execution
- [ ] Evaluate cloud providers (Modal, Daytona, Runloop) if needed

### Phase 4 — Cleanup

- [ ] Deprecate legacy BaseLLM internals (keep aliases)
- [ ] Optional: migrate tracing to Pydantic AI / Logfire
- [ ] Documentation update

---

## Key interfaces (stable contracts)

These seams must not break during migration:

1. **Executor** — `async execute(message) -> AgentResponse`
2. **BenchmarkRunner.run()** — accepts trace_collector, returns benchmark results
3. **WorkflowBuilder** — loads multi-doc YAML, resolves `kind: llm | agent | workflow`
4. **MCPClient.execute_tool()** — tool naming `server__tool`
5. **BenchmarkReport** — consumes trace collector output

---

## Testing strategy

Tests at the **highest seam possible** — external behavior, not implementation:

| Seam | What to assert | Prior art |
|------|----------------|-----------|
| BenchmarkRunner + YAML | Full run completes; evaluation results present | `tests/benchmark/mcpuniverse/test_benchmark_*.py` |
| WorkflowBuilder routing | Legacy `type:` instantiates Pydantic AI-backed agent | `tests/workflow/test_workflow_builder_azure.py` |
| Provider factory | Each provider generates valid responses | `tests/llm/test_openai.py`, `test_openrouter.py`, `test_local_llm.py` |
| Agent execute | Returns AgentResponse; calls tools via MCP | `tests/agent/test_function_call.py` |
| Tracing | FileCollector records trace IDs used by report | `tests/tracer/test_tracer.py` |
| MCP+ context layer | Large tool output compressed | `tests/extensions/mcpplus/integration/test_integration.py` |

POC minimum: one benchmark integration test green with `provider: openai`.

---

## Open questions

1. **Local LLM agent pairing** — auto-route `vllm_local`/`sglang_local` to `react` when native tool calling is unreliable?
2. **Cloud sandbox providers** — Modal/Daytona accounts available, or Docker-only?
3. **Azure provider** — include in factory as `provider: azure` alongside openai?

---

## Decision log (grill session)

| # | Decision |
|---|----------|
| 1 | Maintainability > benchmark parity |
| 2 | Pydantic AI primary; LangChain for sandboxes + CodeMode |
| 3 | Hybrid sandboxes: env_pool + LangChain |
| 4 | Unified context layer: CodeMode + MCP+ fallback |
| 5 | Keep MCPClient; adapters only |
| 6 | Phase 1 agents: function_call, react, wide research |
| 7 | LLM: pydantic_ai provider factory |
| 8 | YAML: WorkflowBuilder transparent routing |
| 9 | Tracing: adapters at execute() |
| 10 | Deliverable: ADR + POC |

---

## References

- [MCP-Universe system architecture](../system-architecture.md)
- [MCP+ README](../../mcpuniverse/extensions/mcpplus/README.md)
- [env_pool README](../../mcpuniverse/mcp/env_pool/README.md)
- [LangChain Deep Agents — Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)
- [Pydantic AI — MCP Client](https://ai.pydantic.dev/mcp/client/)
