"""Configuration for MCP-Universe RL rollout engine.

Uses MCP-Universe's native Agent and LLM components.
"""
import dataclasses
from dataclasses import dataclass, field, MISSING
from typing import List, Dict, Any, Optional
from enum import Enum
from omegaconf import OmegaConf


# Default configuration values
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_NUM_TRAJECTORIES = 1
DEFAULT_DISPATCHER_TYPE = "async_pipeline"
DEFAULT_FORMATTER_TYPE = "gpt_oss"
DEFAULT_TRANSPORT = "stdio"
DEFAULT_ROLLOUT_MODE = "text"  # "text" or "token"

# MCP transport modes
MCP_TRANSPORT_STDIO = "stdio"      # Each agent creates new MCP process
MCP_TRANSPORT_SSE = "sse"          # Shared Gateway via SSE
MCP_TRANSPORT_DOCKER_POOL = "docker_pool"  # Docker Env Pool (each agent gets isolated container)


def _dataclass_from_dict(cls, d: dict):
    """Construct a dataclass *cls* from *d*, using field defaults for missing keys."""
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in d:
            kwargs[f.name] = d[f.name]
        elif f.default is not MISSING:
            kwargs[f.name] = f.default
        elif f.default_factory is not MISSING:
            kwargs[f.name] = f.default_factory()
    return cls(**kwargs)


class AgentMode(str, Enum):
    """Supported agent modes - maps to MCP-Universe Agent classes.
    
    Attributes:
        HARMONY: HarmonyReAct agent mode.
        REACT_TRAIN: ReActTrain agent mode (for Qwen3 and other models).
    """
    HARMONY = "harmony"
    REACT_TRAIN = "react_train"

    @classmethod
    def from_str(cls, s: str) -> "AgentMode":
        """Convert string to AgentMode.
        
        Args:
            s: String representation of agent mode.
            
        Returns:
            AgentMode enum value, defaults to REACT_TRAIN if not found.
        """
        mapping = {
            "harmony": cls.HARMONY,
            "harmony_react": cls.HARMONY,
            "react_train": cls.REACT_TRAIN,
            "react_qwen3": cls.REACT_TRAIN,
            "qwen3": cls.REACT_TRAIN,
        }
        return mapping.get(s.lower(), cls.REACT_TRAIN)

    def to_agent_class_name(self) -> str:
        """Convert to MCP-Universe agent class name.
        
        Returns:
            Agent class name string.
        """
        mapping = {
            AgentMode.HARMONY: "HarmonyReAct",
            AgentMode.REACT_TRAIN: "ReActTrain",
        }
        return mapping.get(self, "ReActTrain")


@dataclass
class ServerConfig:
    """Server configuration.

    Attributes:
        name: Server name.
        tools: Optional list of tool names to expose.
        permissions: Optional list of permission dictionaries.
        transport: Transport type (default: "stdio").
    """
    name: str
    tools: Optional[List[str]] = None
    permissions: Optional[List[Dict[str, Any]]] = None
    transport: str = DEFAULT_TRANSPORT


@dataclass
class GeneratorConfig:
    """Generator/rollout configuration.
    
    Attributes:
        max_iterations: Maximum iterations per trajectory.
        num_trajectories: Number of trajectories per instance.
        val_num_trajectories: Number of trajectories per instance in validation mode.
    """
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    num_trajectories: int = DEFAULT_NUM_TRAJECTORIES
    val_num_trajectories: int = DEFAULT_NUM_TRAJECTORIES


@dataclass
class DispatcherConfig:
    """Dispatcher configuration.
    
    Attributes:
        type: Dispatcher type (async_batch, async_pipeline, async_pool, sequential).
        max_parallel_agents: Maximum parallel agents for run stage.
        max_eval_parallel_agents: Maximum parallel agents for eval stage.
        max_init_retries: Maximum retries for trajectory initialization (e.g., MCP server timeouts).
        init_retry_delay: Delay between init retries in seconds.
    """
    type: str = DEFAULT_DISPATCHER_TYPE
    max_parallel_agents: int = 32
    max_eval_parallel_agents: int = 64
    max_init_retries: int = 3
    init_retry_delay: float = 5.0


