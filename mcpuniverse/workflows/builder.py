"""
Workflow Builder Module

This module provides classes and functionality for building and managing agent workflows.
It includes components for loading configurations, constructing dependency graphs,
and instantiating LLMs, agents, and workflows based on provided specifications.
"""
# pylint: disable=protected-access
from __future__ import annotations
import inspect
import typing
from typing import List, Literal, Dict, Any, Optional, get_args
from collections import defaultdict, deque

import yaml
from pydantic import BaseModel, Field
from mcpuniverse.common.misc import BaseBuilder, ComponentABCMeta
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import Executor, BaseAgent
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.manager import AgentManager
from mcpuniverse.common.context import Context


class Spec(BaseModel):
    """
    Represents the specification for a workflow component.

    Attributes:
        type (str): The type of the component (e.g., class names or alias).
        name (str): The unique name of the component.
        config (dict): Additional configuration parameters for the component.
    """
    type: str
    name: str
    config: dict = Field(default_factory=dict)
    is_main: Optional[bool] = Field(default=False)


class WorkflowConfig(BaseModel):
    """
    Represents a workflow configuration loaded from a YAML file.

    This class handles the loading and validation of workflow configurations,
    which can include LLMs, agents, and other workflows.

    Attributes:
        kind (Literal["llm", "agent", "workflow"]): The kind of component being configured.
        spec (Spec): The specification for the component.
    """
    kind: Literal["llm", "agent", "workflow"]
    spec: Spec

    @staticmethod
    def load(config: str | dict | List[dict]) -> List[WorkflowConfig]:
        """
        Load and parse workflow configurations from various input formats.

        Args:
            config (str | dict | List[dict]): The configuration source. Can be a file path (str),
                                              a single configuration (dict), or a list of configurations.

        Returns:
            List[WorkflowConfig]: A list of parsed WorkflowConfig objects.

        Raises:
            AssertionError: If the provided file is not a YAML file.
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
                return [WorkflowConfig.model_validate(o) for o in objects]
        if isinstance(config, dict):
            config = [config]
        return [WorkflowConfig.model_validate(o) for o in config]


class WorkflowBuilder(BaseBuilder):
    """
    Agent workflow builder.

    This class is responsible for constructing and managing agent workflows based on
    provided configurations. It handles dependency resolution, component instantiation,
    and provides access to built components.

    Attributes:
        _configs (List[WorkflowConfig]): Parsed workflow configurations.
        _agent_classes (Dict[str, Type]): Mapping of agent class names to their types.
        _workflow_classes (Dict[str, Type]): Mapping of workflow class names to their types.
        _mcp_manager (MCPManager): The MCP manager instance.
        _name2config (Dict[str, WorkflowConfig]): Mapping of component names to their configs.
        _graph (Dict[str, List[str]]): Dependency graph of components.
        _name2object (Dict[str, BaseLLM | Executor]): Mapping of component names to instantiated objects.
    """

    def __init__(self, mcp_manager: MCPManager, config: str | dict | List[dict]):
        self._configs = WorkflowConfig.load(config)
        self._agent_classes = self._name_to_class(ComponentABCMeta.get_class("agent"))
        self._workflow_classes = self._name_to_class(ComponentABCMeta.get_class("workflows"))
        self._mcp_manager = mcp_manager

        # Analyze config files
        self._name2config: Dict[str, WorkflowConfig] = {}
        for conf in self._configs:
            name = conf.spec.name
            assert name not in self._name2config, f"Found duplicated name: {name}"
            self._name2config[name] = conf
        self._graph: Dict[str, List[str]] = self._build_dependency_graph()
        self._name2object: Dict[str, BaseLLM | Executor] = {}

        # Set main agent if specified
        self._main = None
        for c in self._configs:
            if c.spec.is_main:
                if self._main is not None:
                    raise ValueError("There are more than one main agent")
                if c.kind not in ["agent", "workflow"]:
                    raise ValueError(f"`{c.kind}:{c.spec.name}` cannot be a main agent")
                self._main = c.spec.name

    def build(
            self,
            components: Optional[Dict[str, BaseLLM | Executor]] = None,
            project_id: Optional[str] = "local_test"
    ):
        """
        Build the agent workflow specified by the config file.

        This method instantiates all components defined in the configuration,
        resolving dependencies and constructing the workflow structure.

        Args:
            components (Dict[str, BaseLLM | Executor], optional): Pre-built components to use in the workflow.
                                                                  If provided, these will be used instead of
                                                                  building new instances for the specified names.
            project_id (str, optional): The project ID for this workflow.

        Raises:
            AssertionError: If a pre-built component name is not found in the configuration.
            Exception: If there are issues during the build process.
        """
        self._name2object = {}
        if components is not None:
            for name, component in components.items():
                assert name in self._name2config, f"Unknown component name: {name}"
                self._name2object[name] = component
        for conf in self._configs:
            self._build_component(conf, self._mcp_manager, project_id=project_id)

    def get_component(self, name: str) -> BaseLLM | Executor:
        """
        Retrieve a built workflow component by its name.

        Args:
            name (str): The name of the component to retrieve.

        Returns:
            BaseLLM | Executor: The instantiated component.

        Raises:
            RuntimeError: If the workflow has not been built yet.
            AssertionError: If the requested component name is not found.
        """
        if not self._name2object:
            raise RuntimeError("Failed to build agents/workflows")
        assert name in self._name2object, f"Unknown component name: {name}"
        return self._name2object[name]

    def dump_config(self) -> List[Dict[str, Any]]:
        """Dump workflow configs."""
        return [config.model_dump(mode="json") for config in self._configs]

    @staticmethod
    def _get_constructor_signature(object_class: Any) -> Dict[str, Dict[str, Any]]:
        """
        Get the `__init__` function signature of a class.

        Args:
            object_class: An object class to analyze.
        """
        init_method = getattr(object_class, "__init__")
        signature = inspect.signature(init_method)
        params = {}
        for name, param in signature.parameters.items():
            if name == "self":
                continue
            params[name] = {
                "type": param.annotation,
                "subtype": get_args(param.annotation),
                "default_value": param.default,
                "is_llm_or_executor": False
            }
            cls = param.annotation
            is_llm_or_executor = False
            try:
                if not isinstance(cls, (typing._GenericAlias, typing._SpecialGenericAlias)):
                    is_llm_or_executor = issubclass(cls, BaseLLM) or issubclass(cls, Executor)
                else:
                    for arg in get_args(cls):
                        if not isinstance(arg, (typing._GenericAlias, typing._SpecialGenericAlias)):
                            is_llm_or_executor = issubclass(arg, BaseLLM) or issubclass(arg, Executor)
                            if is_llm_or_executor:
                                break
            except TypeError:
                pass
            params[name]["is_llm_or_executor"] = is_llm_or_executor
        return params

    def _build_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Build the dependency graph according to the agent/workflow definitions.

        This method analyzes the configurations and constructs a graph representing
        the dependencies between different components in the workflow.

        Returns:
            Dict[str, List[str]]: A dictionary representing the dependency graph,
                                  where keys are component names and values are
                                  lists of dependencies.

        Raises:
            ValueError: If cycles are detected in the dependency graph.
            AssertionError: If there are missing or incorrect configurations.
        """
        graph = defaultdict(list)
        for config in self._configs:
            name = config.spec.name
            class_type = config.spec.type
            if config.kind.lower() == "llm":
                continue
            if config.kind.lower() == "agent":
                assert class_type in self._agent_classes, f"Wrong agent type: {class_type}"
                _class = self._agent_classes[class_type]
            elif config.kind.lower() == "workflow":
                assert class_type in self._workflow_classes, f"Wrong workflow type: {class_type}"
                _class = self._workflow_classes[class_type]
            else:
                raise ValueError(f"Wrong kind: {config.kind}")

            params = self._get_constructor_signature(_class)
            for param_name, param in params.items():
                if not param["is_llm_or_executor"]:
                    continue
                assert param_name in config.spec.config, \
                    f"Parameter `{param_name}` is not set in object `{name}`"
                value = config.spec.config[param_name]
                if isinstance(value, (list, tuple)):
                    for v in value:
                        assert v in self._name2config, f"Object `{v}` is not defined"
                        graph[name].append(v)
                else:
                    assert value in self._name2config, f"Object `{value}` is not defined"
                    graph[name].append(value)
        for name in graph.keys():
            graph[name] = list(set(graph[name]))

        # Check if there exists cycles
        visited = set()
        for name in graph.keys():
            if name in visited:
                continue
            queue = deque([(name, 0)])
            levels = {name: 0}
            while queue:
                node, level = queue.popleft()
                levels[node] = level
                visited.add(name)
                for x in graph.get(node, []):
                    if x in levels and levels[x] <= level:
                        raise ValueError("Cycles detected in the definitions")
                    if x in visited:
                        continue
                    queue.append((x, level + 1))
                    visited.add(x)
        return graph

    def _build_component(
            self,
            config: WorkflowConfig,
            mcp_manager: MCPManager,
            project_id: Optional[str] = "local_test"
    ) -> BaseLLM | Executor:
        """
        Build workflow components, e.g., LLMs, agents.

        Args:
            config: Workflow component config.
            mcp_manager: The MCP manager.
        """
        if config.spec.name in self._name2object:
            return self._name2object[config.spec.name]

        if config.kind.lower() == "llm":
            self._name2object[config.spec.name] = ModelManager().build_model(
                config.spec.type, config=config.spec.config)
            self._name2object[config.spec.name].set_name(config.spec.name)
            self._name2object[config.spec.name].project_id = project_id
            return self._name2object[config.spec.name]

        if config.kind.lower() == "agent":
            args = {
                "class_name": config.spec.type,
                "mcp_manager": mcp_manager,
                "config": {}
            }
            # Dynamic dependencies
            params = self._get_constructor_signature(self._agent_classes[config.spec.type])
            for name, param in params.items():
                if not param["is_llm_or_executor"]:
                    continue
                assert name in config.spec.config, \
                    f"Parameter {name} is not set in agent {config.spec.name}"
                var_name = config.spec.config[name]
                if isinstance(var_name, (list, tuple)):
                    components = []
                    for v in var_name:
                        if v not in self._name2object:
                            components.append(self._build_component(self._name2config[v], mcp_manager))
                        else:
                            components.append(self._name2object[v])
                    args[name] = components
                else:
                    if var_name not in self._name2object:
                        args[name] = self._build_component(self._name2config[var_name], mcp_manager)
                    else:
                        args[name] = self._name2object[var_name]
            # Static parameters
            for key, value in config.spec.config.items():
                if key in args:
                    continue
                args["config"][key] = value
            agent = AgentManager().build_agent(**args)
            agent.set_name(config.spec.name)
            agent.set_project_id(project_id=project_id)
            self._name2object[config.spec.name] = agent
            return agent

        if config.kind.lower() == "workflow":
            args = {}
            # Dynamic dependencies
            params = self._get_constructor_signature(self._workflow_classes[config.spec.type])
            for name, param in params.items():
                if not param["is_llm_or_executor"]:
                    continue
                assert name in config.spec.config, \
                    f"Parameter {name} is not set in workflow {config.spec.name}"
                var_name = config.spec.config[name]
                if isinstance(var_name, (list, tuple)):
                    components = []
                    for v in var_name:
                        if v not in self._name2object:
                            components.append(self._build_component(self._name2config[v], mcp_manager))
                        else:
                            components.append(self._name2object[v])
                    args[name] = components
                else:
                    if var_name not in self._name2object:
                        args[name] = self._build_component(self._name2config[var_name], mcp_manager)
                    else:
                        args[name] = self._name2object[var_name]
            # Static parameters
            for key, value in config.spec.config.items():
                if key in args:
                    continue
                args[key] = value
            workflow = self._workflow_classes[config.spec.type](**args)
            workflow.set_name(config.spec.name)
            workflow.project_id = project_id
            self._name2object[config.spec.name] = workflow
            return workflow

        raise ValueError("Shouldn't be here")

    def list_undefined_env_vars(self, **kwargs) -> List[str]:
        """
        Return a list of undefined environment variables used in this agent.

        Returns:
            List[str]: A list of undefined environment variables.
        """
        undefined_vars = []
        for _, obj in self._name2object.items():
            if hasattr(obj, "list_undefined_env_vars"):
                undefined_vars.extend(obj.list_undefined_env_vars(**kwargs))
        return undefined_vars

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        if context is None:
            return
        for _, obj in self._name2object.items():
            if hasattr(obj, "set_context"):
                obj.set_context(context)

    def get_entrypoint(self) -> str:
        """
        Return the entrypoint agent/workflow name.
        If there is only one workflow or agent, pick it as the main entrypoint.
        """
        if self._main:
            return self._main
        agents, workflows = [], []
        for name, component in self._name2object.items():
            if isinstance(component, BaseAgent):
                agents.append(name)
            elif isinstance(component, Executor):
                workflows.append(name)
        if len(workflows) == 1:
            self._main = workflows[0]
        elif len(agents) == 1:
            self._main = agents[0]
        return self._main

    def get_all_component_ids(self) -> List[str]:
        """
        Return the IDs of all the components.
        """
        ids = []
        for _, component in self._name2object.items():
            ids.append(component.id)
            ids.extend(component.get_children_ids())
        return sorted(list(set(ids)))
