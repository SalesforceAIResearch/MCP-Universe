## Problem Statement

MCP-Universe now supports an explicit Azure OpenAI LLM provider (`type: azure`) for benchmark agents, but the migration is incomplete. Operators who configure only Azure credentials (`AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`) expect to run benchmarks end-to-end without also maintaining direct OpenAI API access.

In practice, several suites still depend on OpenAI outside the agent loop: task evaluators instantiate the OpenAI client directly and hardcode OpenAI model IDs for LLM-as-judge scoring. Benchmark YAMLs for most domains still declare `type: openai`. Some agent types (for example Harmony ReAct) assume provider-specific config fields that Azure does not expose. Documentation and run scripts do not clearly distinguish **agent LLM** (Azure-capable) from **grading LLM** (still OpenAI-only) or from **non-LLM service keys** (Maps, GitHub, SerpAPI, etc.).

This produces confusing failures: agents run successfully on Azure while reports show evaluation failures; or runtime errors such as missing `reasoning` on Azure config when incompatible agent types are used.

## Solution

Finish a **clean, explicit Azure migration** across the benchmark surface area so that:

1. **Agents and evaluators** can both route through a unified LLM abstraction (ModelManager) with explicit provider selection, defaulting to Azure when configured.
2. **All benchmark YAMLs** intended for Azure runs use `type: azure` with deployment names (not OpenAI model IDs).
3. **Incompatible agent/provider pairings** are prevented or documented (Harmony ReAct requires OpenRouter-style `reasoning`; stock web search should use ReAct + Azure).
4. **Operators** can run an overnight batch with a single LLM credential story (Azure-only) for all suites that do not inherently require other APIs — and clear documentation for suites that still need Maps, GitHub, SerpAPI, etc.
5. **Reports** reflect true pass/fail under Azure grading, not agent success with silent judge failure.

## User Stories

1. As a benchmark operator with only Azure OpenAI credentials, I want every benchmark agent to run using `type: azure`, so that I do not need a separate OpenAI API key for inference.
2. As a benchmark operator, I want task evaluators that use LLM-as-judge to grade responses via Azure when Azure is my configured provider, so that pass/fail in reports matches what I actually run.
3. As a benchmark operator running web search, I want the google-search LLM judge to use my Azure deployment instead of a hardcoded `gpt-4.1` OpenAI model, so that web search scores are meaningful under Azure-only setup.
4. As a benchmark operator running deep research, I want the HLE-style LLM judge to use a configurable provider and deployment instead of hardcoded `o3-mini`, so that deep research can be evaluated on Azure when a suitable reasoning deployment exists.
5. As a benchmark operator, I want environment variables that clearly separate agent LLM config from judge LLM config (with sensible defaults to the same Azure deployment), so that I can override the judge only when needed.
6. As a benchmark operator, I want all MCP-Universe domain benchmark YAMLs migrated to Azure, so that I can batch-run financial analysis, web search, location navigation, repository management, browser automation, 3D design, and multi-server without manual per-file edits.
7. As a benchmark operator, I want all MCPMark benchmark YAMLs migrated to Azure with valid deployment names, so that MCPMark suites do not reference OpenRouter model IDs while declaring `type: openai`.
8. As a benchmark operator, I want web search to use the ReAct agent with Azure (not Harmony ReAct), so that I avoid provider-specific `reasoning` config errors at runtime.
9. As a benchmark operator, I want Harmony ReAct benchmarks to either require OpenRouter explicitly or fail fast with a clear error when paired with Azure, so that misconfiguration is obvious immediately.
10. As a benchmark operator, I want financial analysis to remain fully Azure-compatible (agent + deterministic yfinance evaluators), so that my proven working suite stays regression-free.
11. As a benchmark operator, I want location navigation, repository management, browser automation, 3D design, and multi-server benchmarks to work with Azure agents once their non-LLM keys are set, so that LLM migration is not blocked by unrelated services.
12. As a benchmark operator, I want documentation that lists which benchmarks require which non-Azure API keys (Google Maps, GitHub PAT, SerpAPI, Blender, Postgres, Notion, WebArena Docker), so that I know what Azure cannot replace.
13. As a benchmark operator, I want an overnight batch script that runs only Azure-ready suites in sequence with logs and markdown reports, so that I can start a long run without babysitting individual test files.
14. As a benchmark operator, I want the README Azure section to document the two LLM call paths (agent vs evaluator), so that I understand why web search still failed grading before evaluator migration.
15. As a contributor, I want a shared judge helper used by google-search and deep-research evaluators, so that provider logic is not duplicated and future providers are easier to add.
16. As a contributor, I want evaluator LLM calls to go through ModelManager with provider alias `azure` or `openai`, so that the Azure adapter investment applies consistently across the codebase.
17. As a contributor, I want judge model selection to use deployment names on Azure and model names on OpenAI, so that configuration matches each provider's semantics.
18. As a benchmark operator, I want `.env.example` to document optional judge overrides (`EVAL_LLM_PROVIDER`, `EVAL_LLM_DEPLOYMENT` or equivalent), so that hybrid Azure-agent + OpenAI-judge setups are possible during transition.
19. As a benchmark operator, I want Azure GPT-5-class deployments to optionally receive `reasoning_effort` parity with the stock OpenAI provider, so that reasoning-heavy agents behave similarly across providers.
20. As a benchmark operator running web search, I want SerpAPI quota implications documented, so that I do not exhaust search credits mid-run expecting Azure alone to suffice.
21. As a benchmark operator, I want deep research benchmarks explicitly marked out of scope for Azure-only until data prep and judge migration are done, so that I do not attempt multi-thousand-task runs with broken grading.
22. As a contributor, I want unit tests that prove an evaluator judge call uses ModelManager when `EVAL_LLM_PROVIDER=azure`, so that regressions back to hardcoded OpenAI are caught.
23. As a contributor, I want integration tests that run a minimal web-search task end-to-end with Azure agent + Azure judge (mocked HTTP), so that the full loop is verified at the benchmark seam.
24. As a benchmark operator, I want MCPMark Notion and Postgres YAMLs to stop declaring invalid OpenAI model names copied from OpenRouter, so that Azure migration does not inherit bogus model IDs.
25. As a maintainer, I want a compatibility matrix in docs (benchmark × agent provider × evaluator LLM × external keys), so that support questions have a single reference.
26. As a benchmark operator, I want the missing `mcpuniverse/notion.yaml` test reference fixed or removed, so that the test inventory matches runnable configs.
27. As a contributor, I want changes scoped so MCP+ gateway Azure helpers remain consistent with evaluator provider routing, so that remote MCP paths do not assume `OPENAI_API_KEY` only.
28. As a benchmark operator, I want benchmark reports to record which LLM provider graded each task, so that I can audit hybrid runs.
29. As a security-conscious operator, I want judge and agent to read credentials from environment only (never committed), so that Azure and OpenAI keys stay out of YAML.
30. As a benchmark operator, I want a reduced quick web search config (fewer tasks, lower max iterations) documented for smoke runs, so that I can validate Azure migration without multi-hour full suites.