@dataclass
class DockerBuildConfig:
    """Docker image build configuration.

    Attributes:
        dockerfile_path: Optional custom Dockerfile path.
        build_context: Docker build context directory.
        auto_build: Whether to auto-build image if not exists.
        image_prefix: Prefix for auto-generated image names.
        use_dockerfile_cmd: Use Dockerfile's CMD instead of appending gateway command.
    """
    dockerfile_path: Optional[str] = None
    build_context: str = "."
    auto_build: bool = True
    image_prefix: str = "mcp-universe/gateway"
    use_dockerfile_cmd: bool = False


@dataclass
class ContainerResourceConfig:
    """Container resource limits and runtime configuration.

    Attributes:
        cpu_limit: CPU limit per container (e.g., "2").
        memory_limit: Memory limit per container (e.g., "4g").
        shm_size: /dev/shm size (e.g., "2g"). Needed for browser/Chromium workloads.
        env_vars: Extra environment variables passed to containers (e.g., API keys).
        volumes: Extra volume mounts ("host_path:container_path").
    """
    cpu_limit: str = "2"
    memory_limit: str = "4g"
    shm_size: Optional[str] = None
    env_vars: Dict[str, str] = field(default_factory=dict)
    volumes: List[str] = field(default_factory=list)


@dataclass
class EnvPoolConfig:
    """Docker Env Pool configuration.

    Used when mcp_transport="docker_pool" to manage isolated MCP environments.
    Each agent gets its own Docker container with Gateway.

    Attributes:
        enabled: Whether to use Docker Env Pool (auto-enabled when mcp_transport="docker_pool").
        docker_host: Docker host URL for single-host mode (None for local Docker).
        host: Host address for gateway URLs in single-host mode (default: "localhost").
        docker_hosts: List of Docker host configs for multi-host mode.
        base_port: Base port for port mapping.
        max_pool_size: Maximum environments in the pool.
        startup_timeout: Max time to wait for container to be ready.
        reuse_existing: Whether to reuse existing containers with matching config.
        reset_on_release: Whether to reset environment when released.
        gateway_mode: Gateway mode ("stdio" or "sse").
        build: Docker image build configuration.
        resources: Container resource limits and runtime configuration.
    """
    enabled: bool = False
    docker_host: Optional[str] = None
    host: str = "localhost"
    # Multi-host support: list of (docker_host, gateway_host) pairs
    # When set, docker_host/host above are ignored.
    # Example: [{"docker_host": "tcp://node1:2375", "host": "node1"},
    #           {"docker_host": "tcp://node2:2375", "host": "node2"}]
    docker_hosts: List[Dict[str, str]] = field(default_factory=list)
    base_port: int = 9000
    max_pool_size: int = 50
    startup_timeout: float = 120.0
    reuse_existing: bool = True
    reset_on_release: bool = True
    gateway_mode: str = "sse"
    network: str = "bridge"
    build: DockerBuildConfig = field(default_factory=DockerBuildConfig)
    resources: ContainerResourceConfig = field(default_factory=ContainerResourceConfig)


# Keys that belong to each sub-config (for backward-compatible flat dict parsing)
_BUILD_KEYS = frozenset(f.name for f in dataclasses.fields(DockerBuildConfig))
_RESOURCE_KEYS = frozenset(f.name for f in dataclasses.fields(ContainerResourceConfig))


