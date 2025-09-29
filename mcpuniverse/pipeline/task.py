"""
Pipeline task module for executing agent tasks in Celery workers.

This module provides Celery task implementations for running agent-based
tasks asynchronously in a distributed pipeline environment.
"""
# pylint: disable=broad-exception-caught
import asyncio
from contextlib import AsyncExitStack
from pydantic import BaseModel
from celery import Task as CeleryTask
from mcpuniverse.common.logger import get_logger
from mcpuniverse.benchmark.task import TaskConfig, Task
from mcpuniverse.pipeline.launcher import AgentLauncher
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import MemoryCollector


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
        self._logger = get_logger(__name__)
        launcher = AgentLauncher(config_path=agent_collection_config)
        self._agent_collection = launcher.create_agents(project_id="celery")

        # Initialize all agents asynchronously
        self._running_agents = []
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

    def __del__(self):
        """Destructor to clean up agents and event loop."""
        try:
            if self._loop and not self._loop.is_closed():
                self._loop.run_until_complete(self._cleanup_agents())
                self._loop.close()
        except Exception as e:
            self._logger.error("Error during cleanup: %s", str(e))

    async def _cleanup_agents(self):
        """Clean up all agents in the collection."""
        for agent in self._running_agents[::-1]:
            await agent.cleanup()

    def run(self, *args, **kwargs):
        """
        Execute the Celery task.
        
        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments containing task input data.
        """
        task_input = TaskInput.model_validate(kwargs)
        self._loop.run_until_complete(self._run_task(task_input))

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
        self._running_agents.append(agent)
        await agent.initialize()

        async with AsyncExitStack():
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

            return {
                "result": result,
                "evaluation_results": evaluation_results,
                "trace": trace_records
            }
