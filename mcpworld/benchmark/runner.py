"""
Benchmarks for evaluating agents and LLMs
"""
# pylint: disable=broad-exception-caught,too-few-public-methods
import os
from typing import List, Dict, Optional

import yaml
from pydantic import BaseModel, Field
from mcpworld.common.misc import AutodocABCMeta
from mcpworld.llm.base import BaseLLM
from mcpworld.agent.base import Executor
from mcpworld.mcp.manager import MCPManager
from mcpworld.workflows.builder import WorkflowBuilder
from mcpworld.benchmark.task import Task
from mcpworld.tracer.collectors.base import BaseCollector
from mcpworld.tracer import Tracer
from mcpworld.evaluator import EvaluationResult
from mcpworld.common.logger import get_logger


class BenchmarkConfig(BaseModel):
    """Benchmark configuration."""
    description: str
    agent: str
    tasks: List[str] = Field(default_factory=list)


class BenchmarkResult(BaseModel):
    """Benchmark evaluation results."""
    benchmark: BenchmarkConfig
    task_results: Dict[str, List[EvaluationResult]]
    task_trace_ids: Dict[str, str]


class BenchmarkRunner(metaclass=AutodocABCMeta):
    """
    The class for running different benchmarks.
    """

    def __init__(self, config: str):
        """
        :param config: The config file path.
        """
        self._default_folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")
        if not os.path.exists(config):
            config = os.path.join(self._default_folder, config)
        if not os.path.exists(config):
            raise ValueError(f"Cannot find config file: {config}")
        self._logger = get_logger("Benchmark")

        # Load configs
        self._agent_configs = []
        self._benchmark_configs = []
        with open(config, "r", encoding="utf-8") as f:
            objects = yaml.safe_load_all(f)
            if isinstance(objects, dict):
                objects = [objects]
            for obj in objects:
                obj = dict(obj)
                assert "kind" in obj and "spec" in obj, "Wrong config format: Missing `kind`"
                if obj["kind"].lower() == "benchmark":
                    self._benchmark_configs.append(BenchmarkConfig.model_validate(obj["spec"]))
                else:
                    self._agent_configs.append(obj)

        # Load tasks
        self._tasks = []
        for benchmark in self._benchmark_configs:
            task_objects = []
            for task in benchmark.tasks:
                if not os.path.exists(task):
                    task = os.path.join(self._default_folder, task)
                task_objects.append(Task(task))
            self._tasks.append(task_objects)

    async def run(
            self,
            mcp_manager: Optional[MCPManager] = None,
            trace_collector: Optional[BaseCollector] = None,
            components: Optional[Dict[str, BaseLLM | Executor]] = None
    ) -> List[BenchmarkResult]:
        """
        Run specified benchmarks.

        :param mcp_manager: An MCP server manager.
        :param trace_collector: Trace collector.
        :param components: The components to be overwritten.
        """
        if mcp_manager is None:
            mcp_manager = MCPManager()
        workflow = WorkflowBuilder(mcp_manager=mcp_manager, config=self._agent_configs)
        workflow.build(components)
        assert len(self._benchmark_configs) == len(self._tasks)

        outputs = []
        used_agents = []
        for benchmark, task_objects in zip(self._benchmark_configs, self._tasks):
            agent: Executor = workflow.get_component(benchmark.agent)
            used_agents.append(agent)
            await agent.initialize()

            task_results = {}
            task_trace_ids = {}
            for task_name, task in zip(benchmark.tasks, task_objects):
                tracer = Tracer(collector=trace_collector)
                question = task.get_question()
                output_format = task.get_output_format()
                try:
                    response = await agent.execute(
                        question, output_format=output_format, tracer=tracer)
                    result = response.get_response_str()
                except Exception as e:
                    result = str(e)
                evaluation_results = task.evaluate(result)
                task_results[task_name] = evaluation_results
                task_trace_ids[task_name] = tracer.trace_id
            outputs.append(BenchmarkResult(
                benchmark=benchmark, task_results=task_results, task_trace_ids=task_trace_ids))

        for agent in used_agents[::-1]:
            await agent.cleanup()
        return outputs
