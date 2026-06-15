# PRD: LangChain + Pydantic AI Migration

> Design doc: [`docs/design/langchain-pydantic-ai-migration.md`](docs/design/langchain-pydantic-ai-migration.md)

## Problem Statement

MCP-Universe maintains a custom agent and LLM framework (BaseLLM, BaseAgent, hand-rolled ReAct and function-call loops, YAML-driven WorkflowBuilder, ComponentABCMeta registry). While functional and benchmark-proven, this stack is difficult for new contributors to learn because patterns are project-specific rather than aligned with widely adopted open-source ecosystems.

The framework also faces growing context-window pressure from verbose MCP tool outputs. Multiple overlapping mitigation mechanisms exist today (MCP+, summarize_tool_response, in-process SafeCodeExecutor, python-code-sandbox Docker MCP), and there is no unified strategy for newer approaches like CodeMode / programmatic tool calling (PTC).

The team needs a maintainable path to adopt **Pydantic AI** and **LangChain Deep Agents** for agent runtime, sandbox execution, and context reduction — while supporting OpenAI, OpenRouter, and local LLMs (vllm_local / sglang_local) — without breaking existing benchmarks, YAML configs, or trace/report outputs.

## Solution

Adopt an **adapter-first migration**: Pydantic AI becomes the primary agent runtime; LangChain Deep Agents owns sandbox environment creation and CodeMode/PTC; the existing MCPClient layer, BenchmarkRunner, evaluators, env_pool, and tracing remain the source of truth with thin adapters on top.

WorkflowBuilder transparently routes legacy YAML `type:` aliases to new implementations so benchmark configs require no edits. A unified context layer chains CodeMode (when supported) with MCP+ fallback for large tool outputs.

Deliverable for the analysis task: **design document + POC** proving one benchmark domain runs end-to-end on the new stack.

## User Stories

1. As a **framework maintainer**, I want agents implemented on Pydantic AI, so that new contributors can use familiar OSS patterns instead of learning custom BaseAgent loops.

2. As a **framework maintainer**, I want a single LLM provider factory with a `provider` discriminator (openai, openrouter, vllm_local, sglang_local), so that adding or switching providers does not require duplicate agent code.

3. As a **benchmark operator**, I want existing YAML benchmark configs to work unchanged, so that CI and Azure benchmark scripts do not break mid-migration.

4. As a **benchmark operator**, I want BenchmarkRunner, Task evaluators, and BenchmarkReport to work without modification, so that evaluation infrastructure investment is preserved.

5. As a **benchmark operator**, I want trace files and report output to remain compatible with current tooling, so that historical comparison and MCP+ tracer analysis still work.

6. As a **research engineer**, I want function_call agents migrated to Pydantic AI first, so that the most YAML-common agent type proves the adapter pattern quickly.

7. As a **research engineer**, I want react agents migrated for models without reliable native tool calling, so that vllm_local and sglang_local benchmarks remain viable.

8. As a **research engineer**, I want wide research agents migrated, so that the flagship parallel tool-calling feature stays on the maintained stack.

9. As a **research engineer**, I want MCP tools exposed to Pydantic AI agents via adapters over the existing MCPClient, so that permissions, gateway routing, and env_pool integration are not reimplemented.

10. As a **research engineer**, I want tool names to remain in the `server__tool` convention, so that existing evaluators and task definitions stay valid.

11. As a **context-cost owner**, I want a unified context reduction layer, so that CodeMode and MCP+ are composed deliberately instead of competing ad hoc mechanisms.

12. As a **context-cost owner**, I want CodeMode / PTC via LangChain Deep Agents for supported models, so that agents can call tools programmatically and only return final results to chat history.

13. As a **context-cost owner**, I want MCP+ as fallback when CodeMode is unavailable, so that large one-shot tool payloads are still compressed at the MCP transport layer.

14. As a **context-cost owner**, I want MCP+ internals refactored onto Pydantic AI, so that the extension is maintainable alongside the new agent stack.

