# MCPUniverse

MCPUniverse is a comprehensive framework designed for developing, testing, and benchmarking AI agents. 
It offers a robust platform for building and evaluating both AI agents and LLMs across a wide range of task environments. 
The framework also supports seamless integration with external MCP servers and facilitates sophisticated agent orchestration workflows.

## Table of Contents

- [Installation Guide](#installation-guide)
- [System Architecture](#system-architecture)
- [How to Run Benchmarks](#how-to-run-benchmarks)
- [How to Create New Benchmarks](#how-to-create-new-benchmarks)
    - [Task definition](#task-definition)
    - [Benchmark definition](#benchmark-definition)
    - [Test benchmark](#test-benchmark)
    - [Visualization](#visualization)

## Installation Guide

We follow
the [feature branch workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/feature-branch-workflow)
in this repo for its simplicity. To ensure code quality, [PyLint](https://pylint.readthedocs.io/en/latest/)
is integrated into our CI to enforce Python coding standards.

### Prerequisites

* **Python**: Requires version 3.10 or higher.
* **PostgreSQL** (optional): Used for database storage and persistence.
* **Redis** (optional): Used for caching and memory management.

### Quick Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/SalesforceAIResearch/MCP-Universe.git
   cd MCP-Universe
   ```

2. **Create and activate virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -r dev-requirements.txt
   ```

4. **Platform-specific requirements**

   **Linux:**
   ```bash
   sudo apt-get install libpq-dev
   ```

   **macOS:**
   ```bash
   brew install postgresql
   ```

5. **Configure pre-commit hooks**
   ```bash
   pre-commit install
   ```

6. **Environment configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

## System Architecture

The MCPUniverse architecture consists of the following key components:

- **Agents** (`mcpuniverse/agent/`): Base implementations for different agent types
- **Workflows** (`mcpuniverse/workflows/`): Orchestration and coordination layer
- **MCP Servers** (`mcpuniverse/mcp/`): Protocol management and external service integration
- **LLM Integration** (`mcpuniverse/llm/`): Multi-provider language model support
- **Benchmarking** (`mcpuniverse/benchmark/`): Evaluation and testing framework
- **Dashboard** (`mcpuniverse/dashboard/`): Visualization and monitoring interface

The diagram below illustrates the high-level view:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application Layer                          │
├─────────────────────────────────────────────────────────────────┤
│  Dashboard  │    Web API      │   Python Lib   │   Benchmarks   │
│   (Gradio)  │   (FastAPI)     │                │                │
└─────────────┬─────────────────┬────────────────┬────────────────┘
              │                 │                │
┌─────────────▼─────────────────▼────────────────▼────────────────┐
│                      Orchestration Layer                        │
├─────────────────────────────────────────────────────────────────┤
│           Workflows           │        Benchmark Runner         │
│    (Chain, Router, etc.)      │      (Evaluation Engine)        │
└─────────────┬─────────────────┬────────────────┬────────────────┘
              │                 │                │
┌─────────────▼─────────────────▼────────────────▼────────────────┐
│                        Agent Layer                              │
├─────────────────────────────────────────────────────────────────┤
│  BasicAgent │   ReActAgent    │  FunctionCall  │     Other      │
│             │                 │     Agent      │     Agents     │
└─────────────┬─────────────────┬────────────────┬────────────────┘
              │                 │                │
┌─────────────▼─────────────────▼────────────────▼────────────────┐
│                      Foundation Layer                           │
├─────────────────────────────────────────────────────────────────┤
│   MCP Manager   │   LLM Manager   │  Memory Systems │  Tracers  │
│   (Servers &    │   (Multi-Model  │   (RAM, Redis)  │ (Logging) │
│    Clients)     │    Support)     │                 │           │
└─────────────────┴─────────────────┴─────────────────┴───────────┘
```

More information can be found [here](https://github.com/SalesforceAIResearch/MCP-Universe/blob/main/docs).

## How to Run Benchmarks

To run benchmarks, you first need to set environment variables:

1. Copy the `.env.example` file to a new file named .env.
2. In the `.env` file, set the required API keys for various services used by the agents,
   such as `OPENAI_API_KEY` and `GOOGLE_MAPS_API_KEY`.

To execute a benchmark programmatically:

```python
from mcpuniverse.tracer.collectors import MemoryCollector  # You can also use SQLiteCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner

async def test():
    trace_collector = MemoryCollector()
    # Choose a benchmark config file under the folder "mcpuniverse/benchmark/config"
    benchmark = BenchmarkRunner("dummy/benchmark_1.yaml")
    # Run the specified benchmark
    results = await benchmark.run(trace_collector=trace_collector)
    # Get traces
    trace_id = results[0].task_trace_ids["dummy/tasks/weather.json"]
    trace_records = trace_collector.get(trace_id)
```

## How to Create New Benchmarks

A benchmark is defined by three main configuration elements: the task definition,
agent/workflow definition, and the benchmark configuration itself. Below is an example
using a simple "weather forecasting" task.

### Task definition

The task definition is provided in JSON format, for example:

```json
{
  "category": "general",
  "question": "What's the weather in San Francisco now?",
  "mcp_servers": [
    {
      "name": "weather"
    }
  ],
  "output_format": {
    "city": "<City>",
    "weather": "<Weather forecast results>"
  },
  "evaluators": [
    {
      "func": "json -> get(city)",
      "op": "=",
      "value": "San Francisco"
    }
  ]
}
```

Field descriptions:

1. **category**: The task category, e.g., "general", "google-maps", etc. You can set any value for this property.
2. **question**: The main question you want to ask in this task. This is treated as a user message.
3. **mcp_servers**: A list of MCP servers which are supported in this framework.
4. **output_format**: The desired output format of agent responses.
5. **evaluators**: A list of tests to evaluate. For each test/evaluator, it has three attributes: "func" indicates
   how to extract values from the agent response, "op" is the comparison operator, and "value" is the ground-truth
   value.
   It will evaluate **op(func(...), value, op_args...)**. "op" can be "=", "<", ">" or other customized operators.

In "evaluators", you need to write a rule ("func" attribute) showing how to extract values for testing. In the example
above, "json -> get(city)" will first do JSON decoding and then extract the value of key "city". There are several
predefined funcs in this repo:

1. **json**: Perform JSON decoding.
2. **get**: Get a value of a key.
3. **len**: Get the length of a list.
4. **foreach**: Do a FOR-EACH loop.

For example, let's define

```python
data = {"x": [{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}]}
```

Then `get(x) -> foreach -> get(y) -> len` will do the followings:

1. Get value of "x": `[{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}]`.
2. Do foreach loop and get value of "y": `[[1], [1, 1], [1, 2, 3, 4]]`.
3. Get the length of each list: `[1, 2, 4]`.

If these predefined funcs are not enough, you can implement customized ones.
For more details, please check
this [doc](https://github.com/SalesforceAIResearch/MCP-Universe/blob/main/docs/custom-evaluators-guide.md).

### Benchmark definition

Define agent(s) and benchmark in a YAML file. Here’s a simple weather forecast benchmark:

```yaml
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  config:
    llm: llm-1
    instruction: You are an agent for weather forecasting.
    servers:
      - name: weather

---
kind: benchmark
spec:
  description: Test the agent for weather forecasting
  agent: ReAct-agent
  tasks:
    - dummy/tasks/weather.json
```

The benchmark definition mainly contains two parts: One is the definition of the agent,
and the other is the benchmark configuration. The benchmark configuration is simple where you just need to specify
the agent to use (by the defined agent name), and a list of tasks to evaluate. Each task entry is the task config file
path. It can be a full file path or a partial file path. If it is a partial file path (like "dummy/tasks/weather.json"),
it should be put in the
folder [mcpuniverse/benchmark/configs](https://github.com/SalesforceAIResearch/MCP-Universe/tree/main/mcpuniverse/benchmark/configs)
in this repo.

This framework offers a flexible way to define both simple agents (such as ReAct) and more complex, multi-step agent
workflows.

1. **Specify LLMs:** Begin by declaring the large language models (LLMs) you want the agents to use. Each LLM component
   must be assigned a unique name (e.g., `"llm-1"`). These names serve as identifiers that the framework uses to connect
   the different components together.
2. **Define an agent:** Next, define an agent by providing its name and selecting an agent class. Agent classes are
   available in
   the [mcpuniverse.agent](https://github.com/SalesforceAIResearch/MCP-Universe/tree/main/mcpuniverse/agent) package.
   Commonly used classes include `"basic"`, `"function-call"`, and `"react"`. Within the agent specification (
   `spec.config`), you must also indicate which LLM instance the agent should use by setting the `"llm"` field.
3. **Create complex workflows:** Beyond simple agents, the framework supports the definition of sophisticated,
   orchestrated workflows where multiple agents interact or collaborate to solve more complex tasks.

For example:

```yaml
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: basic-agent
  type: basic
  config:
    llm: llm-1
    instruction: Return the latitude and the longitude of a place.

---
kind: agent
spec:
  name: function-call-agent
  type: function-call
  config:
    llm: llm-1
    instruction: You are an agent for weather forecast. Please return the weather today at the given latitude and longitude.
    servers:
      - name: weather

---
kind: workflow
spec:
  name: orchestrator-workflow
  type: orchestrator
  config:
    llm: llm-1
    agents:
      - basic-agent
      - function-call-agent

---
kind: benchmark
spec:
  description: Test the agent for weather forecasting
  agent: orchestrator-workflow
  tasks:
    - dummy/tasks/weather.json
```

### Test benchmark

``` shell
PYTHONPATH=. python tests/benchmark/test_benchmark_google_maps.py
```

For further details, refer to the in-code documentation or existing configuration samples in the repository.

### Visualization

``` python
results = await benchmark.run(trace_collector=trace_collector, verbose=True)
```

Print out the intermediate results.