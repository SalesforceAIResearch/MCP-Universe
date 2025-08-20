# MCPUniverse Configuration Guide

This guide provides comprehensive documentation for writing agent, workflow, and benchmark configurations in MCPUniverse.

## Table of Contents

1. [Overview](#overview)
2. [LLM Configuration](#llm-configuration)
3. [Agent Configuration](#agent-configuration)
4. [Workflow Configuration](#workflow-configuration)
5. [Benchmark Configuration](#benchmark-configuration)
6. [Task Definition](#task-definition)
7. [Complete Examples](#complete-examples)
8. [Best Practices](#best-practices)

## Overview

Component configurations use YAML documents separated by `---` delimiters. Each document represents a component (LLM, agent, workflow, or benchmark) and follows this structure:

```yaml
kind: <component_type>
spec:
  name: <component_name>
  type: <implementation_type>
  config:
    # Component-specific configuration
```

## LLM Configuration

The LLM configuration defines language models used by agents and workflows.

### Basic Structure

```yaml
kind: llm
spec:
  name: <unique_name>
  type: <provider_type>
  config:
    model_name: <model_identifier>
    # Additional provider-specific settings
```

### Example Providers

#### OpenAI
```yaml
kind: llm
spec:
  name: gpt-4o-llm
  type: openai
  config:
    model_name: gpt-4o
    temperature: 1.0
    max_completion_tokens: 2000
```

#### Claude (Anthropic)
```yaml
kind: llm
spec:
  name: claude-llm
  type: claude
  config:
    model_name: claude-3-5-sonnet-20241022
    temperature: 0.1
    max_completion_tokens: 4000
```

#### Google Gemini
```yaml
kind: llm
spec:
  name: gemini-llm
  type: gemini
  config:
    model_name: gemini-2.0-flash
    temperature: 0.5
```

## Agent Configuration

Agents are the core execution units that interact with LLMs and MCP servers.

### Basic Structure

```yaml
kind: agent
spec:
  name: <unique_name>
  type: <agent_type>
  config:
    llm: <llm_name (if required)>
    instruction: <system_instruction>
    # Agent-specific configuration
```

### Agent Types

#### Basic Agent
Simple LLM calling agent without tool use.

```yaml
kind: agent
spec:
  name: basic-agent
  type: basic
  config:
    llm: gpt-4o-llm
    instruction: You are a helpful assistant that provides information.
```

#### Function Call Agent
Stateless agent that makes function calls to MCP servers.

```yaml
kind: agent
spec:
  name: function-call-agent
  type: function-call
  config:
    llm: gpt-4o-llm
    instruction: You are an agent that can call functions to help users.
    servers:
      - name: weather
      - name: google-maps
```

#### ReAct Agent
Reasoning and acting agent that follows the ReAct pattern.

```yaml
kind: agent
spec:
  name: react-agent
  type: react
  config:
    llm: gpt-4o-llm
    instruction: You are a ReAct agent that reasons and acts.
    max_iterations: 10
    servers:
      - name: weather
      - name: google-search
```

#### Reflection Agent
Agent that uses reflection for improved reasoning.

```yaml
kind: agent
spec:
  name: reflection-agent
  type: reflection
  config:
    llm: gpt-4o-llm
    instruction: You are a reflection agent that improves through self-reflection.
    max_iterations: 5
    servers:
      - name: weather
```

### Agent Configuration Parameters

| Parameter | Type | Description                                       | Default |
|-----------|------|---------------------------------------------------|---------|
| `llm` | string | LLM component name                                | - |
| `instruction` | string | System instruction/prompt                         | - |
| `servers` | list | MCP servers to connect to                         | [] |
| `system_prompt` | string | Custom system prompt template path                | - |
| `max_iterations` | int | Max reasoning iterations (ReAct/Reflection)       | 5 |
| `summarize_tool_response` | bool | Summarize tool responses using LLM (ReAct)        | false |
| `use_llm_tool_api` | string | Enable LLM's native tool calling API ("yes"/"no") | "no" |
| `mcp_gateway_url` | string | MCP gateway server URL for remote tool access     | "" |

### Advanced Agent Configuration

#### LLM Tool API Integration

The `use_llm_tool_api` parameter enables integration with the LLM provider's native tool calling API, allowing for more efficient tool execution,
and the `mcp_gateway_url` parameter enables remote MCP server access through a gateway:

```yaml
kind: agent
spec:
  name: remote-agent
  type: basic
  config:
    llm: gpt-4.1-llm
    instruction: You are an agent that uses remote MCP servers.
    use_llm_tool_api: "yes"
    mcp_gateway_url: "https://your-gateway.example.com"
    servers:
      - name: weather
      - name: google-search
```

**Key Features:**
- **Remote Access**: Connect to MCP servers hosted on remote machines
- **SSE Transport**: Uses Server-Sent Events for communication
- **Gateway URL**: Points to the MCP gateway server endpoint
- **Integration**: Works with `use_llm_tool_api: "yes"` for optimal performance

## Workflow Configuration

Workflows orchestrate multiple agents to complete complex tasks.

### Basic Structure

```yaml
kind: workflow
spec:
  name: <unique_name>
  type: <workflow_type>
  config:
    # Workflow-specific configuration
```

### Workflow Types

#### Orchestrator Workflow
Coordinates multiple agents based on planning.

```yaml
kind: workflow
spec:
  name: orchestrator-workflow
  type: orchestrator
  config:
    llm: gpt-4o-llm
    agents:
      - basic-agent
      - function-call-agent
    plan_type: "full"  # or "iterative"
    max_iterations: 10
```

#### Evaluator-Optimizer Workflow
Executes the Evaluator-Optimizer workflow for iterative response improvement.

```yaml
kind: workflow
spec:
  name: evaluator-optimizer-workflow
  type: evaluator-optimizer
  config:
    optimizer: agent1
    evaluator: agent2
    max_iterations: 5
```

#### Chain Workflow
Sequential execution of agents.

```yaml
kind: workflow
spec:
  name: chain-workflow
  type: chain
  config:
    agents:
      - agent1
      - agent2
      - agent3
```

#### Parallelization Workflow
Executes multiple agents in parallel.

```yaml
kind: workflow
spec:
  name: parallel-workflow
  type: parallelization
  config:
    agents:
      - agent1
      - agent2
    aggregator: agent3
```

#### Router Workflow
Routes tasks to appropriate agents based on criteria.

```yaml
kind: workflow
spec:
  name: router-workflow
  type: router
  config:
    llm: gpt-4o-llm
    agents:
      - weather-agent
      - maps-agent
      - search-agent
```

## Benchmark Configuration

Benchmarks define evaluation scenarios for agents and workflows.

### Basic Structure

```yaml
kind: benchmark
spec:
  description: <benchmark_description>
  agent: <agent_or_workflow_name>
  tasks:
    - <task_file_path>
    - <task_file_path>
```

### Example

```yaml
kind: benchmark
spec:
  description: Weather forecasting benchmark
  agent: weather-agent
  tasks:
    - dummy/tasks/weather_1.json
    - dummy/tasks/weather_2.json
```

### Benchmark Parameters

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `description` | string | Human-readable description | Yes |
| `agent` | string | Target agent or workflow name | Yes |
| `tasks` | list | List of task file paths | Yes |

### Task File Paths

Task paths can be:
- **Relative**: `dummy/tasks/weather.json` (relative to `mcpuniverse/benchmark/configs/`)
- **Absolute**: `/full/path/to/task.json`

## Task Definition

Tasks are defined in JSON format and specify the evaluation criteria.

### Basic Structure

```json
{
  "category": "task_category",
  "question": "The task question or instruction",
  "mcp_servers": [
    {
      "name": "server_name"
    }
  ],
  "output_format": {
    "field1": "expected_format",
    "field2": "expected_format"
  },
  "evaluators": [
    {
      "func": "evaluation_function",
      "op": "comparison_operator",
      "value": "expected_value"
    }
  ]
}
```

### Task Components

#### MCP Servers
Specify required servers (optional):

```json
"mcp_servers": [
  {
    "name": "weather"
  },
  {
    "name": "google-maps",
  }
]
```

#### Output Format
Define expected response structure:

```json
"output_format": {
  "city": "<City Name>",
  "weather": "<Weather Description>",
  "temperature": "<Temperature in Celsius>",
  "forecast": [
    {
      "day": "<Day>",
      "condition": "<Condition>"
    }
  ]
}
```

#### Evaluators
Define evaluation criteria using function chains:

```json
"evaluators": [
  {
    "func": "json -> get(city)",
    "op": "=",
    "value": "San Francisco"
  },
  {
    "func": "json -> get(forecast) -> len",
    "op": ">",
    "value": 3
  },
  {
    "func": "json -> get(forecast) -> foreach -> get(day)",
    "op": "contains",
    "value": "Monday"
  }
]
```

#### Built-in Evaluation Functions

| Function | Description | Example |
|----------|-------------|---------|
| `json` | Parse JSON response | `json` |
| `get(key)` | Extract field value | `get(city)` |
| `len` | Get array/string length | `len` |
| `foreach` | Iterate over array | `foreach` |
| `contains` | Check if value exists | - |

#### Built-in Comparison Operators

| Operator   | Description                   | Example               |
|------------|-------------------------------|-----------------------|
| `=`        | Exact equality                | `"value": "expected"` |
| `>`        | Greater than                  | `"value": 5`          |
| `<`        | Less than                     | `"value": 10`         |
| `>=`       | Greater than or equal         | `"value": 0`          |
| `<=`       | Less than or equal            | `"value": 100`        |
| `in`       | Check if a value is in a list | `"value": "list"`     |
| `contains` | Contains substring/element    | `"value": "keyword"`  |

## Complete Examples

### Simple Weather Agent

```yaml
kind: llm
spec:
  name: gpt-4o-llm
  type: openai
  config:
    model_name: gpt-4o
    temperature: 0.1

---
kind: agent
spec:
  name: weather-agent
  type: react
  config:
    llm: gpt-4o-llm
    instruction: You are a weather forecasting agent.
    max_iterations: 5
    servers:
      - name: weather

---
kind: benchmark
spec:
  description: Weather forecasting evaluation
  agent: weather-agent
  tasks:
    - dummy/tasks/weather_1.json
    - dummy/tasks/weather_2.json
```

### Multi-Agent Workflow

```yaml
kind: llm
spec:
  name: planning-llm
  type: openai
  config:
    model_name: gpt-4o-mini

---
kind: llm
spec:
  name: execution-llm
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: location-agent
  type: basic
  config:
    llm: execution-llm
    instruction: Extract location information from user queries.

---
kind: agent
spec:
  name: weather-agent
  type: function-call
  config:
    llm: execution-llm
    instruction: Get weather information for specified locations.
    servers:
      - name: weather

---
kind: workflow
spec:
  name: travel-planner
  type: orchestrator
  config:
    llm: planning-llm
    agents:
      - location-agent
      - weather-agent

---
kind: benchmark
spec:
  description: Travel planning with weather consideration
  agent: travel-planner
  tasks:
    - test/travel/travel_task_0001.json
    - test/travel/travel_task_0002.json
```

This guide provides the foundation for creating effective MCPUniverse configurations. For additional examples, refer to the `mcpuniverse/benchmark/configs/` directory in the repository.