def _env_pool_from_dict(d: dict) -> EnvPoolConfig:
    """Construct an EnvPoolConfig from *d*, accepting both flat and nested formats.

    Flat format (backward-compatible YAML)::

        dockerfile_path: ./Dockerfile
        cpu_limit: "4"

    Nested format::

        build:
          dockerfile_path: ./Dockerfile
        resources:
          cpu_limit: "4"
    """
    # Extract or build sub-config dicts
    build_dict = dict(d.get("build", {}))
    resource_dict = dict(d.get("resources", {}))

    # Promote flat keys into the appropriate sub-config
    for key, value in d.items():
        if key in _BUILD_KEYS and key not in build_dict:
            build_dict[key] = value
        elif key in _RESOURCE_KEYS and key not in resource_dict:
            resource_dict[key] = value

    pool_kwargs = {}
    for f in dataclasses.fields(EnvPoolConfig):
        if f.name == "build":
            pool_kwargs["build"] = _dataclass_from_dict(DockerBuildConfig, build_dict)
        elif f.name == "resources":
            pool_kwargs["resources"] = _dataclass_from_dict(ContainerResourceConfig, resource_dict)
        elif f.name in d:
            pool_kwargs[f.name] = d[f.name]
        elif f.default is not MISSING:
            pool_kwargs[f.name] = f.default
        elif f.default_factory is not MISSING:
            pool_kwargs[f.name] = f.default_factory()

    return EnvPoolConfig(**pool_kwargs)