## Implementation Decisions

### Architectural model: two LLM consumption paths

Benchmarks today consume LLMs in two separate ways:

- **Agent path**: Benchmark YAML → agent (ReAct, FunctionCall, etc.) → ModelManager → provider (`azure`, `openai`, …). This is what the Azure adapter already implements.
- **Evaluator path**: Task JSON evaluators → compare functions that may call `OpenAI()` directly with `OPENAI_API_KEY` and hardcoded model IDs. This path bypasses ModelManager entirely.

**Decision**: Treat evaluator LLM usage as in-scope for complete Azure migration. Introduce a small shared **evaluator LLM helper** in the evaluator layer that builds a model via ModelManager from environment-driven provider config, mirroring agent explicit opt-in (`azure` vs `openai`).

### Evaluator judge configuration

**Decision**: Add environment-driven judge settings with defaults:

- Default judge provider follows agent provider when only Azure is configured (Azure-only happy path).
- Allow explicit override for hybrid transition (Azure agent, OpenAI judge) via documented env vars.
- Judge deployment/model name must respect Azure semantics (deployment name) vs OpenAI semantics (model ID).

Apply to:

- Google search `llm_as_a_judge` (all web search tasks).
- Deep research `hle_llm_as_a_judge` (all generated deep research tasks).

### Benchmark YAML migration

**Decision**: Batch-update benchmark YAML LLM specs to `type: azure` with deployment name placeholder pattern consistent with financial analysis (operator sets deployment in YAML or via documented convention).

Domains in scope for YAML migration:

- MCP-Universe: location navigation, repository management, browser automation, 3D design, multi-server (web search and financial analysis already done).
- MCPMark: filesystem, github, notion, playwright, playwright webarena, postgres.
- Dummy smoke benchmark.
- Deep research configs deferred until judge + tooling story is settled.

**Decision**: Web search agent remains ReAct + Azure; do not use Harmony ReAct with Azure.

**Decision**: Fix MCPMark Notion/Postgres YAML invalid model identifiers when migrating to Azure.

### Azure provider parity (agent path)

