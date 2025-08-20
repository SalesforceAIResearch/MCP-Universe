"""
The engine for executing agents/workflows.
"""
# pylint: disable=broad-exception-caught,unused-argument
import os
import json
import datetime
from typing import Optional, Literal, List, Dict
from contextlib import AsyncExitStack

import yaml
from dotenv import load_dotenv
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.workflows.builder import WorkflowBuilder
from mcpuniverse.common.context import Context
from mcpuniverse.callbacks.base import MessageType, CallbackMessage
from mcpuniverse.callbacks.handlers.redis import RedisHandler
from mcpuniverse.benchmark.task import Task
from mcpuniverse.tracer.tracer import Tracer
from mcpuniverse.tracer.collectors.memory import MemoryCollector
from mcpuniverse.evaluator.evaluator import EvaluationResult
from mcpuniverse.app.db.database import sessionmanager
from mcpuniverse.app.db.sqlc.benchmark_job import AsyncQuerier, UpdateBenchmarkJobParams

load_dotenv()


class AppEngine:
    """
    The engine for executing agents/workflows.
    """

    def __init__(self):
        self.callback = RedisHandler(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ["REDIS_PORT"]),
            expiration_time=3600
        )

    @staticmethod
    def _build_workflow(project_id: str, config: str | dict, context: Optional[Context] = None) -> WorkflowBuilder:
        """Build agents/workflows given the configuration."""
        mcp_manager = MCPManager(context=context)
        if isinstance(config, str):
            config = yaml.safe_load_all(config)
        workflow = WorkflowBuilder(mcp_manager=mcp_manager, config=config)
        workflow.build(project_id=project_id)
        workflow.set_context(context)
        undefined_vars = workflow.list_undefined_env_vars()
        if undefined_vars:
            raise RuntimeError(f"Environment variables are undefined: {undefined_vars}")
        return workflow

    @staticmethod
    def check_config(config: str | dict, context: Optional[Context] = None) -> (bool, str):
        """
        Check if an agent configuration is valid.

        Args:
            config (str | dict): The agent configuration, i.e., a JSON string or a dict.
            context (Context, optional): The context information, e.g., environment variables.
        """
        try:
            workflow = AppEngine._build_workflow(project_id="tmp", config=config, context=context)
            agent_name = workflow.get_entrypoint()
            if not agent_name:
                raise ValueError("No main agent")
        except Exception as e:
            return False, str(e)
        return True, ""

    async def run(
            self,
            project_id: str,
            config: str | dict | List[dict],
            agent_name: str,
            question: str,
            context: Optional[Context] = None
    ) -> str:
        """
        Run the agent given a certain question.

        Args:
            project_id (str): The project ID.
            agent_name (str): The name of the chosen agent to answer the question.
            config (str | dict | List[dict]): The agent configuration, i.e., a JSON string or a dict.
            question (str): The question to answer.
            context (Context, optional): The context information, e.g., environment variables.

        Returns:
            str: The agent response.
        """
        agent = None
        context = context if context else Context()
        async with AsyncExitStack():
            try:
                workflow = AppEngine._build_workflow(
                    project_id=project_id, config=config, context=context)
                if not agent_name:
                    agent_name = workflow.get_entrypoint()
                agent = workflow.get_component(agent_name)
                await agent.initialize()
                response = await agent.execute(question, callbacks=self.callback)
                result = response.get_response_str()
            except Exception as e:
                result = str(e)
            finally:
                if agent:
                    await agent.cleanup()
            return result

    def get_message(
            self,
            project_id: str,
            component_type: Literal["llm", "agent", "workflow", "mcp"],
            component_name: str,
            message_type: str | MessageType
    ) -> Optional[CallbackMessage]:
        """
        Get callback messages.

        Args:
            project_id (str): The project ID.
            component_type (str): The component type, i.e., llm, agent, workflow, mcp.
            component_name (str): The component name defined in the configuration.
            message_type (str | MessageType): The message type.
        """
        if isinstance(message_type, str):
            message_type = MessageType(message_type)
        if component_type == "mcp":
            component_name += "_client"
        source_id = f"{project_id}:{component_type}:{component_name}"
        return self.callback.get(source=source_id, message_type=message_type)

    @staticmethod
    async def run_tasks(
            job_id: str,
            project_id: str,
            config: str | dict | List[dict],
            agent_name: str,
            tasks: List[Task],
            context: Optional[Context] = None
    ) -> Optional[Dict]:
        """
        Run a set of tasks given the agent.

        Args:
            job_id (str): The job ID.
            project_id (str): The project ID.
            agent_name (str): The name of the chosen agent to answer the question.
            config (str | dict | List[dict]): The agent configuration, i.e., a JSON string or a dict.
            tasks (List[Task]): A set of tasks to execute.
            context (Context, optional): The context information, e.g., environment variables.
        """
        context = context if context else Context()
        results, response = {}, None
        try:
            await AppEngine.update_job_status(job_id=job_id, status="started")
            async with AsyncExitStack():
                # Initialize the agent
                workflow = AppEngine._build_workflow(
                    project_id=project_id, config=config, context=context)
                if not agent_name:
                    agent_name = workflow.get_entrypoint()
                agent = workflow.get_component(agent_name)
                await agent.initialize()

                # Execute tasks
                total, succeeded, failed = len(tasks), 0, 0
                for i, task in enumerate(tasks):
                    async with AsyncExitStack():
                        agent.reset()
                        trace_collector = MemoryCollector()
                        tracer = Tracer(collector=trace_collector)
                        question = task.get_question()
                        output_format = task.get_output_format()
                        try:
                            response = await agent.execute(
                                question, output_format=output_format, tracer=tracer)
                            result = response.get_response_str()
                            succeeded += 1
                        except Exception as e:
                            result = str(e)
                            failed += 1
                        evaluation_results = await task.evaluate(result)
                        trace_records = trace_collector.get(tracer.trace_id)
                        results[i] = {
                            "evaluation": evaluation_results,
                            "score": AppEngine.calculate_evaluation_score(evaluation_results)
                        }
                        await task.reset(trace_records)
                        await task.cleanup()
                    await AppEngine.update_job_progress(job_id=job_id, progress=int((i + 1) / total * 100))
                await agent.cleanup()

            response = await AppEngine.update_job_results(job_id=job_id, results=results)
            await AppEngine.update_job_status(job_id=job_id, status="success")
        except Exception as e:
            await AppEngine.update_job_status(job_id=job_id, status="failure")
            raise e
        return response

    @staticmethod
    def calculate_evaluation_score(evaluation_results: List[EvaluationResult]) -> float:
        """Calculate task evaluation score."""
        num_passes = len([r for r in evaluation_results if r.passed])
        return num_passes / len(evaluation_results)

    @staticmethod
    async def update_job_status(job_id: str, status: str):
        """Update job status"""
        if job_id == "":
            return
        async with sessionmanager.engine.begin() as conn:
            querier = AsyncQuerier(conn)
            job = await querier.update_benchmark_job(UpdateBenchmarkJobParams(
                job_id=job_id, status=status, progress=None,
                results=None, score=None, celery_id=None,
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
            if not job:
                raise RuntimeError("Failed to update job status")

    @staticmethod
    async def update_job_progress(job_id: str, progress: int):
        """Update job progress"""
        if job_id == "":
            return
        async with sessionmanager.engine.begin() as conn:
            querier = AsyncQuerier(conn)
            job = await querier.update_benchmark_job(UpdateBenchmarkJobParams(
                job_id=job_id, status=None, progress=progress,
                results=None, score=None, celery_id=None,
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
            if not job:
                raise RuntimeError("Failed to update job progress")

    @staticmethod
    async def update_job_results(job_id: str, results: Dict):
        """Update job results"""
        if job_id == "":
            return
        keys = sorted(results.keys())
        task_results = []
        average_score = 0
        for key in keys:
            task_results.append([e.passed for e in results[key]["evaluation"]])
            average_score += float(results[key]["score"])
        res = json.dumps(task_results)
        average_score /= len(keys)

        async with sessionmanager.engine.begin() as conn:
            querier = AsyncQuerier(conn)
            job = await querier.update_benchmark_job(UpdateBenchmarkJobParams(
                job_id=job_id, status=None, progress=None,
                results=res, score=average_score, celery_id=None,
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
            if not job:
                raise RuntimeError("Failed to update job results")
        return {"results": task_results, "score": average_score}


app_engine = AppEngine()
