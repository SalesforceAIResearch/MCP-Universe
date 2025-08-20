# MCPUniverse

MCPUniverse is a framework for developing and benchmarking AI agents. It provides tools for creating, testing,
and evaluating different agent configurations across a variety of task environments.

## Table of Contents

- [MCPUniverse](#mcpuniverse)
  - [Table of Contents](#table-of-contents)
  - [Installation Guide](#installation-guide)
    - [Setup](#setup)
    - [Github MCP Server Installation](#github-mcp-server-installation)
  - [System Architecture](#system-architecture)
  - [How to Add New Benchmarks](#how-to-add-new-benchmarks)
    - [Task definition](#task-definition)
    - [Benchmark definition](#benchmark-definition)
    - [How to run benchmarks](#how-to-run-benchmarks)
    - [Test benchmark](#test-benchmark)
    - [Visualization](#visualization)

## Installation Guide

We follow
the [feature branch workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/feature-branch-workflow)
in this repo for its simplicity. To ensure code quality, [PyLint](https://pylint.readthedocs.io/en/latest/)
is integrated into our CI to enforce Python coding standards.

### Setup

1. Clone this repo to your machine:

``` shell
git clone https://github.com/SalesforceAIResearch/MCP-Universe.git
```

2. Install Python and create a virtual environment:
   MCPUniverse requires Python 3.10 or higher. Install Python 3.10 and set up
   a [virtual environment](https://virtualenv.pypa.io/en/latest/installation.html).

``` shell
pip3 install virtualenv
virtualenv venv -p python3.10
source venv/bin/activate
```

3. Install project dependencies:

```shell
pip install -r requirements.txt
pip install -r dev-requirements.txt
```
To run unit tests, you also need install postgres. On Linux:
```shell
sudo apt-get install libpq-dev
```
On macOS:
```shell
brew install postgresql
```

4. Setup pre-commit hooks to ensure all the checks are passing before committing the code and pushing to the branch

```shell
pre-commit install
```

### Github MCP Server Installation
```shell
git clone git@github.com:github/github-mcp-server.git
cd cmd/github-mcp-server
go build
```

- add github MCP config to /mcp/configs/server_list.json
```json
"github": {
  "stdio": {
    "command": "/path/to/github-mcp-server",
    "args": ["stdio"]
  },
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "{{GITHUB_PERSONAL_ACCESS_TOKEN}}"
  }
}
```


## System Architecture

The MCPUniverse architecture consists of several key components:

1. Agents and Workflows: YAML configurations that define the agents and workflows.
2. MCP Servers: External services that agents can interact with to complete tasks.
3. Benchmark/Task Definitions: Configurations that specify the task, required servers, and evaluation criteria.
4. Evaluators: Functions that assess the agent's output against predefined criteria.

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
│   (Servers &    │   (OpenAI,      │   (RAM, Redis)  │           │
│    Clients)     │   Claude, etc.) │                 │           │
└─────────────────┴─────────────────┴─────────────────┴───────────┘
```

More information can be found [here](https://github.com/SalesforceAIResearch/MCP-Universe/blob/main/docs).

## How to run benchmarks

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
    # Run a benchmark
    benchmark = BenchmarkRunner("dummy/benchmark_1.yaml")  # Choose a benchmark config file
    results = await benchmark.run(trace_collector=trace_collector)
    # Get traces
    trace_id = results[0].task_trace_ids["dummy/tasks/weather.json"]
    trace_records = trace_collector.get(trace_id)
```

## How to Add New Benchmarks

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

Then "get(x) -> foreach -> get(y) -> len" will do the followings:

1. Get value of "x": [{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}].
2. Do foreach loop and get value of "y": [[1], [1, 1], [1, 2, 3, 4]].
3. Get the length of each list: [1, 2, 4].

If these predefined funcs are not enough, you can implement customized ones.
Please check package "mcpuniverse.evaluator.functions".

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
it should be put in the folder "mcpuniverse/benchmark/configs" in this repo.

This framework provides a convenient way to define simple agents like ReAct or complex agent workflows.
Firstly, you need to specify the LLMs you want to use in the agents. Note that each component has a name, e.g., "llm-1".
The framework will use these names to link all the components together. Secondly, you can define an agent by specifying
the agent name and agent class. Agent classes are those defined in the package "mcpuniverse.agent". Some commonly used ones
are "basic", "function-call" and "react". You also need to specify the LLM used in this agent by setting "llm" in
spec.config.

Complex workflows (e.g., orchestrated agents) can also be defined. Example:

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