"""
The Celery task for running benchmarks.
"""
import asyncio
from celery import Task
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from mcpuniverse.benchmark.task import Task as BenchmarkTask
from mcpuniverse.app.core.engine import app_engine


class Benchmark(Task):
    """
    The Celery task for running benchmarks.
    """
    logger = get_logger(__name__)

    def run(self, *args, **kwargs):
        """Run benchmarks"""
        if "job_id" not in kwargs:
            raise RuntimeError("No job ID")
        if "project_id" not in kwargs:
            raise RuntimeError("No project ID")
        if "config" not in kwargs:
            raise RuntimeError("No agent configuration")
        if "agent_name" not in kwargs:
            raise RuntimeError("No main agent")
        if "tasks" not in kwargs:
            raise RuntimeError("No tasks")

        context = Context()
        tasks = [BenchmarkTask(config) for config in kwargs["tasks"]]
        if "context" in kwargs:
            Context.model_validate(kwargs["context"])
        results = asyncio.run(app_engine.run_tasks(
            job_id=kwargs["job_id"],
            project_id=kwargs["project_id"],
            config=kwargs["config"],
            agent_name=kwargs["agent_name"],
            tasks=tasks,
            context=context
        ))
        return results