15. As a **security-conscious operator**, I want env_pool to continue provisioning isolated Docker MCP Gateway environments for benchmarks, so that Playwright, Postgres, and Blender tasks remain properly isolated.

16. As a **security-conscious operator**, I want LangChain Sandboxes for CodeMode and general code execution, so that interpreter code runs in an isolated environment rather than in-process.

17. As a **security-conscious operator**, I want a hybrid sandbox strategy, so that MCP-heavy benchmarks use env_pool while CodeMode uses LangChain sandbox APIs.

18. As a **local LLM user**, I want vllm_local and sglang_local supported via OpenAI-compatible Pydantic AI providers, so that local inference does not require separate agent implementations.

19. As a **OpenRouter user**, I want openrouter supported via the same provider factory, so that model routing stays configuration-driven.

20. As a **OpenAI / Azure user**, I want openai and azure providers in the factory, so that cloud benchmark scripts (e.g. Azure benchmarks) continue to work.

21. As a **RL engineer**, I want RL, TITO, and VERL integration to remain on the legacy stack during phase 1, so that the OSS migration does not block training workflows.

22. As a **workflow author**, I want custom orchestration workflows (chain, router, orchestrator) to remain on the legacy stack initially, so that migration scope stays bounded.

23. As a **contributor writing tests**, I want POC validated by an existing benchmark integration test passing, so that viability is proven by external behavior not unit mocks.

24. As a **contributor writing tests**, I want provider factory tests following existing LLM test patterns, so that test style stays consistent.

25. As a **contributor writing tests**, I want WorkflowBuilder routing tested so legacy type aliases resolve to Pydantic AI implementations, so that YAML compat is regression-protected.

26. As a **project lead**, I want a phased roadmap (POC → benchmark agents → context layer → sandboxes → cleanup), so that work can be split into independently reviewable PRs.

27. As a **project lead**, I want an analysis deliverable (design doc + working POC), so that stakeholders can sign off before full implementation.

28. As a **downstream integrator**, I want the Executor contract (`execute` → AgentResponse) preserved, so that FastAPI app and pipeline launcher integrations do not break.

29. As a **MCP+ user**, I want mcp-build-plus CLI and wrapper configs to keep working, so that Cursor/Claude Code integrations are not disrupted during MCP+ refactor.

30. As a **future maintainer**, I want legacy BaseLLM types deprecated with aliases rather than deleted immediately, so that rollback and gradual migration are possible.

## Implementation Decisions

### Strategy

- **Adapter-first, not rewrite.** Approximately 70% of the codebase (MCP layer, benchmarks, evaluators, env_pool, tracing) stays; agent loops, LLM factory, and context middleware are the rewrite surface.
- **Do not adopt LangChain and Pydantic AI as dual full agent frameworks.** Pydantic AI owns agent runtime; LangChain owns sandboxes and CodeMode only.

### WorkflowBuilder and YAML compatibility

- WorkflowBuilder gains transparent routing: legacy `kind: llm` types (`openai`, `openrouter`, `vllm_local`, `sglang_local`, `azure`) map internally to `pydantic_ai` + `provider` field.
- Legacy `kind: agent` types (`function_call`, `react`, wide research) instantiate Pydantic AI-backed agents implementing the existing Executor interface.
- No external YAML changes required for POC or phase 1.

### LLM provider factory

- New unified component: `type: pydantic_ai` with `provider: openai | openrouter | vllm_local | sglang_local | azure`.
- vllm_local and sglang_local share the same OpenAI-compatible provider implementation; differ only in environment variable defaults.
- Legacy BaseLLM classes remain as aliases during transition.

### Agent migration (phase 1)

- **POC:** function_call only.
- **Phase 1:** function_call, react, wide research.
- Agents implement existing Executor contract; internally delegate to Pydantic AI Agent with MCP toolsets.

### MCP integration

- MCPClient and MCPManager remain source of truth.
- New adapter layer converts MCPClient tools to Pydantic AI-compatible tool definitions without replacing transport, permissions, gateway, or env_pool logic.

### Context layer

- New unified middleware module composes:
  1. LangChain CodeMode / PTC when model and agent support it.
  2. MCP+ wrapper fallback for large tool outputs otherwise.
