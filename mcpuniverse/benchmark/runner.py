"""
Benchmarks for evaluating agents and LLMs
"""
# pylint: disable=broad-exception-caught,too-few-public-methods
import json
import os
import hashlib
from typing import List, Dict, Optional, Any
from contextlib import AsyncExitStack

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import Executor, BaseAgent
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.workflows.builder import WorkflowBuilder
from mcpuniverse.benchmark.task import Task
from mcpuniverse.benchmark.bundle import (
    resolve_runner_config_file,
)
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer import Tracer
from mcpuniverse.evaluator import EvaluationResult
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from mcpuniverse.callbacks.base import (
    BaseCallback,
    CallbackMessage,
    MessageType,
    send_message_async, send_message
)


class BenchmarkConfig(BaseModel):
    """Benchmark configuration."""
    description: str = ""
    benchmark_id: str = Field(
        ...,
        description=(
            "Suite id for scoped prepare/evaluator lookup (e.g. mcpmark, mcpuniverse). "
            "Required in benchmark YAML; passed through to each Task."
        ),
    )
    agent: str = ""
    tasks: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_benchamrk_typo(cls, data: Any) -> Any:
        if isinstance(data, dict) and "benchamrk_id" in data:
            raise ValueError(
                "Invalid field 'benchamrk_id' in benchmark spec; use 'benchmark_id'."
            )
        return data

    @field_validator("benchmark_id", mode="before")
    @classmethod
    def strip_benchmark_id(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("benchmark_id")
    @classmethod
    def benchmark_id_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("benchmark_id must not be empty or whitespace-only")
        return v

    def md5(self) -> str:
        """Return the MD5 hash of the benchmark config."""
        text = (f"BenchmarkId: {self.benchmark_id}, "
                f"Description: {self.description}, "
                f"Agent: {self.agent}, "
                f"Tasks: {', '.join(self.tasks)}")
        return hashlib.md5(text.encode()).hexdigest()


class BenchmarkResult(BaseModel):
    """Benchmark evaluation results."""
    benchmark: BenchmarkConfig
    task_results: Dict[str, Dict[str, Any]]
    task_trace_ids: Dict[str, str]


class BenchmarkResultStore(metaclass=AutodocABCMeta):
    """
    The class for storing benchmark results, allowing resuming tasks.
    """

    def __init__(self, folder: str = ""):
        """
        Initialize a store of benchmark results.

        Args:
            folder (str): The folder path of the store.
                If it is empty, the results will not be stored.
        """
        self._folder = folder

    def dump_task_result(
            self,
            benchmark: BenchmarkConfig,
            task_config_path: str,
            evaluation_results: List[EvaluationResult],
            trace_id: str,
            overwrite: bool = True
    ):
        """
        Dump a task result in one benchmark.

        Args:
            benchmark (BenchmarkConfig): The benchmark configuration.
            task_config_path (str): The task config filepath.
            evaluation_results (List[EvaluationResult]): The evaluation results to save.
            trace_id (str): The tracing ID for this task (only valid when the collector is a database).
            overwrite (bool): Whether to overwrite existing evaluation results.
        """
        if not self._folder:
            return
        with open(task_config_path, "rb") as f:
            task_md5 = hashlib.md5(f.read()).hexdigest()
        folder = os.path.join(self._folder, benchmark.md5())
        os.makedirs(folder, exist_ok=True)
        filename = os.path.join(folder, f"{task_md5}.json")
        if not overwrite and os.path.isfile(filename):
            return
        result = {
            "results": [r.model_dump(mode="json") for r in evaluation_results],
            "trace_id": trace_id
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    def load_task_result(
            self,
            benchmark: BenchmarkConfig,
            task_config_path: str
    ) -> Optional[dict]:
        """
        Check if the evaluation results of a task have been stored.

        Args:
            benchmark (BenchmarkConfig): The benchmark configuration.
            task_config_path (str): The task config filepath.
        """
        if self._folder == "":
            return None
        with open(task_config_path, "rb") as f:
            task_md5 = hashlib.md5(f.read()).hexdigest()
        folder = os.path.join(self._folder, benchmark.md5())
        filename = os.path.join(folder, f"{task_md5}.json")
        if not os.path.isfile(filename):
            return None
        with open(filename, "r", encoding="utf-8") as f:
            result = json.load(f)
            result["results"] = [EvaluationResult.model_validate(r) for r in result["results"]]
            return result


class BenchmarkRunner(metaclass=AutodocABCMeta):
    """
    The class for running different benchmarks.
    """

    def __init__(self, config: str, context: Optional[Context] = None):
        """
        Initialize a benchmark runner.

        Args:
            config (str): The config file path.
            context (Context, optional): The context information.
        """
        self._logger = get_logger("Benchmark")
        self._context = context if context else Context()

        abs_config = resolve_runner_config_file(config)
        self._resolved_config_path = abs_config

        # Initialize missing attributes to avoid AttributeError
        self._bundle = None
        self._task_search_roots = []

        # Load configs
        self._agent_configs = []
        self._benchmark_configs = []
        self._loaded_bundles = set()  # Track which bundles we've loaded

        with open(abs_config, "r", encoding="utf-8") as f:
            objects = yaml.safe_load_all(f)
            if isinstance(objects, dict):
                objects = [objects]
            for obj in objects:
                obj = dict(obj)
                assert "kind" in obj and "spec" in obj, "Wrong config format: Missing `kind`"
                if obj["kind"].lower() == "benchmark":
                    benchmark_config = BenchmarkConfig.model_validate(obj["spec"])
                    self._benchmark_configs.append(benchmark_config)

                    # Load bundle package to register prepare/cleanup/evaluator functions
                    from mcpuniverse.benchmark.bundle import load_benchmark_package, suite_task_config_root
                    if benchmark_config.benchmark_id not in self._loaded_bundles:
                        self._logger.info("Loading benchmark bundle: %s", benchmark_config.benchmark_id)
                        load_benchmark_package(benchmark_config.benchmark_id)
                        self._loaded_bundles.add(benchmark_config.benchmark_id)

                    # Build task search roots based on benchmark_id
                    task_root = suite_task_config_root(benchmark_config.benchmark_id)
                    if task_root and task_root not in self._task_search_roots:
                        self._task_search_roots.append(task_root)
                else:
                    self._agent_configs.append(obj)

        # store the outputs
        self._benchmark_results = None

    def _resolve_task_filepath(self, task_path: str, benchmark_id: str) -> str:
        """
        Resolve a task path to an existing file.

        Accepts an absolute path, a cwd-relative path to an existing file, or a path
        under ``mcpuniverse/benchmark/<benchmark_id>/task_configs/`` when that
        directory exists.
        """
        if os.path.isabs(task_path) and os.path.isfile(task_path):
            return os.path.abspath(task_path)
        if os.path.isfile(task_path):
            return os.path.abspath(task_path)
        for root in self._task_search_roots:
            candidate = os.path.join(root, task_path)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        hint = (
            f"benchmark_id={benchmark_id!r}: use an absolute path, a path relative to the "
            f"current working directory that exists, or a file under "
            f"benchmark/{benchmark_id}/task_configs/."
        )
        if root:
            raise FileNotFoundError(
                f"Task config not found: {task_path!r} (looked under {root!r}). {hint}"
            )
        raise FileNotFoundError(
            f"Task config not found: {task_path!r} "
            f"(no task_configs directory for this benchmark_id). {hint}"
        )

    async def _execute_benchmark(
            self,
            benchmark: BenchmarkConfig,
            agent: Executor,
            *,
            mcp_manager: MCPManager,
            store: BenchmarkResultStore,
            trace_collector: Optional[BaseCollector],
            overwrite: bool,
            callbacks: Optional[List[BaseCallback]],
    ) -> BenchmarkResult:
        """Run all tasks for one benchmark block (agent already initialized)."""
        await send_message_async(callbacks, message=CallbackMessage(
            source=__file__,
            type=MessageType.LOG,
            metadata={"event": "list_tools", "data": agent}
        ))

        task_results, task_trace_ids = {}, {}
        for idx, task_path in enumerate(benchmark.tasks):
            async with AsyncExitStack():
                send_message(callbacks, message=CallbackMessage(
                    source="benchmark_runner",
                    type=MessageType.PROGRESS,
                    data=f"Running task: {task_path} ({idx + 1}/{len(benchmark.tasks)})"
                ))
                send_message(callbacks, message=CallbackMessage(
                    source="benchmark_runner",
                    type=MessageType.LOG,
                    data=f"Running task: {task_path}"
                ))
                self._logger.info("Running task: %s", task_path)
                task_filepath = self._resolve_task_filepath(task_path, benchmark.benchmark_id)

                stored_result = store.load_task_result(
                    benchmark=benchmark, task_config_path=task_filepath)
                if not overwrite and stored_result is not None:
                    task_results[task_path] = {"evaluation_results": stored_result["results"]}
                    task_trace_ids[task_path] = stored_result["trace_id"]
                    self._logger.info("Loaded stored results for task: %s", task_path)
                    continue

                task = Task(
                    task_filepath,
                    context=self._context,
                    mcp_manager=mcp_manager,
                    benchmark_id=benchmark.benchmark_id,
                )

                filesystem_test_dir = os.environ.get("FILESYSTEM_TEST_DIR", "NOT SET")
                self._logger.info("FILESYSTEM_TEST_DIR before prepare: %s", filesystem_test_dir)

                try:
                    self._logger.info("Preparing task environment for: %s", task_path)
                    await task.prepare()
                except Exception as e:
                    self._logger.error("Failed to prepare task environment: %s", str(e))

                if task.use_specified_server() and isinstance(agent, BaseAgent):
                    await agent.change_servers(task.get_mcp_servers())
                agent.reset()
                tracer = Tracer(collector=trace_collector)
                question = task.get_question()
                output_format = task.get_output_format()

                await send_message_async(callbacks, message=CallbackMessage(
                    source=__file__,
                    type=MessageType.LOG,
                    metadata={"event": "task_description", "data": task}
                ))
                try:
                    response = await agent.execute(
                        question,
                        output_format=output_format,
                        tracer=tracer,
                        callbacks=callbacks
                    )
                    result = response.get_response_str()
                except Exception as e:
                    result = str(e)
                evaluation_results = await task.evaluate(result)

                task_results[task_path] = {
                    "evaluation_results": evaluation_results
                }
                task_trace_ids[task_path] = tracer.trace_id
                trace_records = trace_collector.get(tracer.trace_id) if trace_collector else None
                store.dump_task_result(
                    benchmark=benchmark,
                    task_config_path=task_filepath,
                    evaluation_results=evaluation_results,
                    trace_id=tracer.trace_id,
                    overwrite=True
                )

                self._logger.info("Resetting task %s", task_path)
                await task.reset(trace_records or [])
                await task.cleanup()
                self._logger.info("Finished resetting task %s", task_path)
                if task.use_specified_server() and isinstance(agent, BaseAgent):
                    await agent.cleanup()

        self._logger.info("Finished benchmark: %s", benchmark.description)
        return BenchmarkResult(
            benchmark=benchmark, task_results=task_results, task_trace_ids=task_trace_ids)

    async def run(
            self,
            mcp_manager: Optional[MCPManager] = None,
            trace_collector: Optional[BaseCollector] = None,
            components: Optional[Dict[str, BaseLLM | Executor]] = None,
            store_folder: str = "",
            overwrite: bool = True,
            callbacks: Optional[List[BaseCallback]] = None
    ) -> List[BenchmarkResult]:
        """
        Run specified benchmarks.

        Args:
            mcp_manager (MCPManager): An MCP server manager.
            trace_collector (BaseCollector): Trace collector.
            components (Dict): The components to be overwritten.
            store_folder (str): The folder path for storing evaluation results.
            overwrite (bool): Whether to overwrite existing evaluation results.
            callbacks (List[BaseCallback], optional): Callback functions.
        """
        if mcp_manager is None:
            if self._bundle and self._bundle.has_server_list:
                mcp_manager = MCPManager(config=self._bundle.server_list_path, context=self._context)
            else:
                mcp_manager = MCPManager(context=self._context)
        workflow = WorkflowBuilder(mcp_manager=mcp_manager, config=self._agent_configs)
        workflow.build(components)
        store = BenchmarkResultStore(folder=store_folder)

        outputs = []
        used_agents = []
        for benchmark in self._benchmark_configs:
            agent: Executor = workflow.get_component(benchmark.agent)
            used_agents.append(agent)
            await agent.initialize()
            await send_message_async(callbacks, message=CallbackMessage(
                source=__file__,
                type=MessageType.LOG,
                metadata={"event": "list_tools", "data": agent}
            ))

            task_results, task_trace_ids = {}, {}
            for idx, task_path in enumerate(benchmark.tasks):
                async with AsyncExitStack():
                    send_message(callbacks, message=CallbackMessage(
                        source="benchmark_runner",
                        type=MessageType.PROGRESS,
                        data=f"Running task: {task_path} ({idx + 1}/{len(benchmark.tasks)})"
                    ))
                    send_message(callbacks, message=CallbackMessage(
                        source="benchmark_runner",
                        type=MessageType.LOG,
                        data=f"Running task: {task_path}"
                    ))
                    self._logger.info("Running task: %s", task_path)
                    task_filepath = self._resolve_task_filepath(task_path, benchmark.benchmark_id)
                    if not os.path.isfile(task_filepath):
                        raise FileNotFoundError(f"Task config not found: {task_path} (resolved: {task_filepath})")

                    stored_result = store.load_task_result(
                        benchmark=benchmark, task_config_path=task_filepath)
                    if not overwrite and stored_result is not None:
                        task_results[task_path] = stored_result["results"]
                        task_trace_ids[task_path] = stored_result["trace_id"]
                        self._logger.info("Loaded stored results for task: %s", task_path)
                        continue

                    # Execute the task and the corresponding evaluations
                    task = Task(
                        task_filepath,
                        context=self._context,
                        mcp_manager=mcp_manager,
                        benchmark_id=benchmark.benchmark_id,
                    )

                    # Log FILESYSTEM_TEST_DIR before prepare (after previous task cleanup)
                    filesystem_test_dir = os.environ.get("FILESYSTEM_TEST_DIR", "NOT SET")
                    self._logger.info("FILESYSTEM_TEST_DIR before prepare: %s", filesystem_test_dir)

                    # Prepare task environment before agent execution
                    try:
                        self._logger.info("Preparing task environment for: %s", task_path)
                        await task.prepare()
                    except Exception as e:
                        self._logger.error("Failed to prepare task environment: %s", str(e))
                        # Continue execution even if prepare fails (for backward compatibility)

                    if task.use_specified_server() and isinstance(agent, BaseAgent):
                        await agent.change_servers(task.get_mcp_servers())
                    agent.reset()
                    tracer = Tracer(collector=trace_collector)
                    question = task.get_question()
                    output_format = task.get_output_format()

                    await send_message_async(callbacks, message=CallbackMessage(
                        source=__file__,
                        type=MessageType.LOG,
                        metadata={"event": "task_description", "data": task}
                    ))
                    try:
                        response = await agent.execute(
                            question,
                            output_format=output_format,
                            tracer=tracer,
                            callbacks=callbacks
                        )
                        result = response.get_response_str()
                    except Exception as e:
                        result = str(e)
                    evaluation_results = await task.evaluate(result)

                    # Save the evaluation results
                    task_results[task_path] = {
                        "evaluation_results": evaluation_results
                    }
                    task_trace_ids[task_path] = tracer.trace_id
                    trace_records = trace_collector.get(tracer.trace_id)
                    store.dump_task_result(
                        benchmark=benchmark,
                        task_config_path=task_filepath,
                        evaluation_results=evaluation_results,
                        trace_id=tracer.trace_id,
                        overwrite=True
                    )

                    # Reset task status/environment
                    self._logger.info("Resetting task %s", task_path)
                    await task.reset(trace_records)
                    await task.cleanup()
                    self._logger.info("Finished resetting task %s", task_path)
                    if task.use_specified_server() and isinstance(agent, BaseAgent):
                        await agent.cleanup()

            outputs.append(BenchmarkResult(
                benchmark=benchmark, task_results=task_results, task_trace_ids=task_trace_ids))
            self._logger.info("Finished benchmark: %s", benchmark.description)

        for agent in used_agents[::-1]:
            await agent.cleanup()
        self._logger.info("Agent cleanup succeeded")

        self._benchmark_results = outputs
        return outputs