@dataclass
class RolloutConfig:
    """Main configuration for RL rollout engine.

    Uses MCP-Universe's native Agent and LLM components.

    Example YAML:
    ```yaml
    # LLM configuration (uses mcpuniverse.llm.manager.ModelManager)
    llm_type: vllm_local  # or sglang_local, local_llm
    llm_config:
      model_name: Qwen3-8B

    # Agent mode (uses mcpuniverse.agent.manager.AgentManager)
    agent_mode: react_train  # react_train, harmony

    # Rollout mode: "text" (HTTP endpoint) or "token" (direct engine, token in/out)
    rollout_mode: text

    # MCP servers
    mcp_servers:
      - name: weather

    generator:
      num_trajectories: 4
    ```
    """
    # LLM configuration (uses mcpuniverse.llm.manager.ModelManager)
    llm_type: str = "vllm_local"
    llm_config: Dict[str, Any] = field(default_factory=lambda: {"model_name": "Qwen3-8B"})

    # Rollout mode: "text" (HTTP endpoint, text in/out) or "token" (direct engine, token in/out)
    # Token mode maintains token-level trajectory for RL training
    rollout_mode: str = DEFAULT_ROLLOUT_MODE

    # Agent mode - maps to agent class (FunctionCall, ReAct, HarmonyReAct, ReActTrain)
    agent_mode: AgentMode = AgentMode.REACT_TRAIN

    # Agent-specific config (passed to agent)
    agent_config: Dict[str, Any] = field(default_factory=dict)

    # Model-specific formatter for prompt/output split (gpt_oss, qwen, etc.)
    formatter_type: str = "qwen"

    # MCP servers (static mode)
    mcp_servers: List[ServerConfig] = field(default_factory=list)

    # Dynamic mode: read servers from each sample
    use_sample_servers: bool = False

    # MCP transport: "stdio" (default, each agent creates new process) or "sse" (shared via gateway)
    mcp_transport: str = "sse"

    # MCP gateway address for SSE transport (e.g., "http://localhost:8000")
    mcp_gateway_address: str = ""

    # Task JSON files (paths); scoped prepare uses ``benchmark_id`` (explicit, no path inference).
    tasks: List[str] = field(default_factory=list)

    # Suite id for :class:`~mcpuniverse.benchmark.task.Task` (scoped prepare registry).
    benchmark_id: str = "mcpuniverse"

    # Generator config
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)

    # Dispatcher config
    dispatcher: DispatcherConfig = field(default_factory=DispatcherConfig)

    # Env Pool config (for docker_pool transport)
    env_pool: EnvPoolConfig = field(default_factory=EnvPoolConfig)

    # Trajectory trace log directory (JSONL). None = disabled.
    trace_log_dir: Optional[str] = None

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "RolloutConfig":
        """Load config from YAML file.

        Args:
            yaml_path: Path to YAML configuration file.

        Returns:
            RolloutConfig instance loaded from YAML.
        """
        cfg = OmegaConf.load(yaml_path)
        return cls.from_dict(OmegaConf.to_container(cfg, resolve=True))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RolloutConfig":
        """Load config from dictionary.

        Args:
            d: Configuration dictionary.

        Returns:
            RolloutConfig instance loaded from dictionary.
        """
        # Parse MCP servers
        mcp_servers = []
        for server in d.get("mcp_servers", []):
            if isinstance(server, str):
                mcp_servers.append(ServerConfig(name=server))
            else:
                mcp_servers.append(_dataclass_from_dict(ServerConfig, server))

        # Parse generator / dispatcher configs
        generator = _dataclass_from_dict(GeneratorConfig, d.get("generator", {}))
        dispatcher = _dataclass_from_dict(DispatcherConfig, d.get("dispatcher", {}))

        # Parse agent mode (enum — needs manual handling)
        agent_mode = AgentMode.from_str(d.get("agent_mode", "react_train"))

        # Parse LLM config (string shorthand -> dict)
        llm_config = d.get("llm_config", {"model_name": "Qwen3-8B"})
        if isinstance(llm_config, str):
            llm_config = {"model_name": llm_config}

        # Parse env_pool config (special default for `enabled`)
        env_pool_dict = d.get("env_pool", {})
        mcp_transport = d.get("mcp_transport", "sse")
        if "enabled" not in env_pool_dict:
            env_pool_dict = dict(env_pool_dict, enabled=mcp_transport == MCP_TRANSPORT_DOCKER_POOL)
        env_pool = _env_pool_from_dict(env_pool_dict)

        return cls(
            llm_type=d.get("llm_type", "vllm_local"),
            llm_config=llm_config,
            rollout_mode=d.get("rollout_mode", DEFAULT_ROLLOUT_MODE),
            agent_mode=agent_mode,
            agent_config=d.get("agent_config", {}),
            formatter_type=d.get("formatter_type", "qwen"),
            mcp_servers=mcp_servers,
            use_sample_servers=d.get("use_sample_servers", False),
            mcp_transport=mcp_transport,
            mcp_gateway_address=d.get("mcp_gateway_address", ""),
            tasks=d.get("tasks", []),
            benchmark_id=d.get("benchmark_id", "mcpuniverse"),
            generator=generator,
            dispatcher=dispatcher,
            env_pool=env_pool,
            trace_log_dir=d.get("trace_log_dir"),
        )


@dataclass
class TrajectoryConfig:
    """Configuration for a single trajectory.
    
    Attributes:
        instance_id: Instance identifier.
        trajectory_id: Trajectory identifier.
        max_iterations: Maximum iterations for this trajectory.
        agent_mode: Agent mode to use.
        formatter_type: Model formatter type for prompt/output split.
        rollout_mode: Rollout mode ("text" or "token").
        sampling_params: Sampling parameters for LLM generation.
        mcp_gateway_address: MCP Gateway address for this trajectory (set by Env Pool).
        env_id: Environment ID if using Env Pool.
    """
    instance_id: Any = None
    trajectory_id: int = 0
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    agent_mode: AgentMode = AgentMode.REACT_TRAIN
    formatter_type: str = DEFAULT_FORMATTER_TYPE
    rollout_mode: str = DEFAULT_ROLLOUT_MODE
    sampling_params: Dict[str, Any] = field(default_factory=lambda: {
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": 2048,
        "max_prompt_length": 8192
    })
    mcp_gateway_address: str = ""  # Set by Env Pool or global config
    env_id: Optional[str] = None   # Environment ID if using Env Pool
