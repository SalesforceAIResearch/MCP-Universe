"""
The config manager for the demo dashboard.
"""
# pylint: disable=broad-exception-caught
import os
import json
import asyncio
import threading
import hashlib
from typing import Optional, Dict, Any, List
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.workflows.builder import WorkflowBuilder
from mcpuniverse.common.context import Context
from mcpuniverse.callbacks.handlers.memory import MemoryHandler
from mcpuniverse.tracer.collectors import MemoryCollector
from mcpuniverse.tracer import Tracer
from mcpuniverse.benchmark.runner import BenchmarkConfig, BenchmarkRunner
from mcpuniverse.callbacks.base import CallbackMessage, MessageType, BaseCallback

load_dotenv()


@dataclass
class ChatState:
    """Chat running state."""
    agent_name: str = ""
    agent_config: str = ""
    workflow: WorkflowBuilder = None
    trace_id: str = ""


@dataclass
class BenchmarkState(BaseCallback):
    """Benchmark running state."""
    output_folder: str = ""
    benchmark_name: str = ""
    task_name: str = ""
    agent_name: str = ""
    benchmark_thread: threading.Thread = None
    benchmark_results: Dict = field(default_factory=dict)
    benchmark_status: str = ""
    benchmark_logs: List[str] = field(default_factory=list)

    def md5(self) -> str:
        """Return the MD5 hash of the benchmark state."""
        key = (f"benchmark name: {self.benchmark_name}, "
               f"task name: {self.task_name}, "
               f"agent name: {self.agent_name}")
        return hashlib.md5(key.encode()).hexdigest()

    def dump(self):
        """Dump benchmark state."""
        filepath = os.path.join(self.output_folder, f"state-{self.md5()}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "benchmark_name": self.benchmark_name,
                "task_name": self.task_name,
                "agent_name": self.agent_name,
                "benchmark_status": self.benchmark_status,
                "benchmark_results": self.benchmark_results,
                "benchmark_logs": self.benchmark_logs
            }
            f.write(json.dumps(data))

    @staticmethod
    def load(output_folder: str, benchmark_name: str, task_name: str, agent_name: str):
        """Load benchmark state."""
        state = BenchmarkState(
            output_folder=output_folder,
            benchmark_name=benchmark_name,
            task_name=task_name,
            agent_name=agent_name
        )
        filepath = os.path.join(output_folder, f"state-{state.md5()}.json")
        if os.path.isfile(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                state.benchmark_name = data["benchmark_name"]
                state.benchmark_status = data["benchmark_status"]
                state.benchmark_results = data["benchmark_results"]
                if "benchmark_logs" in data:
                    state.benchmark_logs = data["benchmark_logs"]
        return state

    def call(self, message: CallbackMessage, **kwargs):
        """Process the input message."""
        if message.type == MessageType.PROGRESS:
            self.benchmark_status = message.data
        if message.type == MessageType.LOG:
            if isinstance(message.data, Dict):
                self.benchmark_logs.append(json.dumps(message.data, indent=4))
            else:
                self.benchmark_logs.append(message.data)
        self.dump()

    def set_benchmark_status(self, status: str):
        """Set benchmark status."""
        self.benchmark_status = status
        self.dump()

    def set_benchmark_results(self, results: Dict):
        """Set benchmark status."""
        self.benchmark_results = results
        self.dump()


class Manager:
    """
    The config manager for the demo dashboard.
    """

    def __init__(self):
        home_folder = os.path.expanduser("~")
        self.folder = os.path.join(home_folder, ".mcpuniverse")
        if not os.path.isdir(self.folder):
            os.makedirs(self.folder, exist_ok=True)
        self.tmp_folder = os.path.join(self.folder, "tmp")
        if not os.path.isdir(self.tmp_folder):
            os.makedirs(self.tmp_folder, exist_ok=True)

        # Configs
        self.agent_config_file = os.path.join(self.folder, "agent_list.json")
        self.agent_configs = {}
        self.mcp_config_file = os.path.join(self.folder, "server_list.json")
        self.mcp_configs = {}
        self.benchmark_folder = ""
        self.benchmark_configs = {}
        self._load_configs()

        # Callback and state
        self.callback = MemoryHandler()
        self.state = None
        self.trace_collector = MemoryCollector()
        self.benchmark_state = None

    def _load_configs(self):
        """Load agent, MCP server and benchmark configurations."""
        folder = os.path.dirname(os.path.realpath(__file__))
        default_mcp_config = os.path.join(folder, "../mcp/configs/server_list.json")
        with open(default_mcp_config, "r", encoding="utf-8") as f:
            mcp_configs = json.loads(f.read())
        # The default MCP server configs cannot be changed
        self.mcp_configs = {}
        if os.path.exists(self.mcp_config_file):
            with open(self.mcp_config_file, "r", encoding="utf-8") as f:
                self.mcp_configs = json.loads(f.read())
        self.mcp_configs.update(mcp_configs)
        with open(self.mcp_config_file, "w", encoding="utf-8") as f:
            json.dump(self.mcp_configs, f)

        if os.path.exists(self.agent_config_file):
            with open(self.agent_config_file, "r", encoding="utf-8") as f:
                config = f.read().strip()
                self.agent_configs = {} if not config else json.loads(config)

        self.benchmark_folder = os.path.join(folder, "../benchmark/configs")
        for name in os.listdir(self.benchmark_folder):
            folder = os.path.join(self.benchmark_folder, name)
            if not os.path.isdir(folder):
                continue
            for file in os.listdir(folder):
                if file.endswith(".yaml") or file.endswith(".yml"):
                    benchmark_name = os.path.join(name, file)
                    with open(os.path.join(folder, file), "r", encoding="utf-8") as f:
                        objects = yaml.safe_load_all(f)
                        for obj in objects:
                            obj = dict(obj)
                            if obj["kind"].lower() == "benchmark":
                                config = BenchmarkConfig.model_validate(obj["spec"])
                                self.benchmark_configs[benchmark_name] = {
                                    "description": config.description,
                                    "tasks": config.tasks
                                }

    def _build_workflow(self, project_id: str, config: str | dict,
                        context: Optional[Context] = None) -> WorkflowBuilder:
        """Build agents/workflows given the configuration."""
        mcp_manager = MCPManager(config=self.mcp_config_file, context=context)
        if isinstance(config, str):
            config = yaml.safe_load_all(config)
        workflow = WorkflowBuilder(mcp_manager=mcp_manager, config=config)
        workflow.build(project_id=project_id)
        workflow.set_context(context)
        undefined_vars = workflow.list_undefined_env_vars()
        if undefined_vars:
            raise RuntimeError(f"Environment variables are undefined: {undefined_vars}")
        return workflow

    def upsert_agent(self, name: str, config: str):
        """Upsert a new agent configuration."""
        if name.lower() == "new":
            raise ValueError(f"Agent name cannot be {name}")
        if not name.strip():
            raise ValueError("Agent name cannot be empty")
        if not config.strip():
            raise ValueError("Agent config cannot be empty")
        workflow = self._build_workflow(project_id=name, config=config)
        agent_name = workflow.get_entrypoint()
        if not agent_name:
            raise ValueError("No main agent, please set `is_main` flag")
        agent_config = list(yaml.safe_load_all(config))
        self.agent_configs[name] = agent_config
        with open(self.agent_config_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.agent_configs))

    def upsert_mcp_server(self, name: str, config: str):
        """Upsert a new MCP server."""
        if name.lower() == "new":
            raise ValueError(f"MCP server name cannot be {name}")
        if not name.strip():
            raise ValueError("MCP server name cannot be empty")
        if not config.strip():
            raise ValueError("MCP server config cannot be empty")
        mcp_config = json.loads(config)
        mcp_manager = MCPManager(config=self.mcp_config_file, context=None)
        mcp_manager.load_configs({name: mcp_config})
        self.mcp_configs[name] = mcp_config
        with open(self.mcp_config_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.mcp_configs))

    def get_agent_configs(self) -> Dict:
        """Return the agent configurations."""
        return self.agent_configs

    def get_mcp_configs(self) -> Dict:
        """Return the MCP server configurations."""
        return self.mcp_configs

    def get_benchmark_configs(self) -> Dict:
        """Return the benchmark configurations."""
        return self.benchmark_configs

    def get_benchmark_task_config(self, task: str) -> Dict:
        """Return the task configuration."""
        with open(os.path.join(self.benchmark_folder, task), "r", encoding="utf-8") as f:
            return json.load(f)

    async def chat(self, agent_name: str, message: str) -> str:
        """Run agent with an input message."""
        if agent_name == "":
            return "ERROR: Agent name is empty"
        if agent_name not in self.agent_configs:
            return f"ERROR: Agent {agent_name} is not found"
        async with AsyncExitStack():
            try:
                tracer = Tracer(collector=self.trace_collector)
                config = self.agent_configs[agent_name]
                workflow = self._build_workflow(project_id=agent_name, config=config)
                name = workflow.get_entrypoint()
                if not name:
                    raise ValueError("No main agent, please set `is_main` flag")
                agent = workflow.get_component(name)
                await agent.initialize()
                response = await agent.execute(message, tracer=tracer, callbacks=self.callback)
                result = response.get_response_str()
                self.state = ChatState(
                    agent_name=agent_name,
                    agent_config=config,
                    workflow=workflow,
                    trace_id=tracer.trace_id
                )
            except Exception as e:
                result = f"ERROR: {str(e)}"
                self.state = None
            finally:
                if agent:
                    await agent.cleanup()
            return result

    def get_chat_responses(self) -> Dict[str, Any]:
        """Return the responses of all the components."""
        if self.state is None:
            return {}
        ids = self.state.workflow.get_all_component_ids()
        responses = {}
        for source in ids:
            message = self.callback.get(source=source, message_type="response")
            if message:
                responses[source] = message.data
        return responses

    def get_traces(self) -> str:
        """Return the traces of the latest chat."""
        if self.state is None:
            return ""
        records = self.trace_collector.get(self.state.trace_id)
        return json.dumps([r.to_dict() for r in records], indent=2)

    def run_benchmark(self, benchmark_name: str, task_name: str, agent_name: str):
        """Run benchmarks."""
        if self.benchmark_state is not None:
            raise RuntimeError("The benchmark is still running. Please wait for a while.")

        async def _run():
            agent_config = self.agent_configs[agent_name]
            workflow = self._build_workflow(project_id=agent_name, config=agent_config)
            main_agent_name = workflow.get_entrypoint()
            if not main_agent_name:
                raise ValueError("No main agent, please set `is_main` flag")
            benchmark = self.benchmark_configs[benchmark_name]
            benchmark_config = BenchmarkConfig(
                description=benchmark["description"],
                agent=main_agent_name,
                tasks=benchmark["tasks"] if task_name.lower() in ["", "all"] else [task_name]
            )
            configs = []
            configs.extend(agent_config)
            configs.append({
                "kind": "benchmark",
                "spec": benchmark_config.model_dump(mode="json")
            })
            filename = f"{benchmark_config.md5()}.yaml"
            with open(os.path.join(self.tmp_folder, filename), "w", encoding="utf-8") as f:
                f.write(yaml.dump_all(configs))
            benchmark_runner = BenchmarkRunner(config=os.path.join(self.tmp_folder, filename))
            results = await benchmark_runner.run(
                trace_collector=MemoryCollector(),
                callbacks=self.benchmark_state
            )
            results = [r.model_dump(mode="json") for r in results]
            self.benchmark_state.set_benchmark_results(results[0])

        def _run_benchmark():
            self.benchmark_state.set_benchmark_status("Running")
            asyncio.run(_run())
            self.benchmark_state.set_benchmark_status("Completed")

        self.benchmark_state = BenchmarkState(
            output_folder=self.tmp_folder,
            benchmark_name=benchmark_name,
            task_name=task_name,
            agent_name=agent_name,
            benchmark_thread=threading.Thread(target=_run_benchmark)
        )
        self.benchmark_state.dump()
        self.benchmark_state.benchmark_thread.start()
        self.benchmark_state.benchmark_thread.join()
        self.benchmark_state = None

    def get_benchmark_state(self, benchmark_name: str, task_name: str, agent_name: str) -> BenchmarkState:
        """Return benchmark running states."""
        return BenchmarkState.load(
            output_folder=self.tmp_folder,
            benchmark_name=benchmark_name,
            task_name=task_name,
            agent_name=agent_name
        )


dashboard_manager = Manager()
