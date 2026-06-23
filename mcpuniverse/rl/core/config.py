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
DEFAULT_FORMATTER_TYPE = "gpt_oss"
DEFAULT_TRANSPORT = "stdio"
DEFAULT_ROLLOUT_MODE = "token"

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

    Known modes resolve to their canonical agent class. Any other value is
    passed through verbatim as an agent class name / alias, so any registered
    MCP-Universe agent can be selected by its class name or alias without
    extending this enum. Existing modes (``harmony``, ``react_train``) are
    unaffected.

    Attributes:
        HARMONY: HarmonyReAct agent mode.
        REACT_TRAIN: ReActTrain agent mode (for Qwen3 and other models).
    """
    HARMONY = "harmony"
    REACT_TRAIN = "react_train"

    @classmethod
    def _missing_(cls, value):
        """Pass-through unknown values as custom agent class names/aliases.

        Returning a transient str-backed member lets ``agent_mode`` stay a
        single generic selector: known modes use the mapping below, anything
        else is handed to ``AgentManager`` as-is (resolved by class name or
        alias). Invalid values fail loudly at agent build time rather than
        being silently coerced to a default agent.
        """
        if isinstance(value, str) and value:
            pseudo = str.__new__(cls, value)
            pseudo._name_ = value
            pseudo._value_ = value
            return pseudo
        return None

    @classmethod
    def from_str(cls, s: str) -> "AgentMode":
        """Convert string to AgentMode.

        Args:
            s: String representation of agent mode.

        Returns:
            A known AgentMode for recognised aliases; otherwise a pass-through
            member carrying the raw value. Empty/invalid input defaults to
            REACT_TRAIN (unchanged behaviour).
        """
        if not isinstance(s, str) or not s:
            return cls.REACT_TRAIN
        mapping = {
            "harmony": cls.HARMONY,
            "harmony_react": cls.HARMONY,
            "react": cls.REACT_TRAIN,
            "react_train": cls.REACT_TRAIN,
        }
        key = s.lower()
        if key in mapping:
            return mapping[key]
        return cls(s)  # unknown -> pass-through via _missing_

    def to_agent_class_name(self) -> str:
        """Convert to MCP-Universe agent class name.

        Returns:
            Canonical class name for known modes; the raw value (used as an
            AgentManager class name/alias) for pass-through modes.
        """
        mapping = {
            AgentMode.HARMONY: "HarmonyReAct",
            AgentMode.REACT_TRAIN: "ReActTrain",
        }
        return mapping.get(self, self.value)


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
        max_init_agents: Init-stage workers = max concurrent env/container
            acquisitions (run-stage concurrency defaults to 2x this).
        max_run_agents: Run-stage (generation) workers, decoupled from
            init/container concurrency. ``None`` -> default of
            2*max_init_agents (see ``core/pipeline.py::_parse_pipeline_params``).
        max_eval_parallel_agents: Maximum parallel agents for eval stage.
        max_init_retries: Maximum retries for trajectory initialization (e.g., MCP server timeouts).
        init_retry_delay: Delay between init retries in seconds.
        init_timeout: Per-attempt timeout (seconds) for ``traj.initialize()``.
            Default of 300s preserves the historical default behaviour (MCP
            server + container env cold start can easily exceed the 60s default
            in ``core/pipeline.py``); the in-process runner short-circuits
            this and uses the 60s dispatcher default instead.
        exec_timeout: Per-trajectory timeout (seconds) for ``traj.generate()``.
            Bump this for agents that legitimately need many sequential tool
            calls / long LLM rounds; the default of 300s is tuned for short
            tasks.
        cleanup_timeout: Per-trajectory timeout (seconds) for
            ``traj.cleanup()`` (env release + user cleanup hook).
    """
    max_init_agents: int = 32
    max_run_agents: Optional[int] = None
    max_eval_parallel_agents: int = 64
    max_init_retries: int = 3
    init_retry_delay: float = 5.0
    init_timeout: float = 300.0
    exec_timeout: float = 300.0
    cleanup_timeout: float = 30.0


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
class EnvPoolConfig:  # pylint: disable=too-many-instance-attributes
    """Environment pool configuration.

    Used when mcp_transport="docker_pool" to manage isolated MCP environments.
    Each agent gets its own container with a Gateway. The container backend is
    selected by ``provisioner_backend``: "docker" (daemon) or daemon-less
    "apptainer" (per-pod worker).

    Attributes:
        enabled: Whether to use the environment pool (auto-enabled when mcp_transport="docker_pool").
        docker_host: Docker host URL for single-host mode (None for local Docker).
        host: Host address for gateway URLs in single-host mode (default: "localhost").
        docker_hosts: List of Docker host configs for multi-host mode.
        base_port: Base port for port mapping.
        max_pool_size: Maximum environments in the pool.
        startup_timeout: Max time to wait for container to be ready.
        reuse_existing: Whether to reuse existing containers with matching config.
        reset_on_release: Whether to reset environment when released.
        gateway_mode: Gateway mode ("stdio" or "sse").
        env_servers: Fixed container server surface for pool reuse (empty = per-task).
        control_port_vars: Optional aux control-port templates ({ENV_VAR: "{port}"});
            the provisioner allocates a unique port per env and injects them.
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
    # Env-reuse policy applied on release:
    #   "cache"         -> return the container to the ready pool for reuse
    #                      (reusable, cold-start-heavy envs);
    #   "destroy"       -> tear the container down (per-task images that never
    #                      reuse, so caching them only fills the pool);
    #   "trimmed_cache" -> reuse up to the quotas below, destroy the surplus.
    reuse_policy: str = "cache"
    # Ready-cache quotas. For "cache" they are optional caps (0 = unbounded);
    # for "trimmed_cache" they bound the warm cache (0/0 = behaves like destroy).
    max_ready_envs: int = 0
    max_ready_per_key: int = 0
    # Provisioner backend: "docker" (default, dockerd) or "apptainer" (daemon-less
    # per-pod worker). The apptainer_* knobs configure that worker / its gateway
    # port window. MUST be declared here or the flat-dict parser drops them and
    # env_pool_runtime silently falls back to docker.
    provisioner_backend: str = "docker"
    apptainer_worker_port: int = 8900
    apptainer_port_range: int = 200
    gateway_mode: str = "sse"
    network: str = "bridge"
    # Fixed container server surface for pool reuse. When non-empty, every
    # container runs this exact server set (instead of each task's own servers)
    # so the pool can reuse containers across tasks whose per-task server sets
    # would otherwise differ and defeat reuse (e.g. stateful multi-server envs).
    # The agent still only sees its task's servers. Empty (default) -> per-task
    # servers (unchanged default).
    env_servers: List[str] = field(default_factory=list)
    # Optional per-env auxiliary "control" port templates: {ENV_VAR: "{port}"}.
    # The provisioner allocates a unique internal port per env and injects it
    # under these names (e.g. {"MY_CTRL_PORT": "{port}"}).
    # MUST be declared here or the flat-dict parser drops it -> the env falls back
    # to a hardcoded control port -> port collisions when the backend shares a
    # network namespace across envs (MCP_CONTROL_PORT_VARS env-var is a backup).
    control_port_vars: Dict[str, str] = field(default_factory=dict)
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

    # Rollout mode: "token" (direct engine, token in/out) or "text" (HTTP endpoint)
    rollout_mode: token

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
    formatter_type: str = DEFAULT_FORMATTER_TYPE

    # MCP servers (static mode)
    mcp_servers: List[ServerConfig] = field(default_factory=list)

    # Dynamic mode: read servers from each sample
    use_sample_servers: bool = False

    # MCP transport: "stdio" (default, each agent creates new process) or "sse" (shared via gateway)
    mcp_transport: str = "sse"

    # MCP gateway address for SSE transport (e.g., "http://localhost:8000")
    mcp_gateway_address: str = ""

    # Task files (JSON)
    tasks: List[str] = field(default_factory=list)

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

        # Parse agent mode (enum needs manual handling)
        agent_mode = AgentMode.from_str(d.get("agent_mode", "react_train"))

        # Parse LLM config (string shorthand -> dict)
        llm_config = d.get("llm_config", {"model_name": "Qwen3-8B"})
        if isinstance(llm_config, str):
            llm_config = {"model_name": llm_config}

        # Parse env_pool config (special default for `enabled`)
        env_pool_dict = d.get("env_pool", {})
        mcp_transport = d.get("mcp_transport", "sse")
        if env_pool_dict.get("enabled") is None:
            env_pool_dict = dict(env_pool_dict, enabled=mcp_transport == MCP_TRANSPORT_DOCKER_POOL)
        env_pool = _env_pool_from_dict(env_pool_dict)

        return cls(
            llm_type=d.get("llm_type", "vllm_local"),
            llm_config=llm_config,
            rollout_mode=d.get("rollout_mode", DEFAULT_ROLLOUT_MODE),
            agent_mode=agent_mode,
            agent_config=d.get("agent_config", {}),
            formatter_type=d.get("formatter_type", DEFAULT_FORMATTER_TYPE),
            mcp_servers=mcp_servers,
            use_sample_servers=d.get("use_sample_servers", False),
            mcp_transport=mcp_transport,
            mcp_gateway_address=d.get("mcp_gateway_address", ""),
            tasks=d.get("tasks", []),
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
