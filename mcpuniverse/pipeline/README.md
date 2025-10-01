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

## Usage (For testing purpose)

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

#### Using CLI (Recommended)

```bash
# Start workers with default settings
python -m mcpuniverse.pipeline start-workers --agent-collection /path/to/config.yaml

# Start workers with cleanup and custom settings
python -m mcpuniverse.pipeline start-workers \
  --agent-collection /path/to/config.yaml \
  --clean \
  --mq-type kafka \
  --max-queue-size 200
```

#### Programmatic Launch

```python
from mcpuniverse.pipeline.launcher import AgentPipeline

# Initialize pipeline
pipeline = AgentPipeline(
    config_path="/path/to/agent-config.yaml",
    max_queue_size=100,
    mq_type="kafka"
)

# Clean existing tasks (optional)
pipeline.delete_all_tasks()

# Start Celery workers
pipeline.start_celery_workers()
```

### 2. Sending Tasks

```python
from mcpuniverse.benchmark.task import TaskConfig

# Create task configuration
task_config = TaskConfig(
    task_name="example_task",
    question="What is the capital of France?",
    # ... other task parameters
)

# Send task to agent collection
success = pipeline.send_task(
    agent_collection_name="my-agents",
    task_config=task_config
)

if success:
    print("Task submitted successfully")
else:
    print("Task submission failed (queue full)")
```

### 3. Pulling Results

#### Real-time Consumption

```python
# Consume all results (blocks until interrupted)
for result in pipeline.pull_task_outputs():
    print(f"Result: {result['result']}")
    print(f"Evaluation: {result['evaluation_results']}")
    print(f"Trace: {result['trace']}")
```

#### CLI Consumption

```bash
# Consume results with message limit
python -m mcpuniverse.pipeline consume-outputs \
  --agent-collection /path/to/config.yaml \
  --max-messages 100
```

### 4. Task Management

#### Clean All Tasks

```python
# Programmatically
pipeline.delete_all_tasks()
```

```bash
# Via CLI
python -m mcpuniverse.pipeline clean-tasks --agent-collection /path/to/config.yaml
```

#### Monitor Queue Status

```python
# Check queue sizes
queue_size = pipeline._get_queue_size("agent_queue_name")
print(f"Queue size: {queue_size}")
```

## Configuration Examples

### Agent Collection Configuration

```yaml
# agent-config.yaml
kind: collection
spec:
  name: "text-processing-agents"
  config: "./agents/text-agent.yaml"
  number: 3
  context:
    - env:
        MODEL_NAME: "gpt-4"
        MAX_TOKENS: "2000"
```

### Environment Configuration

```bash
# .env file
AGENT_COLLECTION_CONFIG_FILE=./configs/agent-collection.yaml
REDIS_HOST=localhost
REDIS_PORT=6379
KAFKA_HOST=localhost
KAFKA_PORT=9092
MQ_TOPIC=agent-task-results
```

## Advanced Features

### Multiple Message Queue Support

```python
# Use RabbitMQ instead of Kafka
pipeline = AgentPipeline(
    config_path="/path/to/config.yaml",
    mq_type="rabbitmq"  # Will be supported when implemented
)
```

### Queue Size Management

```python
# Initialize with custom queue limits
pipeline = AgentPipeline(
    config_path="/path/to/config.yaml",
    max_queue_size=500  # Prevent queue overflow
)
```

### Error Handling

```python
try:
    pipeline.start_celery_workers()
except KeyboardInterrupt:
    print("Shutting down gracefully...")
except Exception as e:
    print(f"Pipeline error: {e}")
```

## Performance Considerations

- **Worker Scaling**: Add more Celery workers to increase throughput
- **Queue Management**: Monitor queue sizes to prevent memory issues
- **Redis Connection**: Use Redis clustering for high availability
- **Message Queue**: Configure Kafka partitions for better parallelism
- **Task Batching**: Group related tasks to reduce overhead

## Monitoring and Debugging

- **Celery Monitoring**: Use Flower for Celery worker monitoring
- **Queue Monitoring**: Monitor Redis and Kafka metrics
- **Logging**: Enable debug logging for detailed execution traces
- **Health Checks**: Regular Redis/Kafka connection health checks