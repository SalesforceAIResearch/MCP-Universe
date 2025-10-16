"""
Agent collection launcher and configuration utilities.

Defines classes for loading agent collection configurations and launching
agent instances with specified contexts and settings.
"""
# pylint: disable=too-few-public-methods,consider-using-with,broad-exception-caught
from __future__ import annotations
import os
import json
import tempfile
import subprocess
import logging
import time
import uuid
from queue import Queue
from threading import Thread
from typing import List, Dict, Literal, Generator

import yaml
import redis
from pydantic import BaseModel, Field
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.workflows.builder import WorkflowBuilder, Executor
from mcpuniverse.mcp.manager import MCPManager, Context
from mcpuniverse.benchmark.task import TaskConfig
from mcpuniverse.pipeline.celery_config import send_task, purge_queue
from mcpuniverse.pipeline.mq.factory import MQFactory
from mcpuniverse.pipeline.utils import deserialize_task_output

logging.basicConfig(level="INFO")
logger = logging.getLogger("Agent-Pipeline")


class AgentCollectionSpec(BaseModel):
    """
    The specification for an agent collection.
    
    Defines the structure for configuring a collection of agents with
    shared settings and contexts.
    """

    # Agent collection name
    name: str
    # Agent config file path
    config: str
    # Agent contexts defining environment variables and settings
    context: List[Context] = Field(default_factory=list)
    # Number of agents to create for each context
    number: int = 1


class AgentCollectionConfig(BaseModel):
    """
    Configuration for an agent collection.
    
    Contains the collection specification and metadata.
    """
    # Configuration type identifier
    kind: Literal["collection"]
    # Agent collection specification
    spec: AgentCollectionSpec

    @staticmethod
    def load(config: str | dict | List[dict]) -> List[AgentCollectionConfig]:
        """
        Load agent collection configurations from various sources.
        
        Args:
            config: Configuration source - YAML file path, dict, or list of dicts.
            
        Returns:
            List of AgentCollectionConfig instances.
            
        Raises:
            AssertionError: If config file doesn't have .yml or .yaml extension.
        """
        if not config:
            return []
        if isinstance(config, str):
            assert config.endswith(".yml") or config.endswith(".yaml"), \
                "Config should be a YAML file"
            with open(config, "r", encoding="utf-8") as f:
                objects = yaml.safe_load_all(f)
                if isinstance(objects, dict):
                    objects = [objects]
                return [AgentCollectionConfig.model_validate(o) for o in objects]
        if isinstance(config, dict):
            config = [config]
        return [AgentCollectionConfig.model_validate(o) for o in config]


class AgentLauncher(metaclass=AutodocABCMeta):
    """
    Manages and launches agent collections.
    
    Validates configurations and creates agent instances from collection specs.
    """

    def __init__(self, config_path: str):
        """
        Initialize the launcher with configuration.
        
        Args:
            config_path: Path to the YAML configuration file.
            
        Raises:
            ValueError: If invalid kind, missing config files, or duplicate names.
        """
        self._collection_configs = AgentCollectionConfig.load(config_path)

        # Check if all the configs are "collection"
        for config in self._collection_configs:
            if config.kind != "collection":
                raise ValueError(f"Agent collection configs have invalid kind `{config.kind}`")

        # Check if agent config file exists
        folder = os.path.dirname(config_path)
        for config in self._collection_configs:
            path = config.spec.config
            if not os.path.exists(path):
                path = os.path.join(folder, path)
                if not os.path.exists(path):
                    raise ValueError(f"Missing agent config file `{config.spec.config}`")
                config.spec.config = path

        self._name_to_configs = {}
        for config in self._collection_configs:
            if config.spec.name in self._name_to_configs:
                raise ValueError(f"Found duplicated collection name `{config.spec.name}`")
            self._name_to_configs[config.spec.name] = config

    def create_agents(self, project_id: str = "agent-collection") -> Dict[str, List[Executor]]:
        """
        Create agent instances from collection configurations.
        
        Args:
            project_id: Project identifier for the agents.
            
        Returns:
            Dictionary mapping collection names to lists of agent executors.
        """
        agent_collection = {}
        for name, config in self._name_to_configs.items():
            agents = []
            for _ in range(config.spec.number):
                contexts = config.spec.context if config.spec.context else [None]
                for context in contexts:
                    mcp_manager = MCPManager(context=context)
                    builder = WorkflowBuilder(mcp_manager=mcp_manager, config=config.spec.config)
                    builder.build(project_id=project_id)
                    agent_name = builder.get_entrypoint()
                    agents.append(builder.get_component(agent_name))
            agent_collection[name] = agents
        return agent_collection


