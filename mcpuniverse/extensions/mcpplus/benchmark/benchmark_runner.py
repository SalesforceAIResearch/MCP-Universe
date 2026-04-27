"""
Extended Benchmark Runner with Wrapper Support

EXISTING (MCPUniverse BenchmarkRunner):
- Loads benchmark YAML configs and runs tasks against agents
- Creates standard MCPManager for MCP protocol
- Uses WorkflowBuilder to instantiate agents from configs

THIS IMPLEMENTATION:
- Extends to use WorkflowBuilderWithWrapper instead of WorkflowBuilder
- Automatically detects wrapper configs and builds MCPWrapperManager
- Maintains full compatibility with existing benchmark configs
- Adds wrapper support without breaking existing benchmarks
"""
# pylint: disable=broad-exception-caught,too-few-public-methods
import os
from typing import List, Dict, Optional, Any
from contextlib import AsyncExitStack

from mcpuniverse.benchmark.runner import (
    BenchmarkRunner as BaseBenchmarkRunner,
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkResultStore
)
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import Executor, BaseAgent
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.benchmark.task import Task
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer import Tracer
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.context import Context
from mcpuniverse.callbacks.base import (
    BaseCallback,
    CallbackMessage,
    MessageType,
    send_message_async,
    send_message
)

from mcpuniverse.extensions.mcpplus.benchmark.builder import WorkflowBuilderWithWrapper


