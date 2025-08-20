# MCPUniverse System Architecture

This document provides a comprehensive overview of the MCPUniverse system architecture, including its core components, design patterns, and how the different layers interact to provide a framework for developing and benchmarking AI agents using the Model Control Protocol (MCP).

## Overview

MCPUniverse is a modular framework designed to facilitate AI agent development, testing, and benchmarking. The system is built around the Model Control Protocol (MCP) standard, which enables agents to interact with external tools and services in a standardized way.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application Layer                          │
├─────────────────────────────────────────────────────────────────┤
│  Dashboard  │    Web API      │    Python Lib   │   Benchmarks  │
│   (Gradio)  │   (FastAPI)     │                 │               │
└─────────────┬─────────────────┬─────────────────┬───────────────┘
              │                 │                 │
┌─────────────▼─────────────────▼─────────────────▼──────────────┐
│                      Orchestration Layer                       │
├────────────────────────────────────────────────────────────────┤
│           Workflows           │        Benchmark Runner        │
│    (Chain, Router, etc.)      │      (Evaluation Engine)       │
└─────────────┬─────────────────┬─────────────────┬──────────────┘
              │                 │                 │
┌─────────────▼─────────────────▼─────────────────▼──────────────┐
│                        Agent Layer                             │
├────────────────────────────────────────────────────────────────┤
│  BasicAgent │   ReActAgent    │  FunctionCall   │     Other    │
│             │                 │     Agent       │     Agents   │
└─────────────┬─────────────────┬─────────────────┬──────────────┘
              │                 │                 │
┌─────────────▼─────────────────▼─────────────────▼──────────────┐
│                      Foundation Layer                          │
├────────────────────────────────────────────────────────────────┤
│   MCP Manager   │   LLM Manager   │  Memory Systems │  Tracers │
│   (Servers &    │   (OpenAI,      │   (RAM, Redis)  │          │
│    Clients)     │   Claude, etc.) │                 │          │
└─────────────────┴─────────────────┴─────────────────┴──────────┘
```

## Core Components

### 1. Agent Layer (`mcpuniverse/agent/`)

The agent layer is the core of MCPUniverse, providing different types of AI agents that can reason, act, and interact with external tools.

#### BaseAgent
- **Purpose**: Abstract base class that all agents inherit from
- **Key Features**:
  - MCP server connection management
  - Tool execution capabilities
  - Configuration management
  - Tracing and debugging support
  - Lifecycle management (initialize, execute, cleanup)

#### Agent Types
- **BasicAgent**: Simple LLM interaction agent for straightforward tasks
- **ReActAgent**: Implements reasoning and acting pattern with iterative thinking
- **FunctionCallAgent**: Uses native LLM tool calling APIs
- **ReflectionAgent**: Self-reflective agent with memory capabilities
- **ClaudeCodeAgent**: Specialized agent for code-related tasks

#### Key Interfaces
```python
class Executor:
    async def execute(message, **kwargs) -> AgentResponse
    async def initialize()
    async def cleanup()
    def set_name(name: str)