- MCP+ PostProcessAgent refactored to use Pydantic AI instead of custom BaseAgent for post-processing LLM calls.
- `summarize_tool_response` on legacy agents deprecated over time in favor of unified layer.

### Sandboxes (hybrid)

- **env_pool:** unchanged for benchmark and RL MCP Gateway isolation; future optional wrap as LangChain BaseSandbox backend.
- **LangChain Sandboxes:** used for CodeMode execution and general code tasks; setup scripts for dependency install.
- **python_code_sandbox MCP:** remains during transition; may be superseded by LangChain sandbox execute over time.

### Tracing and callbacks

- Existing Tracer, FileCollector, MemoryCollector, and callback event bus preserved.
- Pydantic AI agents emit trace events via adapters at `execute()` boundaries.
- No trace format changes in phase 0–1.

### Dependencies

- Add `pydantic-ai` (or `pydantic-ai-slim` + extras as appropriate).
- Add `deepagents` / LangChain Deep Agents for sandbox and CodeMode phases.
- Do not remove existing OpenAI SDK usage until legacy BaseLLM aliases are deprecated.

### Registration

- New agents and LLM factory register with existing ComponentABCMeta / AgentManager / ModelManager patterns so YAML `type:` resolution continues to work.

## Testing Decisions

### Principles

- Test **external behavior** at the highest seam possible, not internal Pydantic AI or LangChain call structure.
- Prefer integration tests over mocking LLM responses when proving migration viability.
- Existing skipped benchmark tests are the template for POC validation (un-skip or add parallel test only when API keys available).

### Modules / seams to test

| Seam | Behavior under test | Prior art |
|------|---------------------|-----------|
| BenchmarkRunner + unchanged YAML | Full benchmark run produces evaluation results | benchmark integration tests in tests/benchmark/mcpuniverse/ |
| WorkflowBuilder | Legacy type aliases resolve to new implementations | workflow builder tests |
| Provider factory | Each provider produces valid generation | LLM provider unit tests |
| Executor.execute | Agent returns AgentResponse; invokes MCP tools | function_call agent tests |
| Tracing | Trace collector receives records; BenchmarkReport dumps | tracer and report tests |
| MCP+ context layer | Large outputs compressed when threshold exceeded | MCP+ integration tests |

### POC test gate

- `financial_analysis` benchmark (or agreed alternate) passes end-to-end with Pydantic AI function_call agent and `provider: openai`.
- YAML config file unchanged from current version.
- BenchmarkReport generates without trace shape errors.

### Out of scope for POC tests

- react and wide research (phase 1).
- CodeMode / LangChain sandbox (phase 2–3).
- RL rollouts and env_pool docker_pool mode.
- Local LLM providers (phase 1 after openai POC).

## Out of Scope

- Full migration of all agent types in one effort.
- Replacing MCPClient with Pydantic AI or LangChain MCP clients.
- Retiring env_pool in favor of cloud-only LangChain sandbox providers.
- Replacing MCP+ entirely with CodeMode.
- RL / TITO / VERL / react_train_agent migration.
- Custom workflow orchestration migration to LangGraph.
- Benchmark score parity guarantees with legacy agents.
- Removing legacy BaseLLM and BaseAgent in phase 0–1.
- OpenTelemetry migration (optional future phase).
- Committing secrets or API keys in tests or configs.

## Further Notes

- **MCP+ vs CE:** "CE" in the original task refers to code execution / CodeMode (programmatic tool calling), not a named component in this repo. MCP+ and CodeMode are complementary, not competing replacements.
- **No existing LangChain or Pydantic AI footprint** in the codebase today; migration introduces new dependencies alongside existing OpenAI SDK, Anthropic, and openai-agents usage.
- **Design doc** with architecture diagram, phased roadmap, and decision log: `docs/design/langchain-pydantic-ai-migration.md`.
- **Open questions** for follow-up: auto-select react for local LLMs without tool calling; cloud sandbox provider availability; azure as explicit factory provider.
