# MCP+ (MCP Plus)

**MCP client context management via agentic post-processing of MCP server responses**

MCP+ wraps existing MCP servers with LLM-powered post-processing that automatically extracts and transforms long tool outputs to return only the information relevant to your query.

## Why MCP+?

When MCP tools return large outputs (API responses, web scrapes, file contents, etc.), agents face critical challenges:

- **Context dilution** - Irrelevant tokens consume precious context window space, reducing the agent's effective working memory
- **Context corruption** - Noise in verbose outputs can mislead the agent's reasoning and degrade response quality

MCP+ is a **context management solution** that prevents these issues by intelligently post-processing outputs before they enter the agent's context.

## How It Works

1. **Intercepting tool calls** - Adding an `expected_info` parameter to capture what the agent actually needs
2. **Intelligent post-processing** - Using LLM-generated code or direct extraction to process outputs (not simple truncation)
3. **Context preservation** - Only relevant, high-quality information enters the agent's context window

## Quick Start

### Installation

MCP+ is included with mcpuniverse:

```bash
pip install mcpuniverse
```

### Usage

1. **Set your OpenAI API key** (used for the post-processing LLM):
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

2. **Wrap your existing MCP servers**:
   ```bash
   mcp-build-plus --mcp-config ~/.cursor/mcp.json
   ```

3. **Review and confirm** the changes when prompted

4. **Restart your MCP client** (Cursor, Claude Desktop, etc.)

5. **Use the `-plus` servers** - e.g., `finance-plus` instead of `finance`

## How It Works

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│   MCP+ Proxy     │────▶│  Upstream MCP   │
│ (Cursor/Claude) │     │   Server         │     │    Server       │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Post-Processor  │
                        │  (LLM + Code)    │
                        └──────────────────┘
```

### Processing Flow

1. **Tool Call**: Agent calls a tool with `expected_info` describing what it needs
2. **Upstream Execution**: MCP+ forwards the call to the original server
3. **Threshold Check**: If output < 400 tokens, return as-is
4. **Post-Processing**:
   - LLM analyzes output and `expected_info`
   - Decides between direct extraction or code generation
   - Executes extraction code safely
   - Validates output quality via reflection
5. **Return**: Post-processed output returned to agent with processing summary

### Example

**Before (raw output)**: 15,000 chars of JSON from a finance API

**After (post-processed)**:
```
Stock: AAPL
Price: $178.52
Change: +2.3%

---
[MCP+ Post-Processing Summary]
Route: Code generation (new)
Iterations: 1/3
Reduction: 15,234 -> 48 chars (99%)
```

## Configuration

### CLI Options

```bash
mcp-build-plus --mcp-config ~/.cursor/mcp.json \
               --servers finance weather \        # Specific servers (default: all)
               --llm-model gpt-4.1 \              # LLM for post-processing (default: gpt-4.1)
               --dry-run                          # Preview without changes
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key for post-processing LLM | Required |
| `MCPPLUS_LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING) | WARNING |

### Proxy Config Options

Each `-plus` server has a config in `~/.mcpplus/configs/`:

```json
{
  "wrapper": {
    "enabled": true,
    "token_threshold": 400,
    "max_iterations": 3,
    "post_processor_type": "extract",
    "enable_reflection": true
  }
}
```

| Option | Description | Default |
|--------|-------------|---------|
| `token_threshold` | Min tokens to trigger post-processing | 400 |
| `max_iterations` | ReAct loop iterations for code refinement | 3 |
| `post_processor_type` | `"extract"` (intelligent) or `"react"` (code-only) | `"extract"` |
| `enable_reflection` | Validate output quality via LLM | true |

## Logging

By default, MCP+ runs quietly (WARNING level). For debugging:

```bash
export MCPPLUS_LOG_LEVEL=DEBUG
```

Output format:
- Normal: `[MCP+] Processing finance/get_data (12,450 chars)...`
- Debug: `[MCP+:PostProcessAgent] Iteration 1/3`

## Files

MCP+ adds these files:

```
~/.mcpplus/configs/
├── proxy_finance.json       # Config for finance-plus
├── proxy_weather.json       # Config for weather-plus
└── ...

~/.cursor/mcp.json           # Updated with -plus server entries
```

## Troubleshooting

### "No servers to wrap"
All servers may already have `-plus` versions. Check your mcp.json.

### API key not working
Ensure `OPENAI_API_KEY` is set before running `mcp-build-plus`. The key gets embedded in the generated configs.

### Post-processing not triggering
Output may be below the token threshold (400). Adjust `token_threshold` in the proxy config.

### Verbose logging in Cursor
Set `MCPPLUS_LOG_LEVEL=WARNING` (default) for quiet operation.

## Future Optimizations

To further reduce latency:

1. **Remove synthetic delays** - The 0.5s UX pauses in `react_extract_postprocess.py` can be removed for faster processing
2. **Skip validation step** - Disable `enable_reflection: false` to skip the second LLM call that validates output quality
3. **Use function calling** - Replace text-based JSON parsing with structured function calling for more reliable extraction

## API

### Programmatic Usage

```python
from mcpuniverse.mcpplus.mcp import MCPWrapperManager, WrapperConfig

# Create wrapper manager
wrapper_config = WrapperConfig(
    enabled=True,
    token_threshold=400,
    post_processor_type="extract"
)
manager = MCPWrapperManager(wrapper_config=wrapper_config)
manager.load_configs("path/to/server_list.json")

# Set LLM for post-processing
from mcpuniverse.llm.manager import ModelManager
llm = ModelManager().build_model(type="openai", config={"model_name": "gpt-4.1"})
manager.set_llm(llm)

# Build wrapped client
client = await manager.build_wrapped_client("finance")
result = await client.execute_tool(
    "get_stock_data",
    {"symbol": "AAPL", "expected_info": "Current price only"}
)
```