```

### 2. MCP Layer (`mcpuniverse/mcp/`)

Manages Model Control Protocol servers and clients, enabling agents to interact with external tools and services.

#### MCPManager
- **Purpose**: Central management of MCP server configurations and client connections
- **Key Features**:
  - Server configuration loading from JSON
  - Dynamic server registration and management
  - Client building for stdio and SSE transports
  - Environment variable templating
  - Parameter validation

#### MCPClient
- **Purpose**: Handles connections to individual MCP servers
- **Supported Transports**: stdio, SSE (Server-Sent Events)
- **Operations**: Tool execution, resource access, server communication

#### Example built-in Servers
- **Weather**: National Weather Service API integration
- **Google Search**: Search functionality via SERP API
- **Google Sheets**: Spreadsheet operations
- **Wikipedia**: Knowledge base access
- **Blender**: 3D modeling operations
- **Yahoo Finance**: Financial data access

### 3. LLM Layer (`mcpuniverse/llm/`)

Provides unified interface to multiple language model providers.

#### BaseLLM
- **Purpose**: Abstract base class for all LLM implementations
- **Key Features**:
  - Async generation capabilities
  - Message handling and formatting
  - Context management
  - Configuration export/import

#### Supported Providers
- **OpenAI**: OpenAI models
- **Anthropic**: Claude models
- **Google**: Gemini models
- **Mistral**: Mistral AI models
- **Ollama**: Local model serving
- **Grok**: xAI's Grok models
- **DeepSeek**: DeepSeek models

### 4. Workflow Layer (`mcpuniverse/workflows/`)

Orchestrates complex multi-agent interactions and task execution patterns.

#### BaseWorkflow
- **Purpose**: Foundation for workflow implementations
- **Key Features**:
  - Agent lifecycle management
  - Execution coordination
  - Result aggregation
  - Error handling and recovery

#### Workflow Types
- **Chain**: Sequential agent execution
- **Router**: Conditional agent selection based on input
- **Parallelization**: Concurrent agent execution
- **Orchestrator**: Complex multi-agent coordination
- **EvaluatorOptimizer**: Agent performance optimization

### 5. Benchmark Layer (`mcpuniverse/benchmark/`)

Comprehensive system for evaluating agent performance across different tasks and domains.

#### BenchmarkRunner
- **Purpose**: Executes benchmarks and collects performance data
- **Key Features**:
  - YAML-based configuration
  - Task definition and execution
  - Result collection and analysis
  - Performance metrics calculation

#### Task System
- **Task Definition**: JSON-based task specifications
- **Evaluation**: Custom evaluators for different domains
- **Metrics**: Success rates, execution time, resource usage

#### Supported Domains
- **Google Maps**: Location and navigation tasks
- **GitHub**: Repository and code management
- **Blender**: 3D modeling and rendering
- **Playwright**: Web automation
- **Financial**: Yahoo Finance integration
- **Multi-server**: Complex cross-domain tasks

### 6. Evaluation Layer (`mcpuniverse/evaluator/`)

Domain-specific evaluation functions for assessing agent performance.

#### Evaluator System
- **Purpose**: Automated assessment of agent outputs
- **Key Features**:
  - JSON-based output validation
  - Custom evaluation functions
  - Domain-specific scoring
  - Comparative analysis

### 7. Tracing Layer (`mcpuniverse/tracer/`)

Comprehensive debugging and monitoring system for agent execution.

#### Tracer
- **Purpose**: Execution tracking and debugging
- **Key Features**:
  - Hierarchical trace collection
  - Performance monitoring
  - Error tracking
  - Execution replay

#### Collectors
- **Memory**: In-memory trace storage
- **File**: Persistent file-based storage
- **SQLite**: Database-backed trace storage

### 8. Memory Layer (`mcpuniverse/agent/memory/`)

Provides memory capabilities for agents to maintain context across interactions.

#### Memory Types
- **Short-term Memory**: 
  - **RAM**: In-memory storage for session data
  - **Redis**: Distributed memory for scalable deployments
- **Context Management**: Conversation and task context preservation

### 9. Callback System (`mcpuniverse/callbacks/`)

Event-driven system for monitoring and reacting to agent execution events.

#### Callback Types
- **Status Updates**: Execution state changes
- **Error Handling**: Exception and failure notifications
- **Performance Monitoring**: Metrics and timing data
- **Custom Handlers**: Application-specific event processing

### 10. Application Layer (`mcpuniverse/app/`)

Web application interface providing REST APIs and user interface.

#### Web API (FastAPI)
- **Endpoints**: Agent management, benchmark execution, task monitoring
- **Authentication**: Token-based security
- **Database**: PostgreSQL for persistent storage
- **Background Tasks**: Celery for async processing

#### Dashboard (Gradio)
- **Purpose**: Interactive web interface for agent testing
- **Features**: Real-time execution monitoring, result visualization

## Data Flow

### 1. Agent Execution Flow
```
User Input → Agent.execute() → LLM.generate() → Tool Execution → Response
     ↓              ↓              ↓              ↓              ↓
  Callbacks ←   Tracer     ←   Callbacks   ←   MCP Client  ←  Evaluation
```

### 2. MCP Tool Execution Flow
```
Agent → MCPManager → MCPClient → MCP Server → External Service
  ↑         ↑           ↑           ↑             ↑
Config    Server     Transport   Tool Call    API/Service
Loading   Selection   Protocol    Execution    Response
```

### 3. Benchmark Execution Flow
```
YAML Config → BenchmarkRunner → Task Execution → Evaluation → Results
     ↓              ↓               ↓              ↓          ↓
  Task Def    Agent Creation   Agent Execution  Scoring   Report Gen
```

## Configuration Management

### 1. Hierarchical Configuration
- **Global**: Framework-level settings
- **Agent**: Agent-specific configurations
- **Server**: MCP server configurations
- **Task**: Benchmark task definitions

### 2. Environment Variable Templating
```json
{
  "env": {
    "API_KEY": "{{MY_API_KEY}}",
    "PORT": "{{PORT}}"
  }
}
```

### 3. Dynamic Configuration
Runtime configuration updates through the MCPManager API:
```python
manager.add_server_config("new-server", config)
```

This architecture provides a solid foundation for AI agent development while maintaining flexibility, scalability, and extensibility. The modular design allows developers to focus on specific aspects of agent behavior while leveraging the robust infrastructure for common operations like tool execution, memory management, and performance evaluation.