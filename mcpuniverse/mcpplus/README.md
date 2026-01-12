# MCP+ (MCP Plus)

**MCP client context management via agentic post-processing of MCP server responses**

MCP+ prevents your MCP client's context window from being diluted or corrupted with irrelevant information by intelligently extracting only what your agent needs from verbose tool outputs.

## The Problem

When MCP tools return large outputs (API responses, web scrapes, database results, file contents), agents face two challenges:

1. **Context dilution** - Irrelevant tokens consume precious context window space
2. **Context corruption** - Noise in the output can mislead the agent's reasoning

## The Solution

MCP+ intercepts tool calls and post-processes outputs using dual extraction:

- **Direct extraction** and **code generation** in a single LLM call

It uses LLM reasoning to understand what information is relevant to the agent's stated goal and extracts/transforms accordingly.

## Quick Start

```bash
pip install mcpuniverse
export OPENAI_API_KEY=sk-...
mcp-build-plus --mcp-config ~/.cursor/mcp.json
# Restart your MCP client → use finance-plus instead of finance
```

## CLI Options

```bash
mcp-build-plus --mcp-config ~/.cursor/mcp.json [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--mcp-config` | Path to your mcp.json config file | Required |
| `--servers` | Specific server names to wrap (space-separated) | All servers |
| `--llm-model` | LLM model for post-processing | `gpt-4.1` |
| `--llm-api-key-env` | Environment variable name for API key | `OPENAI_API_KEY` |
| `--token-threshold` | Min tokens to trigger post-processing | `500` |
| `--output` | Path to write updated config | Overwrite input |
| `--dry-run` | Preview changes without writing | - |
| `-y, --yes` | Skip confirmation prompt | - |

**Examples:**
```bash
# Wrap specific servers with custom threshold
mcp-build-plus --mcp-config ~/.cursor/mcp.json --servers finance weather --token-threshold 500

# Preview changes without applying
mcp-build-plus --mcp-config ~/.cursor/mcp.json --dry-run
```

## How It Works

1. Agent calls tool with `expected_info` parameter describing what it needs
2. MCP+ forwards the call to the upstream server
3. If output exceeds token threshold, post-processor analyzes it
4. LLM returns both direct extraction and code (dual extraction)
5. Validated, relevant output returned to agent

## Per-Server Configuration

Each `-plus` server has a config file in `~/.mcpplus/configs/proxy_<server>.json`:

| Option | Description | Default |
|--------|-------------|---------|
| `token_threshold` | Min tokens to trigger post-processing | 500 |
| `max_iterations` | Dual retries before giving up | 3 |
| `enable_reflection` | Validate output quality via LLM | false |
| `execution_timeout` | Timeout in seconds for LLM call and code execution | 500 |
| `max_tool_output_chars` | Max chars passed to the post-processor (null = no truncation) | null |

Note: `post_processor_type` is deprecated and ignored. MCP+ always uses the dual post-processor.

## Documentation

See [docs/mcp-plus.md](../../docs/mcp-plus.md) for full documentation.

## Future Optimizations

- Tighten `execution_timeout` or `max_iterations` for lower latency
- Keep `enable_reflection: false` to avoid extra LLM calls

## Next steps

- Support other LLM vendors for MCP+ agent besides OpenAI
- Test with remote MCP servers
