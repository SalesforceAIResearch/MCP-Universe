"""
Pipeline task module for executing agent tasks in Celery workers.

This module provides Celery task implementations for running agent-based
tasks asynchronously in a distributed pipeline environment.
"""
# pylint: disable=broad-exception-caught
import asyncio
import json
import os
from contextlib import AsyncExitStack
from dotenv import load_dotenv
from pydantic import BaseModel
from celery import Task as CeleryTask
from mcpuniverse.common.logger import get_logger
from mcpuniverse.benchmark.task import TaskConfig, Task
from mcpuniverse.pipeline.launcher import AgentLauncher
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import MemoryCollector
from mcpuniverse.pipeline.mq.producer import Producer
from mcpuniverse.pipeline.utils import serialize_task_output

load_dotenv()


class TaskInput(BaseModel):
    """
    Input data for agent task execution.
    
    Args:
        agent_collection_name: Name of the agent collection to use.
        agent_index: Index of the specific agent within the collection.
        task_config: Configuration for the task to be executed.
    """
    agent_collection_name: str
    agent_index: int
    task_config: TaskConfig


class AgentTask(CeleryTask):
    """
    Celery task for executing agent tasks asynchronously.
    """

    def __init__(self, agent_collection_config: str):
        """
        Initialize the agent task with an agent collection.
        
        Args:
            agent_collection_config: Path to the agent collection configuration file.
        """
        self._logger = get_logger(self.__class__.__name__)
        launcher = AgentLauncher(config_path=agent_collection_config)
        self._agent_collection = launcher.create_agents(project_id="celery")

    def run(self, *args, **kwargs):
        """
        Execute the Celery task.
        
        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments containing task input data.
        """
        if "agent_collection_name" not in kwargs:
            raise RuntimeError("No agent collection name")
        if "agent_index" not in kwargs:
            raise RuntimeError("No agent index")
        if "task_config" not in kwargs:
            raise RuntimeError("No task configuration")

        kwargs["agent_index"] = int(kwargs["agent_index"])
        if isinstance(kwargs["task_config"], str):
            kwargs["task_config"] = json.loads(kwargs["task_config"])
        try:
            task_input = TaskInput.model_validate(kwargs)
            task_output = asyncio.run(self._run_task(task_input))
            mq = Producer(
                host=os.environ.get("KAFKA_HOST", "localhost"),
                port=int(os.environ.get("KAFKA_PORT", 9092)),
                topic=os.environ.get("KAFKA_TOPIC", "agent-task-mq"),
                value_serializer=serialize_task_output
            )
            if not mq.send(task_output):
                self._logger.error("Failed to send task output for %s", str(kwargs))
        except Exception as e:
            self._logger.error("Failed to process task: %s", str(e))

    async def _run_task(self, task_input: TaskInput):
        """
        Execute a task using the specified agent.
        
        Args:
            task_input: Input parameters for task execution.
            
        Returns:
            Dict containing execution result, evaluation results, and trace records,
            or None if task cannot be executed.
        """
        if task_input.agent_collection_name not in self._agent_collection:
            return None
        if task_input.agent_index > len(self._agent_collection[task_input.agent_collection_name]):
            return None

        trace_collector = MemoryCollector()
        agent = self._agent_collection[task_input.agent_collection_name][task_input.agent_index]

        async with AsyncExitStack():
            await agent.initialize()
            try:
                task = Task(config=task_input.task_config.model_dump())
                question = task.get_question()
                output_format = task.get_output_format()
            except Exception as e:
                self._logger.error("Failed to create task: %s", str(e))
                return None

            try:
                if task.use_specified_server() and isinstance(agent, BaseAgent):
                    await agent.change_servers(task.get_mcp_servers())
                agent.reset()
                tracer = Tracer(collector=trace_collector)
                response = await agent.execute(
                    question,
                    output_format=output_format,
                    tracer=tracer
                )
                result = response.get_response_str()
            except Exception as e:
                result = str(e)

            evaluation_results = await task.evaluate(result)
            trace_records = trace_collector.get(tracer.trace_id)

            # Reset task status/environment
            await task.reset(trace_records)
            await task.cleanup()
            if task.use_specified_server() and isinstance(agent, BaseAgent):
                await agent.cleanup()
            await agent.cleanup()

            return {
                "result": result,
                "evaluation_results": evaluation_results,
                "trace": trace_records
            }