class AgentPipeline(metaclass=AutodocABCMeta):
    """
    Manages distributed task execution using Celery workers.
    
    Launches agent collections as Celery workers and distributes tasks
    across available agents using round-robin scheduling.
    """
    AGENT_TASK = "mcpuniverse.pipeline.task.AgentTask"

    def __init__(
            self,
            config_path: str,
            max_queue_size: int = 100,
            mq_type: Literal["kafka", "rabbitmq"] = "kafka"
    ):
        """
        Initialize the pipeline launcher with agent configuration.
        
        Args:
            config_path: Path to the YAML agent collection configuration file.
            max_queue_size: The maximum Celery queue size.
            mq_type: Message queue type ('kafka' or 'rabbitmq').
        """
        agent_launcher = AgentLauncher(config_path=config_path)
        self._agent_collection = agent_launcher.create_agents(project_id="pipeline")
        self._agent_collection_config = config_path
        self._agent_indices = {name: 0 for name in self._agent_collection}
        self._max_queue_size = max_queue_size
        self._redis_client = AgentPipeline._build_redis_client()
        self._mq_consumer = MQFactory.create_consumer(
            mq_type=mq_type,
            topic=os.environ.get("MQ_TOPIC", "agent-task-mq"),
            value_deserializer=deserialize_task_output
        )

    @staticmethod
    def _build_redis_client() -> redis.Redis:
        redis_host = os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(os.environ.get("REDIS_PORT", 6379))
        max_retries, retry_delay = 6, 10
        for attempt in range(max_retries):
            try:
                redis_client = redis.Redis(host=redis_host, port=redis_port, socket_timeout=30)
                redis_client.ping()
                return redis_client
            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.warning("Redis connection attempt %d failed: %s", attempt + 1, str(e))
                if attempt == max_retries - 1:
                    logger.error("Failed to connect to Redis after all retries")
                    raise RuntimeError(f"Cannot connect to Redis at {redis_host}:{redis_port}") from e
                logger.info("Retrying in %d seconds...", retry_delay)
                time.sleep(retry_delay)

    def _build_celery_script(self):
        """
        Build shell script for starting Celery workers.
        
        Returns:
            Shell script content with Celery worker startup commands.
        """
        commands = []
        for name, agents in self._agent_collection.items():
            for i in range(len(agents)):
                queue_name = f"{name}_{i}"
                agent_name = str(uuid.uuid4())
                commands.append(f"AGENT_COLLECTION_CONFIG_FILE={self._agent_collection_config} "
                                f"celery -A mcpuniverse.pipeline.worker worker -Q {queue_name} "
                                f"--loglevel=info -n {agent_name}@%h -c 1 &")
        return "\n".join(commands)

    def start_celery_workers(self):
        """
        Start Celery workers for all agent collections.
        
        Creates a shell script with worker startup commands and executes it.
        Logs output and handles subprocess errors.
        """
        folder = os.path.dirname(os.path.realpath(__file__))
        tmpdir = tempfile.gettempdir()
        script = self._build_celery_script()
        with open(os.path.join(tmpdir, "start_pipeline.sh"), "w", encoding="utf-8") as f:
            f.write(script)
        commands = ["bash", os.path.join(tmpdir, "start_pipeline.sh")]
        try:
            env = os.environ.copy()
            env["AGENT_COLLECTION_CONFIG_FILE"] = self._agent_collection_config
            _stream_logs(commands, env=env, cwd=os.path.join(folder, '../..'))
        except subprocess.CalledProcessError as e:
            logger.error(str(e))

    def _get_queue_size(self, queue_name) -> int:
        return self._redis_client.llen(queue_name)

    def send_task(self, agent_collection_name: str, task_config: TaskConfig | dict) -> bool:
        """
        Send a task to an agent using round-robin scheduling.
        
        Args:
            agent_collection_name: Name of the agent collection to send task to.
            task_config: Configuration for the task to be executed.
            
        Raises:
            RuntimeError: If agent collection name is invalid.
        """
        if agent_collection_name not in self._agent_collection:
            raise RuntimeError(f"Invalid agent collection: {agent_collection_name}")
        if isinstance(task_config, dict):
            task_config = TaskConfig.model_validate(task_config)

        agent_index = self._agent_indices[agent_collection_name]
        self._agent_indices[agent_collection_name] = (
                (agent_index + 1) % len(self._agent_collection[agent_collection_name]))
        queue_name = f"{agent_collection_name}_{agent_index}"
        if self._get_queue_size(queue_name) > self._max_queue_size:
            return False

        try:
            send_task(
                task=AgentPipeline.AGENT_TASK,
                kwargs={
                    "agent_collection_name": agent_collection_name,
                    "agent_index": agent_index,
                    "task_config": json.dumps(task_config.model_dump(mode="json"))
                },
                queue=queue_name
            )
            return True
        except Exception as e:
            logger.error(str(e))
            return False

    def delete_all_tasks(self):
        """Delete all scheduled tasks in the Celery queues."""
        for name, agents in self._agent_collection.items():
            for i in range(len(agents)):
                purge_queue(f"{name}_{i}")

    def pull_task_outputs(self) -> Generator:
        """Pull task outputs from Kafka."""
        return self._mq_consumer.consume_messages()


def _stream_logs(cmds: str | List[str], *, env=None, cwd=None):
    proc = subprocess.Popen(
        cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd
    )
    queue: Queue[tuple[str, bytes]] = Queue()
    stderr, stdout = b"", b""
    # We will use a thread to read from the subprocess and avoid hanging from Ctrl+C
    t = Thread(target=_enqueue_output, args=(proc.stdout, "stdout", queue))
    t.daemon = True
    t.start()
    t = Thread(target=_enqueue_output, args=(proc.stderr, "stderr", queue))
    t.daemon = True
    t.start()
    for _ in range(2):
        for src, line in iter(queue.get, None):
            logger.info(line.decode(errors="replace").strip("\n"))
            if src == "stderr":
                stderr += line
            else:
                stdout += line
    exit_code = proc.wait()
    if exit_code != 0:
        raise subprocess.CalledProcessError(
            exit_code, cmds, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(
        proc.args, exit_code, stdout=stdout, stderr=stderr
    )


def _enqueue_output(pipe, pipe_name, queue):
    try:
        with pipe:
            for line in iter(pipe.readline, b""):
                queue.put((pipe_name, line))
    finally:
        queue.put(None)
