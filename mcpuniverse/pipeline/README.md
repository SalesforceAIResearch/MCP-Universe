# Agent Pipeline

A distributed task execution framework for running AI agents asynchronously using Celery workers and message queues.

## Purpose

The Agent Pipeline package provides a scalable, distributed infrastructure for executing AI agent tasks in a production environment. It enables:

- **Distributed Processing**: Execute agent tasks across multiple workers for improved throughput
- **Asynchronous Execution**: Non-blocking task submission and result retrieval
- **Scalable Architecture**: Add/remove workers dynamically based on load
- **Multi-Queue Support**: Support for different message queue backends (Kafka, RabbitMQ)

## Architecture Design

### Data Flow Diagram

```
┌─────────────────┐
│     Client      │
│   (Submit Task) │
└─────────────────┘
          │
          │ 1. send_task()
          ▼
┌─────────────────┐    2. Round-robin    ┌─────────────────┐
│  AgentPipeline  │───── scheduling ───▶ │ Celery Queues   │
│   (Launcher)    │                      │ (Redis Backend) │
└─────────────────┘                      └─────────────────┘
          ▲                                        │
          │ 6. pull_task_outputs()                 │ 3. Worker pickup
          │                                        ▼ 
┌─────────────────┐                      ┌─────────────────┐
│ Message Queue   │◀─── 5. Publish ──────│ Celery Workers  │
│ (Kafka/RabbitMQ)│      results         │  (AgentTask)    │
│                 │                      └─────────────────┘
│ ┌─────────────┐ │                                │
│ │Task Results │ │                                │ 4. Execute agents
│ │Evaluation   │ │                                ▼   
│ │Trace Data   │ │                      ┌─────────────────┐
│ └─────────────┘ │                      │  Agent Engine   │
└─────────────────┘                      │  (LLM + Tools)  │
                                         └─────────────────┘
```
1. **Task Submission**: Client submits tasks via `AgentPipeline.send_task()`
2. **Queue Distribution**: Tasks distributed to Celery queues using round-robin strategy
3. **Worker Execution**: Celery workers pick up tasks, execute agents and run evaluations
4. **Result Publication**: Task outputs published to message queue
5. **Result Consumption**: Clients consume results via `AgentPipeline.pull_task_outputs()`

### Key Classes

1. **`AgentPipeline`**: Main orchestrator for distributed task execution
   - Manages Celery workers and message queue connections
   - Handles task distribution with round-robin scheduling
   - Provides functions for sending tasks and pulling task results

2. **`AgentTask`**: Celery task implementation for agent execution
   - Executes individual agent tasks asynchronously
   - Publishes results to message queue for consumption
   - Handles agent lifecycle and resource cleanup

3. **`MQFactory`**: Factory for creating message queue producers/consumers
   - Supports multiple MQ backends (Kafka, RabbitMQ)
   - Provides environment-based configuration
   - Type-safe producer/consumer creation

4. **Message Queue Components**:
   - **`Producer`**: Publishes task results to message topics
   - **`Consumer`**: Consumes task outputs with generator interface
   - **Serialization utilities**: JSON-based task input/output serialization

### Configuration

The pipeline uses environment variables for configuration:

```bash
# Required
AGENT_COLLECTION_CONFIG_FILE=/path/to/agent-config.yaml

# Redis (Celery backend)
REDIS_HOST=localhost
REDIS_PORT=6379

# Message Queue
KAFKA_HOST=localhost
KAFKA_PORT=9092
MQ_TOPIC=agent-task-mq
```

### Agent Collection Configuration

Agent collections define how agents are deployed and managed in the pipeline. The configuration follows a YAML structure that specifies agent properties, deployment parameters, and execution context.
You can find an example in the folder `tests/data/collection`.

#### Basic Structure

```yaml
kind: collection
spec:
  name: "my-agent-collection"
  config: "./path/to/agent-config.yaml"
  number: 3
  context:
    - env:
        GITHUB_PERSONAL_ACCESS_TOKEN: xxx
        GITHUB_PERSONAL_ACCOUNT_NAME: xxx
    - env:
        GITHUB_PERSONAL_ACCESS_TOKEN: yyy
        GITHUB_PERSONAL_ACCOUNT_NAME: yyy
```

#### Configuration Parameters

- **`kind`**: Always set to `"collection"` for agent collections
- **`spec.name`**: Unique identifier for the agent collection
- **`spec.config`**: Path to the individual agent configuration file
- **`spec.number`**: Number of agent instances to deploy
- **`spec.context`**: Execution context including environment variables

Note that `spec.number` specifies the number of agents to create for **each context**:
- If `spec.context` is not set, or contains only one context, the total number of created agents equals `spec.number`.
- If `spec.context` includes multiple contexts, `spec.number` agents will be created for each one. 
- If you define multiple contexts because some tools have concurrency issues, you must set `spec.number` to `1`.

## Usage (For local test)

### 1. Launching the Pipeline

#### Prerequisites

Before starting the pipeline, ensure Redis and Kafka are running:

```bash
# Start Redis (required for Celery backend)
make redis

# Start Kafka (required for message queue)
make kafka
```

To stop and clean up the services when done:

```bash
# Stop Redis
make dropredis

# Stop Kafka
make dropkafka
```

#### Start Celery Workers

Open a new terminal and run the following command, keeping it running in the background:
```bash
# Start workers with default settings
python -m mcpuniverse.pipeline start-workers --agent-collection /path/to/config.yaml

# Or start workers with cleanup and custom settings
python -m mcpuniverse.pipeline start-workers \
  --agent-collection /path/to/config.yaml \
  --clean \
  --mq-type kafka \
  --max-queue-size 200
```

### 2. Sending Tasks

This package provides a simple interface to send tasks:
```python
from mcpuniverse.benchmark.task import TaskConfig
from mcpuniverse.pipeline.launcher import AgentPipeline

# Initialize pipeline (config_path should be the same as the one used to launch Celery workers)
pipeline = AgentPipeline(config_path="/path/to/agent-config.yaml")

# Create task configuration
task_config = TaskConfig(
    task_name="example_task",
    question="What is the capital of France?",
    # ... other task parameters
)

# Send task to agent collection (`agent_collection_name` should match the collection name defined in the config)
success = pipeline.send_task(
    agent_collection_name="my-agent-collection",
    task_config=task_config
)
if success:
    print("Task submitted successfully")
else:
    print("Task submission failed (queue full)")
```

### 3. Pulling Results

#### Real-time Consumption

The following code snippet can be used to implement a PyTorch dataset:
```python
# Consume all results (blocks until interrupted)
for result in pipeline.pull_task_outputs():
    print(f"Result: {result['result']}")
    print(f"Evaluation: {result['evaluation_results']}")
    print(f"Trace: {result['trace']}")
```

#### CLI Consumption (for testing purpose)

```bash
# Consume results with message limit
python -m mcpuniverse.pipeline consume-outputs \
  --agent-collection /path/to/config.yaml
```
