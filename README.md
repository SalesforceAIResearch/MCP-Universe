<div align="center">

# <img src="assets/icon.png" alt="MCP-Universe" width="23" height="23"> MCP-Universe

[![Paper](https://img.shields.io/badge/Paper-arXiv:2508.14704-B31B1B?style=for-the-badge&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2508.14704)
[![Website](https://img.shields.io/badge/Website-Live-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white)](https://mcp-universe.github.io/)
[![Leaderboard](https://img.shields.io/badge/Leaderboard-Results-FF6B35?style=for-the-badge&logo=chartdotjs&logoColor=white)](https://mcp-universe.github.io/#results)
[![Discord](https://img.shields.io/badge/Discord-Join_Community-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/t9tU77GF)

</div>

---

## What is MCP-Universe?

MCP-Universe is a comprehensive framework designed for developing, testing, and benchmarking AI agents. It offers a robust platform for building and evaluating both AI agents and LLMs across a wide range of task environments. The framework also supports seamless integration with external MCP servers and facilitates sophisticated agent orchestration workflows.

<div align="center">

![MCP-Universe Introduction](assets/intro-mcp-universe.png)

</div>

Unlike existing benchmarks that rely on overly simplistic tasks, MCP-Universe addresses critical gaps by evaluating LLMs in **real-world scenarios** through interaction with actual MCP servers, capturing real application challenges such as:

- 🎯 **Long-horizon reasoning** across multi-step tasks
- 🔧 **Large, unfamiliar tool spaces** with diverse MCP servers  
- 🌍 **Real-world data sources** and live environments
- ⚡ **Dynamic evaluation** with time-sensitive ground truth

## Performance Highlights

Even state-of-the-art models show significant limitations in real-world MCP interactions:

- 🥇 **GPT-5**: 43.72% success rate
- 🥈 **Grok-4**: 33.33% success rate  
- 🥉 **Claude-4.0-Sonnet**: 29.44% success rate

*This highlights the challenging nature of real-world MCP server interactions and substantial room for improvement in current LLM agents.*

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Quick Test](#quick-test)
- [Evaluating LLMs and Agents](#evaluating-llms-and-agents)
    - [Prerequisites](#prerequisites-1)
    - [Environment Configuration](#environment-configuration)
    - [Benchmark Configuration](#benchmark-configuration)
    - [Execution](#execution)
    - [Save the running log](#save-the-running-log)
    - [Save the benchmark result to a report](#save-the-benchmark-result-to-a-report)
    - [Visualize the agent running information](#visualize-the-agent-running-information)
- [Creating Custom Benchmarks](#creating-custom-benchmarks)
    - [Task definition](#task-definition)
    - [Benchmark definition](#benchmark-definition)
- [Citation](#citation)

## Architecture Overview

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

## Getting Started

We follow
the [feature branch workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/feature-branch-workflow)
in this repo for its simplicity. To ensure code quality, [PyLint](https://pylint.readthedocs.io/en/latest/)
is integrated into our CI to enforce Python coding standards.

### Prerequisites

* **Python**: Requires version 3.10 or higher.
* **Docker**: Used for running Dockerized MCP servers.
* **PostgreSQL** (optional): Used for database storage and persistence.
* **Redis** (optional): Used for caching and memory management.

### Installation

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

### Quick Test

To run benchmarks, you first need to set environment variables:

1. Copy the `.env.example` file to a new file named `.env`.
2. In the `.env` file, set the required API keys for various services used by the agents,
   such as `OPENAI_API_KEY` and `GOOGLE_MAPS_API_KEY`.

To execute a benchmark programmatically:

```python
from mcpuniverse.tracer.collectors import MemoryCollector  # You can also use SQLiteCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner

async def test():
    trace_collector = MemoryCollector()
    # Choose a benchmark config file under the folder "mcpuniverse/benchmark/configs"
    benchmark = BenchmarkRunner("dummy/benchmark_1.yaml")
    # Run the specified benchmark
    results = await benchmark.run(trace_collector=trace_collector)
    # Get traces
    trace_id = results[0].task_trace_ids["dummy/tasks/weather_1.json"]
    trace_records = trace_collector.get(trace_id)
```

## Evaluating LLMs and Agents

This section provides comprehensive instructions for evaluating LLMs and AI agents using the MCP-Universe benchmark suite. The framework supports evaluation across multiple domains including web search, location navigation, browser automation, financial analysis, repository management, and 3D design.

### Prerequisites

Before running benchmark evaluations, ensure you have completed the [Getting Started](#getting-started) section and have the following:

- Python: Version 3.10 or higher
- Docker: Installed and available in your environment
- All required dependencies installed via `pip install -r requirements.txt`
- Active virtual environment
- Appropriate API access for the services you intend to evaluate

### Environment Configuration

#### 1. Initial Setup

Copy the environment template and configure your API credentials:

```bash
cp .env.example .env
```

#### 2. API Keys and Configuration

Configure the following environment variables in your `.env` file. The required keys depend on which benchmark domains you plan to evaluate:

##### Core LLM Providers

| Environment Variable | Provider | Description | Required For |
|---------------------|----------|-------------|--------------|
| `OPENAI_API_KEY` | OpenAI | API key for GPT models (gpt-5, etc.) | All domains |
| `ANTHROPIC_API_KEY` | Anthropic | API key for Claude models | All domains |
| `GEMINI_API_KEY` | Google | API key for Gemini models | All domains |

> **Note**: You only need to configure the API key for the LLM provider you intend to use in your evaluation.

##### Domain-Specific Services

| Environment Variable | Service | Description | Setup Instructions |
|---------------------|---------|-------------|-------------------|
| `SERP_API_KEY` | SerpAPI | Web search API for search benchmark evaluation | [Get API key](https://serpapi.com/) |
| `GOOGLE_MAPS_API_KEY` | Google Maps | Geolocation and mapping services | [Setup Guide](https://console.cloud.google.com/google/maps-apis/credentials) |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub | Personal access token for repository operations | [Token Setup](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) |
| `GITHUB_PERSONAL_ACCOUNT_NAME` | GitHub | Your GitHub username | N/A |
| `NOTION_API_KEY` | Notion | Integration token for Notion workspace access | [Integration Setup](https://developers.notion.com/docs/authorization#obtaining-a-token) |
| `NOTION_ROOT_PAGE` | Notion | Root page ID for your Notion workspace | See configuration example below |

##### System Paths

| Environment Variable | Description | Example |
|---------------------|-------------|---------|
| `BLENDER_APP_PATH` | Full path to Blender executable (we used v4.4.0) | `/Applications/Blender.app/Contents/MacOS/Blender` |
| `MCPUniverse_DIR` | Absolute path to your MCP-Universe repository | `/Users/username/MCP-Universe` |

##### Configuration Examples

**Notion Root Page ID:**
If your Notion page URL is:
```
https://www.notion.so/your_workspace/MCP-Evaluation-1dd6d96e12345678901234567eaf9eff
```
Set `NOTION_ROOT_PAGE=MCP-Evaluation-1dd6d96e12345678901234567eaf9eff`

**Blender Installation:**
1. Download Blender v4.4.0 from [blender.org](https://www.blender.org/)
2. Install our modified Blender MCP server following the [installation guide](docs/blender-setup.md)
3. Set the path to the Blender executable

##### ⚠️ Security Recommendations

> **🔒 IMPORTANT SECURITY NOTICE**
> 
> Please read and follow these security guidelines carefully before running benchmarks:

- **🚨 GitHub Integration**: **CRITICAL** - We strongly recommend using a dedicated test GitHub account for benchmark evaluation. The AI agent will perform real operations on GitHub repositories, which could potentially modify or damage your personal repositories.

- **🔐 API Key Management**: 
  - Store API keys securely and never commit them to version control
  - Use environment variables or secure key management systems
  - Regularly rotate your API keys for enhanced security

- **🛡️ Access Permissions**: 
  - Grant minimal necessary permissions for each service integration
  - Review and limit API key scopes to only required operations
  - Monitor API usage and set appropriate rate limits

- **⚡ Blender Operations**: The 3D design benchmarks will execute Blender commands that may modify or create files on your system. Ensure you have adequate backups and run in an isolated environment if necessary.

### Benchmark Configuration

#### Domain-Specific Configuration Files

Each benchmark domain has a dedicated YAML configuration file located in `mcpuniverse/benchmark/configs/test/`. To evaluate your LLM/agent, modify the appropriate configuration file:

| Domain | Configuration File | Description |
|--------|-------------------|-------------|
| Web Search | `web_search.yaml` | Search engine and information retrieval tasks |
| Location Navigation | `location_navigation.yaml` | Geographic and mapping-related queries |
| Browser Automation | `browser_automation.yaml` | Web interaction and automation scenarios |
| Financial Analysis | `financial_analysis.yaml` | Market data analysis and financial computations |
| Repository Management | `repository_management.yaml` | Git operations and code repository tasks |
| 3D Design | `3d_design.yaml` | Blender-based 3D modeling and design tasks |

#### LLM Model Configuration

In each configuration file, update the LLM specification to match your target model:

```yaml
kind: llm
spec:
  name: llm-1
  type: openai  # or anthropic, google, etc.
  config:
    model_name: gpt-4o  # Replace with your target model
```

### Execution

#### Running Individual Benchmarks

Execute specific domain benchmarks using the following commands:

```bash
# Set Python path and run individual benchmarks
export PYTHONPATH=.

# Location Navigation
python tests/benchmark/test_benchmark_location_navigation.py

# Browser Automation  
python tests/benchmark/test_benchmark_browser_automation.py

# Financial Analysis
python tests/benchmark/test_benchmark_financial_analysis.py

# Repository Management
python tests/benchmark/test_benchmark_repository_management.py

# Web Search
python tests/benchmark/test_benchmark_web_search.py

# 3D Design
python tests/benchmark/test_benchmark_3d_design.py
```

#### Batch Execution

For comprehensive evaluation across all domains:

```bash
#!/bin/bash
export PYTHONPATH=.

domains=("location_navigation" "browser_automation" "financial_analysis" 
         "repository_management" "web_search" "3d_design")

for domain in "${domains[@]}"; do
    echo "Running benchmark: $domain"
    python "tests/benchmark/test_benchmark_${domain}.py"
    echo "Completed: $domain"
done
```

### Save the running log

If you want to save the running log, you can pass the `trace_collector` to the benchmark run function:

```python
from mcpuniverse.tracer.collectors import FileCollector

trace_collector = FileCollector(log_file="log/location_navigation.log")
benchmark_results = await benchmark.run(trace_collector=trace_collector)
```

### Save the benchmark result to a report 

If you want to save a report of the benchmark result, you can use `BenchmarkReport` to dump a report:

```python
from mcpuniverse.benchmark.report import BenchmarkReport

report = BenchmarkReport(benchmark, trace_collector=trace_collector)
report.dump()
```

### Visualize the agent running information

To run the benchmark with intermediate results and see real-time progress, pass `callbacks=get_vprint_callbacks()` to the run function:

```python
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks

benchmark_results = await benchmark.run(
    trace_collector=trace_collector, 
    callbacks=get_vprint_callbacks()
)
```

This will print out the intermediate results as the benchmark runs.


For further details, refer to the in-code documentation or existing configuration samples in the repository.

## Creating Custom Benchmarks

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
3. **mcp_servers**: A list of MCP servers that are supported in this framework.
4. **output_format**: The desired output format of agent responses.
5. **evaluators**: A list of tests to evaluate. For each test/evaluator, it has three attributes: "func" indicates
   how to extract values from the agent response, "op" is the comparison operator, and "value" is the ground-truth
   value.
   It will evaluate **op(func(...), value, op_args...)**. "op" can be "=", "<", ">" or other customized operators.

In "evaluators", you need to write a rule ("func" attribute) showing how to extract values for testing. In the example
above, "json -> get(city)" will first do JSON decoding and then extract the value of key "city". There are several
predefined funcs in this repo:

1. **json**: Perform JSON decoding.
2. **get**: Get the value of a key.
3. **len**: Get the length of a list.
4. **foreach**: Do a FOR-EACH loop.

For example, let's define

```python
data = {"x": [{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}]}
```

Then `get(x) -> foreach -> get(y) -> len` will do the following:

1. Get the value of "x": `[{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}]`.
2. Do a foreach loop and get the value of "y": `[[1], [1, 1], [1, 2, 3, 4]]`.
3. Get the length of each list: `[1, 2, 4]`.

If these predefined functions are not enough, you can implement custom ones.
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

The benchmark definition mainly contains two parts: the agent definition and the benchmark configuration. The benchmark configuration is simple—you just need to specify the agent to use (by the defined agent name) and a list of tasks to evaluate. Each task entry is the task config file
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

## Citation

If you use MCP-Universe in your research, please cite our paper:

```bibtex
@misc{mcpuniverse,
  title={MCP-Universe: Benchmarking Large Language Models with Real-World Model Context Protocol Servers},
  author={Ziyang Luo and Zhiqi Shen and Wenzhuo Yang and Zirui Zhao and Prathyusha Jwalapuram and Amrita Saha and Doyen Sahoo and Silvio Savarese and Caiming Xiong and Junnan Li},
  year={2025},
  eprint={2508.14704},
  archivePrefix={arXiv},
  primaryClass={cs.AI},
  url={https://arxiv.org/abs/2508.14704}, 
}
```