class BenchmarkRunnerWithWrapper(BaseBenchmarkRunner):
    """
    Extended BenchmarkRunner that supports wrapper configurations.

    This class extends MCPUniverse's BenchmarkRunner to use WorkflowBuilderWithWrapper,
    enabling post-processing agent functionality through wrapper configs.
    """

    def __init__(self, config: str, context: Optional[Context] = None):
        """
        Initialize a benchmark runner with wrapper support.

        Args:
            config (str): The config file path.
            context (Context, optional): The context information.
        """
        # Call parent __init__ to initialize basic attributes
        super().__init__(config, context)
        # Note: parent already sets self._agent_configs, self._benchmark_configs, etc.

        # Generate run identifiers for coordinated logging
        from datetime import datetime
        import uuid
        self._run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._run_id = str(uuid.uuid4())[:8]
        self._failure_log_filename = None  # Will be set after first task provides metadata

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
        Run specified benchmarks with wrapper support.

        Args:
            mcp_manager (MCPManager): An MCP server manager (can be MCPWrapperManager).
            trace_collector (BaseCollector): Trace collector.
            components (Dict): The components to be overwritten.
            store_folder (str): The folder path for storing evaluation results.
            overwrite (bool): Whether to overwrite existing evaluation results.
            callbacks (List[BaseCallback], optional): Callback functions.

        Returns:
            List[BenchmarkResult]: Results from all benchmarks.
        """
        # Use WorkflowBuilderWithWrapper instead of standard WorkflowBuilder
        # This automatically detects wrapper configs and builds MCPWrapperManager if needed
        workflow = WorkflowBuilderWithWrapper(
            mcp_manager=mcp_manager,
            config=self._agent_configs,
            context=self._context
        )
        workflow.build(components)

        # Set trace collector on manager for post-processor tracing
        if trace_collector and hasattr(workflow._mcp_manager, '__dict__'):
            workflow._mcp_manager._trace_collector = trace_collector
            self._logger.debug("Set trace collector on MCP manager for post-processor tracing")

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
                        benchmark_id=benchmark.benchmark_id,
                    )
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
                    # Reset post-processor tracer before each task (ensures separate trace per task)
                    if hasattr(workflow._mcp_manager, 'reset_postprocessor_tracer'):
                        workflow._mcp_manager.reset_postprocessor_tracer()

                    # Set current task path for failure logging
                    if hasattr(workflow._mcp_manager, 'set_current_task_path'):
                        workflow._mcp_manager.set_current_task_path(task_path)

                    try:
                        response = await agent.execute(
                            question,
                            output_format=output_format,
                            tracer=tracer,
                            callbacks=callbacks,
                            task_path=task_path  # Pass task_path for failure logging
                        )
                        result = response.get_response_str()
                    except Exception as e:
                        result = str(e)

                    evaluation_results = await task.evaluate(result)

                    # Get post-processor trace ID if available
                    postprocessor_trace_id = None
                    if hasattr(workflow._mcp_manager, 'get_postprocessor_trace_id'):
                        postprocessor_trace_id = workflow._mcp_manager.get_postprocessor_trace_id()
                        self._logger.info(
                            "Post-processor trace_id for task %s: %s",
                            task_path, postprocessor_trace_id
                        )
                    else:
                        self._logger.warning("Manager does not have get_postprocessor_trace_id method")

                    # Analyze trace to extract metrics (using tracer instead of callbacks)
                    from mcpuniverse.extensions.mcpplus.utils.tracer_analyzer import TracerAnalyzer
                    analyzer = TracerAnalyzer(
                        trace_collector=trace_collector,
                        agent_configs=self._agent_configs
                    )
                    trace_metrics = analyzer.analyze_task(
                        tracer.trace_id,
                        postprocessor_trace_id=postprocessor_trace_id
                    )

                    # Extract agent type and postprocessor type from configs
                    main_agent_type = "unknown"
                    postprocessor_type = None
                    for config in self._agent_configs:
                        if config.get('kind') == 'agent':
                            main_agent_type = config.get('spec', {}).get('type', 'unknown')
                        elif config.get('kind') == 'wrapper':
                            if config.get('spec', {}).get('enabled', False):
                                postprocessor_type = "dual"

                    # Convert to statistics dict with separate input/output costs
                    postprocessor_stats = {
                        # Main agent
                        "main_agent_name": trace_metrics.main_agent.agent_name,
                        "main_agent_type": main_agent_type,
                        "main_agent_llm_name": trace_metrics.main_agent.llm_name,
                        "main_agent_model_name": trace_metrics.main_agent.model_name,
                        "main_agent_iterations": trace_metrics.main_agent.iterations,
                        "main_agent_input_tokens": trace_metrics.main_agent.input_tokens,
                        "main_agent_output_tokens": trace_metrics.main_agent.output_tokens,
                        "main_agent_total_tokens": trace_metrics.main_agent.total_tokens,
                        "main_agent_input_cost": trace_metrics.main_agent.input_cost,
                        "main_agent_output_cost": trace_metrics.main_agent.output_cost,
                        "main_agent_total_cost": trace_metrics.main_agent.total_cost,

                        # Postprocessor (if exists)
                        "postprocessor_name": trace_metrics.postprocessor.agent_name if trace_metrics.postprocessor else None,
                        "postprocessor_type": postprocessor_type,
                        "postprocessor_llm_name": trace_metrics.postprocessor.llm_name if trace_metrics.postprocessor else None,
                        "postprocessor_model_name": trace_metrics.postprocessor.model_name if trace_metrics.postprocessor else None,
                        "postprocessor_iterations": trace_metrics.postprocessor.iterations if trace_metrics.postprocessor else 0,
                        "postprocessor_input_tokens": trace_metrics.postprocessor.input_tokens if trace_metrics.postprocessor else 0,
                        "postprocessor_output_tokens": trace_metrics.postprocessor.output_tokens if trace_metrics.postprocessor else 0,
                        "postprocessor_total_tokens": trace_metrics.postprocessor.total_tokens if trace_metrics.postprocessor else 0,
                        "postprocessor_input_cost": trace_metrics.postprocessor.input_cost if trace_metrics.postprocessor else 0.0,
                        "postprocessor_output_cost": trace_metrics.postprocessor.output_cost if trace_metrics.postprocessor else 0.0,
                        "postprocessor_total_cost": trace_metrics.postprocessor.total_cost if trace_metrics.postprocessor else 0.0,

                        # Totals
                        "total_iterations": trace_metrics.main_agent.iterations + (trace_metrics.postprocessor.iterations if trace_metrics.postprocessor else 0),
                        "total_input_tokens": trace_metrics.total_input_tokens,
                        "total_output_tokens": trace_metrics.total_output_tokens,
                        "total_tokens": trace_metrics.total_tokens,
                        "total_input_cost": trace_metrics.total_input_cost,
                        "total_output_cost": trace_metrics.total_output_cost,
                        "total_cost": trace_metrics.total_cost,
                    }

                    self._logger.info("Trace analysis complete: main_iterations=%d, pp_iterations=%d, total_cost=$%.4f",
                                     trace_metrics.main_agent.iterations,
                                     trace_metrics.postprocessor.iterations if trace_metrics.postprocessor else 0,
                                     trace_metrics.total_cost)

                    # Save the evaluation results with statistics
                    # EXISTING: MCPUniverse uses "evaluation_results" key (not serialized)
                    # THIS IMPLEMENTATION: Add statistics to task results
                    task_results[task_path] = {
                        "evaluation_results": evaluation_results,
                        "statistics": postprocessor_stats
                    }
                    task_trace_ids[task_path] = tracer.trace_id
                    store.dump_task_result(
                        benchmark=benchmark,
                        task_config_path=task_filepath,
                        evaluation_results=evaluation_results,
                        trace_id=tracer.trace_id,
                        overwrite=overwrite
                    )

                    await send_message_async(callbacks, message=CallbackMessage(
                        source=__file__,
                        type=MessageType.LOG,
                        metadata={"event": "task_result", "data": {
                            "task": task_path,
                            "results": evaluation_results
                        }}
                    ))

            outputs.append(BenchmarkResult(
                benchmark=benchmark,
                task_results=task_results,
                task_trace_ids=task_trace_ids
            ))

        # Cleanup
        for agent in used_agents:
            await agent.cleanup()

        self._benchmark_results = outputs
        return outputs
