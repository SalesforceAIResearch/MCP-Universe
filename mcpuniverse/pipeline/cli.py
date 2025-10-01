"""CLI for managing pipeline workers and tasks."""

import os
from typing import Optional, Literal

import click
from mcpuniverse.pipeline.launcher import AgentPipeline

MQType = Literal["kafka", "rabbitmq"]


@click.group()
def cli():
    """Pipeline management CLI."""


@cli.command()
@click.option(
    "--agent-collection",
    required=True,
    help="Path to agent collection configuration file"
)
@click.option(
    "--mq-type",
    type=click.Choice(["kafka", "rabbitmq"]),
    default="kafka",
    help="Message queue type (default: kafka)"
)
@click.option(
    "--clean",
    is_flag=True,
    help="Delete all tasks before starting workers"
)
@click.option(
    "--max-queue-size",
    type=int,
    default=100,
    help="Maximum Celery queue size (default: 100)"
)
@click.option(
    "--redis-host",
    help="Redis host (overrides REDIS_HOST env var)"
)
@click.option(
    "--redis-port",
    type=int,
    help="Redis port (overrides REDIS_PORT env var)"
)
@click.option(
    "--kafka-host",
    help="Kafka host (overrides KAFKA_HOST env var)"
)
@click.option(
    "--kafka-port",
    type=int,
    help="Kafka port (overrides KAFKA_PORT env var)"
)
@click.option(
    "--mq-topic",
    help="Message queue topic (overrides MQ_TOPIC env var)"
)
def start_workers(
        agent_collection: str,
        mq_type: str,
        clean: bool,
        max_queue_size: int,
        redis_host: Optional[str],
        redis_port: Optional[int],
        kafka_host: Optional[str],
        kafka_port: Optional[int],
        mq_topic: Optional[str]
):
    """Start Celery workers for agent collections."""
    # Set environment variables
    os.environ["AGENT_COLLECTION_CONFIG_FILE"] = agent_collection

    if redis_host:
        os.environ["REDIS_HOST"] = redis_host
    if redis_port:
        os.environ["REDIS_PORT"] = str(redis_port)
    if kafka_host:
        os.environ["KAFKA_HOST"] = kafka_host
    if kafka_port:
        os.environ["KAFKA_PORT"] = str(kafka_port)
    if mq_topic:
        os.environ["MQ_TOPIC"] = mq_topic

    click.echo(f"Starting pipeline with agent collection: {agent_collection}")
    click.echo(f"Message queue type: {mq_type}")
    click.echo(f"Max queue size: {max_queue_size}")

    # Initialize pipeline
    pipeline = AgentPipeline(
        config_path=agent_collection,
        max_queue_size=max_queue_size,
        mq_type=mq_type  # type: ignore
    )

    # Clean tasks if requested
    if clean:
        click.echo("Cleaning existing tasks...")
        pipeline.delete_all_tasks()
        click.echo("Tasks cleaned successfully")

    # Start workers
    click.echo("Starting Celery workers...")
    try:
        pipeline.start_celery_workers()
    except KeyboardInterrupt:
        click.echo("\nShutting down workers...")
    except Exception as e:
        click.echo(f"Error starting workers: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option(
    "--agent-collection",
    required=True,
    help="Path to agent collection configuration file"
)
@click.option(
    "--mq-type",
    type=click.Choice(["kafka", "rabbitmq"]),
    default="kafka",
    help="Message queue type (default: kafka)"
)
def clean_tasks(
        agent_collection: str,
        mq_type: str
):
    """Delete all scheduled tasks from Celery queues."""
    click.echo("Cleaning all scheduled tasks...")

    pipeline = AgentPipeline(
        config_path=agent_collection,
        mq_type=mq_type  # type: ignore
    )
    pipeline.delete_all_tasks()
    click.echo("All tasks cleaned successfully")


@cli.command()
@click.option(
    "--agent-collection",
    required=True,
    help="Path to agent collection configuration file"
)
@click.option(
    "--mq-type",
    type=click.Choice(["kafka", "rabbitmq"]),
    default="kafka",
    help="Message queue type (default: kafka)"
)
def consume_outputs(
        agent_collection: str,
        mq_type: str
):
    """Consume task outputs from message queue."""
    click.echo(f"Starting output consumer (MQ type: {mq_type})...")

    pipeline = AgentPipeline(
        config_path=agent_collection,
        mq_type=mq_type  # type: ignore
    )

    message_count = 0
    try:
        for output in pipeline.pull_task_outputs():
            click.echo(f"Received output:\n{output}")
            message_count += 1
    except KeyboardInterrupt:
        click.echo(f"\nConsumed {message_count} messages before interruption")
    except Exception as e:
        click.echo(f"Error consuming outputs: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()