**Decision**: Optionally align Azure OpenAI provider with stock OpenAI provider for `reasoning_effort` injection on supported deployments (gpt-5-class), without reintroducing deployment name rewriting bugs.

**Decision**: Do not add a `reasoning` field to Azure config for Harmony; Harmony stays OpenRouter-oriented unless separately redesigned.

### Operator tooling

**Decision**: Extend or replace the Azure batch run script to:

- Run suites grouped by readiness (Azure-only vs needs external keys).
- Emit logs and BenchmarkReport markdown per README patterns.
- Skip or gate suites missing required non-LLM credentials with clear messages.

### Documentation

**Decision**: Update README and `.env.example` with:

- Agent vs evaluator LLM paths.
- Compatibility matrix (benchmark / external keys / LLM judge yes-no).
- Azure-only vs hybrid credential layouts.

## Testing Decisions

**Principle**: Test external behavior at the highest existing seams; prefer extending patterns from the Azure LLM provider work (ModelManager build, workflow/benchmark integration) over testing private OpenAI client construction inside evaluators.

**Seams (highest first)**:

1. **Benchmark runner integration** — minimal single-task web search run with evaluator asserting pass when judge response is stubbed/mocked at the ModelManager boundary (proves agent + evaluator both route through configured provider).
2. **Evaluator compare functions** — unit tests for google-search and deep-research judges: when judge provider env is `azure`, ModelManager receives `azure` and no direct OpenAI client is required; when `openai`, existing behavior preserved.
3. **ModelManager / evaluator helper** — unit tests for env parsing (defaults, overrides, deployment name on Azure).
4. **YAML/config validation** (lightweight) — smoke test that all migrated benchmark YAMLs parse and resolve `type: azure` without missing fields for standard agent types.

**Prior art**:

- Existing Azure provider tests (ModelManager `build_model("azure")`, env validation, deployment name preservation).
- Workflow builder Azure integration tests.
- Benchmark test modules that use FileCollector, BenchmarkReport, and `get_vprint_callbacks` (financial analysis, web search patterns).

**Avoid**: Testing internal prompt strings or judge parsing regexes unless behavior regressions require it; focus on provider routing and end-to-end pass/fail under Azure judge config.

## Out of Scope

- Replacing non-LLM external services with Azure (Google Maps, SerpAPI/Serper, GitHub, Notion, Postgres, Blender, WebArena Docker, Jina, etc.) — these remain separate credentials regardless of LLM provider.
- Migrating MCP+ gateway default from `OPENAI_API_KEY` to Azure unless required for benchmark runs (may be follow-up).
- Full deep research overnight runs (GAIA/BrowseComp/HLE thousands of tasks) before data preparation and judge migration are complete.
- Harmony ReAct agent redesign for Azure-native harmony channel prompts.
- Upstreaming to SalesforceAIResearch/MCP-Universe (fork work unless explicitly requested).
- Auto-switching OpenAI to Azure silently without YAML `type: azure` opt-in (preserves existing explicit opt-in decision from the original Azure provider PRD).

## Further Notes

### Current state summary (from migration work)

| Area | Agent on Azure | Grading on Azure | Status |
|------|----------------|------------------|--------|
| Financial analysis | Yes | Yes (deterministic yfinance evaluators) | Working |
| Web search | Yes (ReAct) | No (OpenAI judge hardcoded) | Hybrid required today |
| Other MCP-Universe domains | After YAML flip | Yes (deterministic evaluators) | Needs YAML + external keys |
| MCPMark suites | After YAML flip | Yes (deterministic verifiers) | Needs YAML + service setup |
| Deep research | Not migrated | No (OpenAI o3-mini judge) | Out of scope for v1 |

### Known runtime pitfalls already encountered

- Harmony ReAct + Azure → `AzureOpenAIConfig` has no `reasoning` attribute.
- Web search stock YAML used OpenRouter + Harmony; fixed locally to ReAct + Azure for agent path only.
- SerpAPI quota is independent of Azure; full web search can exhaust Serp credits.
- `test_benchmark_notion.py` references a non-existent `mcpuniverse/notion.yaml`; use MCPMark Notion config instead.

### Suggested delivery slices (for implementation issues)

1. Evaluator judge helper + google-search judge on ModelManager/Azure.
2. Batch YAML migration + docs matrix + `.env.example` judge vars.
3. Deep research judge migration + GAIA smoke (optional follow-up).
4. Overnight batch script phases + quick web search profile.

### Related work

- Azure OpenAI LLM provider (agent path) — implemented on branch `feat/azure-openai-llm-provider` / PR #2 on fork.
- This PRD covers the **remaining gap**: evaluators, YAML coverage, operator clarity, and Azure-only reporting honesty.
