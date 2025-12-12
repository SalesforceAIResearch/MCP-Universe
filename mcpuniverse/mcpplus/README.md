# MCP+ (MCP Plus)

**MCP client context management via agentic post-processing of MCP server responses**

MCP+ prevents your MCP client's context window from being diluted or corrupted with irrelevant information by intelligently extracting only what your agent needs from verbose tool outputs.

## The Problem

When MCP tools return large outputs (API responses, web scrapes, database results, file contents), agents face two challenges:

1. **Context dilution** - Irrelevant tokens consume precious context window space
2. **Context corruption** - Noise in the output can mislead the agent's reasoning

## The Solution

MCP+ intercepts tool calls and post-processes outputs using:

- **Direct extraction** - For simple, visible data that can be extracted immediately
- **Code generation** - For complex transformations requiring parsing, filtering, or restructuring

MCP+ uses LLM reasoning to understand what information is relevant to the agent's stated goal and extracts/transforms accordingly.

## Quick Start

```bash
pip install mcpuniverse
export OPENAI_API_KEY=sk-...
mcp-build-plus --mcp-config ~/.cursor/mcp.json
# Restart your MCP client → use finance-plus instead of finance
```

## How It Works

1. Agent calls tool with `expected_info` parameter describing what it needs
2. MCP+ forwards the call to the upstream server
3. If output exceeds token threshold, post-processor analyzes it
4. LLM decides: direct extraction or code generation
5. Validated, relevant output returned to agent

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `token_threshold` | Min tokens to trigger post-processing | 400 |
| `max_iterations` | ReAct iterations for code refinement | 3 |
| `enable_reflection` | Validate output quality via LLM | true |
| `post_processor_type` | `"extract"` (intelligent) or `"react"` (code-only) | `"extract"` |

## Documentation

See [docs/mcp-plus.md](../../docs/mcp-plus.md) for full documentation.

## Future Optimizations

- Remove synthetic UX delays for lower latency
- Skip validation step (`enable_reflection: false`) for faster processing

## Next steps

- Support other LLM vendors for MCP+ agent besides OpenAI
- Test with remote MCP servers
