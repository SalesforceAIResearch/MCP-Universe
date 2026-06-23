"""
RolloutEngine - Main entry point for MCP-Universe rollout engine.

Uses MCP-Universe's native Agent and LLM components for rollout.

Supports three MCP transport modes:
- "stdio": Each agent creates new MCP process (not recommended)
- "sse": All agents share a single Gateway via SSE
- "docker_pool": Each agent gets isolated Docker container with Gateway (recommended)

Framework-neutral rollout orchestration helpers (sample materialization,
dispatcher config building, trajectory construction/dispatch, metric
aggregation) live in ``mcpuniverse.rl.core.rollout`` so they can be
reused by integrations (veRL, slime, ...) without depending on this
user-facing runner.
"""
# pylint: disable=broad-exception-caught
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union
import os

from loguru import logger

from mcpuniverse.mcp.env_pool import (
    DockerProvisioner, EnvPoolManager, EnvConfig
)
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator import Evaluator

from .core.config import (
    RolloutConfig, TrajectoryConfig,
    MCP_TRANSPORT_SSE, MCP_TRANSPORT_DOCKER_POOL
)
from .core.trace_logger import TrajectoryTraceLogger
from .core.trajectory import create_llm, Trajectory
from .core.types import RolloutBatchResult, TrajectoryResult
from .core.rollout import (
    build_rollout_dispatcher_config,
    build_rollout_trajectories,
    collect_rollout_batch_result,
    compute_rollout_metrics,
    dispatch_rollout_trajectories,
    prepare_mcp_servers_for_sample,
)


@dataclass
class RolloutOutput:
    """Output from a rollout batch.

    Contains complete trajectory information including responses, rewards,
    finish reasons, and aggregated metrics.

    Attributes:
        responses: Final responses from each trajectory.
        rewards: Reward values from evaluation.
        finish_reasons: Finish reasons for each trajectory.
        trajectories: Complete trajectory data dictionaries.
        rollout_metrics: Aggregated metrics across all trajectories.
    """
    responses: List[str] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    finish_reasons: List[str] = field(default_factory=list)
    trajectories: List[Dict[str, Any]] = field(default_factory=list)
    rollout_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert output to dictionary.

        Returns:
            Dictionary representation of the rollout output.
        """
        return {
            "responses": self.responses,
            "rewards": self.rewards,
            "finish_reasons": self.finish_reasons,
            "trajectories": self.trajectories,
            "rollout_metrics": self.rollout_metrics
        }

    def get_trajectory_texts(self) -> List[str]:
        """Get all trajectories as formatted text.

        Returns:
            List of formatted trajectory texts.
        """
        return [
            "\n".join(t.get("history", []))
            for t in self.trajectories
        ]

    def get_all_steps(self) -> List[List[Dict[str, Any]]]:
        """Get all steps from all trajectories.

        Returns:
            List of step lists, one per trajectory.
        """
        return [t.get("steps", []) for t in self.trajectories]

    def get_all_messages(self) -> List[List[Dict[str, Any]]]:
        """Get all conversation messages from all trajectories.

        Returns:
            List of message lists, one per trajectory.
        """
        return [t.get("messages", []) for t in self.trajectories]


def rollout_batch_result_to_output(result: RolloutBatchResult) -> RolloutOutput:
    """Convert a framework-neutral rollout batch result to legacy output."""
    def _get_value(trajectory: Any, key: str, default: Any) -> Any:
        if isinstance(trajectory, dict):
            return trajectory.get(key, default)
        return getattr(trajectory, key, default)

    def _to_record(trajectory: Any) -> Dict[str, Any]:
        if hasattr(trajectory, "to_rollout_record"):
            return trajectory.to_rollout_record()
        if hasattr(trajectory, "to_dict"):
            return trajectory.to_dict()
        if isinstance(trajectory, dict):
            return dict(trajectory)
        return {}

    trajectories = [_to_record(trajectory) for trajectory in result.trajectories]

    return RolloutOutput(
        responses=[
            _get_value(trajectory, "response", "")
            for trajectory in result.trajectories
        ],
        rewards=[
            _get_value(trajectory, "reward", 0.0)
            for trajectory in result.trajectories
        ],
        finish_reasons=[
            _get_value(trajectory, "finish_reason", "")
            for trajectory in result.trajectories
        ],
        trajectories=trajectories,
        rollout_metrics=result.metrics,
    )


class RolloutEngine:
    """Main engine for MCP-Universe rollout.

    Uses MCP-Universe's native Agent and LLM components for executing
    rollouts on batches of tasks.

    Supports three MCP transport modes:
    - "stdio": Each agent creates new MCP process (original mode)
    - "sse": All agents share a single Gateway via SSE
    - "docker_pool": Each agent gets isolated Docker container with Gateway (Env Pool)

    Example:
        ```python
        engine = RolloutEngine.from_config("config.yaml")
        output = await engine.run([{"instruction": "What's the weather?"}])

        # Dynamic endpoint update (for training)
        engine.update_model_endpoint("http://localhost:8000/v1")
        ```

    Configuration:
        ```yaml
        llm_type: llm_local
        llm_config:
          model_name: Qwen3-4B-Instruct
          base_url: null  # Will be set dynamically by training engine

        agent_mode: react_train  # react_train, harmony

        # MCP transport modes:
        # - "stdio": Each agent creates new MCP process (default)
        # - "sse": Shared Gateway via SSE
        # - "docker_pool": Docker Env Pool (each agent gets isolated container)
        mcp_transport: sse

        # For docker_pool mode:
        env_pool:
          docker_host: null  # null = local Docker, or "tcp://remote:2375"
          max_pool_size: 50
          dockerfile_path: path/to/Dockerfile

        mcp_servers:
          - name: weather
        ```

    Attributes:
        cfg: Configuration object.
        mcp_manager: MCP server manager instance.
        llm: Language model instance.
        trajectories: Dictionary mapping instance_id to trajectory dictionaries.
        _tasks: Dictionary mapping task paths to Task objects.
        _env_pool: Optional EnvPoolManager instance (for docker_pool mode).
    """

    def __init__(
        self,
        cfg: RolloutConfig,
        mcp_manager: Optional[MCPManager] = None
    ) -> None:
        self.cfg = cfg
        self.mcp_manager = mcp_manager or MCPManager()

        # Initialize LLM
        self._llm_type = cfg.llm_type
        self._llm_config = dict(cfg.llm_config) if cfg.llm_config else {}

        # For token mode with AsyncVLLMModel, ensure rollout_mode is set in config
        if cfg.rollout_mode == "token":
            self._llm_config["rollout_mode"] = "token"
            # Token mode requires async_vllm LLM type
            if self._llm_type not in ("async_vllm", "AsyncVLLMModel"):
                logger.warning(
                    f"Token mode requires async_vllm LLM type, but got {self._llm_type}. "
                    f"Automatically switching to async_vllm."
                )
                self._llm_type = "async_vllm"
        # Note: Do NOT add rollout_mode to llm_config for text mode
        # as LocalLLMConfig and other configs don't accept this parameter

        self.llm = create_llm(self._llm_type, self._llm_config)

        logger.info(
            f"RolloutEngine initialized with LLM: {self._llm_type}, "
            f"Agent mode: {cfg.agent_mode.value}, "
            f"Rollout mode: {cfg.rollout_mode}, "
            f"MCP transport: {cfg.mcp_transport}"
        )

        # Trajectories storage: {instance_id: {trajectory_id: Trajectory}}
        self.trajectories: Dict[Any, Dict[int, Trajectory]] = {}

        # Tasks and evaluators (loaded from config)
        self._tasks: Dict[str, Task] = {}
        self._load_tasks()

        # Trajectory trace logger
        self._trace_logger = TrajectoryTraceLogger(cfg.trace_log_dir) if cfg.trace_log_dir else None

        # Env Pool (for docker_pool mode)
        self._env_pool = None
        self._env_assignments: Dict[str, str] = {}  # trajectory_key -> env_id

        if cfg.mcp_transport == MCP_TRANSPORT_DOCKER_POOL or cfg.env_pool.enabled:
            self._init_env_pool()

    def _init_env_pool(self) -> None:
        """Initialize Docker Env Pool for docker_pool transport mode."""
        pool_cfg = self.cfg.env_pool

        # Build default EnvConfig from MCP servers
        server_names = [s.name for s in self.cfg.mcp_servers]
        default_config = EnvConfig(
            servers=server_names,
            dockerfile_path=pool_cfg.build.dockerfile_path,
            cpu_limit=pool_cfg.resources.cpu_limit,
            memory_limit=pool_cfg.resources.memory_limit,
            shm_size=pool_cfg.resources.shm_size,
            gateway_mode=pool_cfg.gateway_mode,
            use_dockerfile_cmd=pool_cfg.build.use_dockerfile_cmd,
            env_vars=pool_cfg.resources.env_vars,
            volumes=pool_cfg.resources.volumes,
        )

        # Create provisioner(s) - supports multi-host mode
        common_kwargs = {
            "base_port": pool_cfg.base_port,
            "startup_timeout": pool_cfg.startup_timeout,
            "build_context": pool_cfg.build.build_context,
            "auto_build": pool_cfg.build.auto_build,
            "image_prefix": pool_cfg.build.image_prefix,
            "config": default_config,
        }

        if pool_cfg.docker_hosts:
            provisioners = []
            for host_cfg in pool_cfg.docker_hosts:
                p = DockerProvisioner(
                    docker_host=host_cfg.get('docker_host'),
                    host=host_cfg.get('host', 'localhost'),
                    **common_kwargs,
                )
                provisioners.append(p)
            provisioner = provisioners[0]
        else:
            provisioner = DockerProvisioner(
                docker_host=pool_cfg.docker_host,
                host=pool_cfg.host,
                **common_kwargs,
            )
            provisioners = None

        # Create pool manager
        self._env_pool = EnvPoolManager(
            provisioner=provisioner,
            provisioners=provisioners,
            max_pool_size=pool_cfg.max_pool_size,
            reset_on_release=pool_cfg.reset_on_release,
        )

        hosts_desc = (
            f"{len(pool_cfg.docker_hosts)} hosts" if pool_cfg.docker_hosts
            else (pool_cfg.docker_host or 'local')
        )
        logger.info(
            f"Env Pool initialized: docker_host={hosts_desc}, "
            f"max_pool_size={pool_cfg.max_pool_size}, "
            f"servers={server_names}"
        )

    def _build_env_config(self) -> "EnvConfig":
        """Build EnvConfig from current RolloutConfig settings."""
        pool_cfg = self.cfg.env_pool
        return EnvConfig(
            servers=[s.name for s in self.cfg.mcp_servers],
            dockerfile_path=pool_cfg.build.dockerfile_path,
            cpu_limit=pool_cfg.resources.cpu_limit,
            memory_limit=pool_cfg.resources.memory_limit,
            shm_size=pool_cfg.resources.shm_size,
            gateway_mode=pool_cfg.gateway_mode,
            use_dockerfile_cmd=pool_cfg.build.use_dockerfile_cmd,
            env_vars=pool_cfg.resources.env_vars,
            volumes=pool_cfg.resources.volumes,
        )

    def update_model_endpoint(
        self,
        endpoint: str,
        model_name: Optional[str] = None
    ) -> None:
        """Update the model endpoint dynamically.

        This is used by training engines to point the rollout engine to the
        current actor model's inference endpoint.

        Args:
            endpoint: The new model endpoint URL (e.g., "http://localhost:8000/v1").
            model_name: Optional new model name.

        Example:
            ```python
            # Training engine starts vLLM server and passes endpoint
            runner.update_model_endpoint("http://192.168.1.100:8000/v1")

            # Or with different model name
            runner.update_model_endpoint(
                "http://localhost:8000/v1",
                model_name="meta-llama/Llama-3.1-8B-Instruct"
            )
            ```
        """
        self._llm_config["base_url"] = endpoint
        if model_name:
            self._llm_config["model_name"] = model_name

        # Recreate LLM with new endpoint
        self.llm = create_llm(self._llm_type, self._llm_config)

        log_msg = f"Model endpoint updated to: {endpoint}"
        if model_name:
            log_msg += f", model: {model_name}"
        logger.info(log_msg)

    def get_model_endpoint(self) -> str:
        """Get the current model endpoint.

        Returns:
            Current model endpoint URL, or empty string if not set.
        """
        return self._llm_config.get("base_url", "")

    def update_llm_config(self, **kwargs: Any) -> None:
        """Update LLM configuration and recreate the LLM.

        Args:
            **kwargs: LLM config parameters to update.

        Example:
            ```python
            runner.update_llm_config(
                base_url="http://localhost:8000/v1",
                model_name="llama-3",
                temperature=0.7
            )
            ```
        """
        self._llm_config.update(kwargs)
        self.llm = create_llm(self._llm_type, self._llm_config)
        logger.info(f"LLM config updated: {kwargs}")

    @classmethod
    def from_config(
        cls,
        config_path: str,
        mcp_manager: Optional[MCPManager] = None
    ) -> "RolloutEngine":
        """Load engine from config file.

        Args:
            config_path: Path to YAML config file.
            mcp_manager: Optional MCPManager instance.

        Returns:
            RolloutEngine instance initialized from config.
        """
        cfg = RolloutConfig.from_yaml(config_path)
        return cls(cfg, mcp_manager)

    def _load_tasks(self) -> None:
        """Load task definitions from config."""
        for task_path in self.cfg.tasks:
            if os.path.exists(task_path):
                task = Task(task_path)
                self._tasks[task_path] = task

    def _get_sample_servers(self, sample: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract MCP servers from a sample.

        Args:
            sample: Sample dictionary potentially containing mcp_servers.

        Returns:
            List of MCP server configuration dictionaries.
        """
        return prepare_mcp_servers_for_sample(
            sample,
            default_servers=self.cfg.mcp_servers,
            use_default_servers=not self.cfg.use_sample_servers,
        )

    def _get_evaluators(self, instance: Dict[str, Any]) -> List[Evaluator]:
        """Get evaluators for an instance.

        Args:
            instance: Instance dictionary potentially containing task_path
                or evaluators.

        Returns:
            List of Evaluator instances.
        """
        # Check if instance has task reference
        task_path = instance.get("task_path") or instance.get("task")
        if task_path and task_path in self._tasks:
            return self._tasks[task_path].get_evaluators()

        # Check if instance has inline evaluators (from sample)
        if "evaluators" in instance:
            return [Evaluator(e) for e in instance["evaluators"]]

        return []

    def _get_num_trajectories(self, val_mode: bool = False) -> int:
        """Return the configured trajectory count for train or validation rollout."""
        return (
            self.cfg.generator.val_num_trajectories if val_mode
            else self.cfg.generator.num_trajectories
        )

    def _build_rollout_trajectory_kwargs(
        self,
        val_mode: bool = False,
    ) -> Dict[str, Any]:
        """Build shared trajectory-construction kwargs for this engine."""
        # Determine MCP gateway address based on transport mode.
        # For docker_pool mode, each trajectory will get its own address later.
        base_gateway_address = ""
        if self.cfg.mcp_transport == MCP_TRANSPORT_SSE:
            base_gateway_address = self.cfg.mcp_gateway_address

        def _trajectory_config_kwargs(_instance, _instance_id, _traj_id):
            # For token mode, forward sampling params from llm_config to
            # TrajectoryConfig so TITOLLMWrapper gets the expected generation params.
            traj_kwargs = {"mcp_gateway_address": base_gateway_address}
            if self.cfg.rollout_mode == "token":
                _sampling_keys = (
                    "temperature", "top_p", "max_tokens", "stop",
                    "include_stop_str_in_output", "skip_special_tokens",
                )
                overrides = {
                    k: v for k, v in self._llm_config.items()
                    if k in _sampling_keys
                }
                if overrides:
                    sp = dict(TrajectoryConfig().sampling_params)
                    sp.update(overrides)
                    traj_kwargs["sampling_params"] = sp
            return traj_kwargs

        def _build_env_callbacks(instance_id, traj_id, _instance, _mcp_servers):
            if self._env_pool is None:
                return None, None
            _iid, _tid = instance_id, traj_id

            async def _acquire(_iid=_iid, _tid=_tid):
                return await self._acquire_env_for_trajectory(_iid, _tid)

            async def _release(_iid=_iid, _tid=_tid):
                key = f"{_iid}-{_tid}"
                env_id = self._env_assignments.pop(key, None)
                if env_id:
                    await self._env_pool.release(env_id)

            return _acquire, _release

        return {
            "num_trajectories": self._get_num_trajectories(val_mode),
            "mcp_manager": self.mcp_manager,
            "agent_mode": self.cfg.agent_mode,
            "max_iterations": self.cfg.generator.max_iterations,
            "formatter_type": self.cfg.formatter_type,
            "rollout_mode": self.cfg.rollout_mode,
            "agent_config": self.cfg.agent_config,
            "val_mode": val_mode,
            "trace_logger": self._trace_logger,
            "get_mcp_servers": self._get_sample_servers,
            "get_evaluators": self._get_evaluators,
            "create_llm_for_trajectory": lambda _val_mode: self.llm,
            "build_env_callbacks": _build_env_callbacks,
            "trajectory_config_kwargs": _trajectory_config_kwargs,
        }

    def _build_dispatcher_config(
        self,
        batch_size: int,
        val_mode: bool = False,
    ) -> Dict[str, Any]:
        """Build dispatcher config for a standalone rollout batch."""
        return build_rollout_dispatcher_config(
            self.cfg.dispatcher,
            num_instances=batch_size,
            num_trajectories=self._get_num_trajectories(val_mode),
            include_max_eval_parallel_agents=True,
        )

    def _initialize_trajectories(
        self,
        batch: List[Dict[str, Any]],
        val_mode: bool = False
    ) -> None:
        """Initialize trajectory objects for the batch.

        Args:
            batch: List of instance dictionaries.
            val_mode: Whether to use validation settings.
        """
        self.trajectories = {}
        self._env_assignments = {}  # Reset env assignments

        self.trajectories = build_rollout_trajectories(
            batch,
            **self._build_rollout_trajectory_kwargs(val_mode),
        )

    @staticmethod
    def _compute_rollout_metrics(
        results: List[TrajectoryResult],
        num_instances: int,
    ) -> Dict[str, Any]:
        """Compute aggregated rollout metrics from a flat list of results."""
        return compute_rollout_metrics(results, num_instances)

    def _collect_batch_result(self) -> RolloutBatchResult:
        """Collect completed trajectories into the generic rollout result."""
        return collect_rollout_batch_result(
            self.trajectories,
            num_instances=len(self.trajectories),
        )

    def _postprocess_results(self) -> RolloutOutput:
        """Collect trajectory results into the legacy output container.

        Returns:
            RolloutOutput containing all processed results and metrics.
        """
        return rollout_batch_result_to_output(self._collect_batch_result())

    async def _provision_env_pool(
        self,
        num_envs: int,
        config: Optional[Any] = None
    ) -> None:
        """Provision environments in the Env Pool.

        Args:
            num_envs: Number of environments to provision.
            config: Optional EnvConfig override.
        """
        if self._env_pool is None:
            return

        if config is None:
            config = self._build_env_config()

        logger.info(f"Provisioning {num_envs} environments in Env Pool...")
        await self._env_pool.provision(
            num_envs=num_envs,
            config=config,
            parallel=True,
            reuse_existing=self.cfg.env_pool.reuse_existing
        )
        logger.info(f"Env Pool ready: {self._env_pool.get_stats()}")

    async def _acquire_env_for_trajectory(
        self,
        instance_id: Any,
        traj_id: int
    ) -> Optional[str]:
        """Acquire an environment from the pool for a trajectory.

        Args:
            instance_id: Instance identifier.
            traj_id: Trajectory identifier.

        Returns:
            Gateway address for the acquired environment, or None if not using pool.
        """
        if self._env_pool is None:
            return None

        config = self._build_env_config()
        traj_key = f"{instance_id}-{traj_id}"
        agent_id = f"agent-{traj_key}"

        env = await self._env_pool.acquire(agent_id=agent_id, config=config)
        self._env_assignments[traj_key] = env.env_id

        return env.gateway_address

    async def _release_all_envs(self) -> None:
        """Release all acquired environments back to the pool."""
        if self._env_pool is None:
            return

        for _, env_id in self._env_assignments.items():
            try:
                await self._env_pool.release(env_id)
            except Exception as e:
                logger.warning(f"Failed to release env {env_id}: {e}")

        self._env_assignments = {}

    @staticmethod
    def _normalize_input_batch(
        input_batch: Union[List[Dict[str, Any]], Dict[str, Any], Iterable[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Normalize user-provided rollout input into a list of samples."""
        if isinstance(input_batch, dict):
            if "batch" in input_batch:
                batch = input_batch["batch"]
                if hasattr(batch, "tolist"):
                    batch = batch.tolist()
                return list(batch)
            return [input_batch]
        if hasattr(input_batch, "__iter__"):
            return list(input_batch)
        return [input_batch]

    async def run_batch_result(
        self,
        input_batch: Union[List[Dict[str, Any]], Dict[str, Any], Iterable[Dict[str, Any]]],
        val_mode: bool = False
    ) -> RolloutBatchResult:
        """Run rollout and return a framework-neutral batch result.

        Args:
            input_batch: List of instances, each containing:
                - instruction/question: The task prompt
                - mcp_servers: Optional MCP servers (dynamic mode)
                - evaluators: Optional evaluators (dynamic mode)
                - output_format: Optional expected output format
            val_mode: Whether to use validation settings.

        Returns:
            RolloutBatchResult with trajectory results and metrics.
        """
        batch = self._normalize_input_batch(input_batch)

        mode = "dynamic" if self.cfg.use_sample_servers else "static"
        transport = self.cfg.mcp_transport
        logger.info(f"Running rollout on {len(batch)} instances, "
                   f"mode={mode}, transport={transport}, val_mode={val_mode}, "
                   f"num_trajectories={self.cfg.generator.num_trajectories}")

        # Initialize trajectories
        self._initialize_trajectories(batch, val_mode)

        try:
            # For docker_pool mode: provision environments based on max_init_agents
            # Trajectories will acquire/release environments dynamically during execution
            if self._env_pool is not None:
                # Only provision max_init_agents environments (not total_trajectories)
                # This allows environment reuse across batches
                max_parallel = self.cfg.dispatcher.max_init_agents
                await self._provision_env_pool(num_envs=max_parallel)

            dispatcher_cfg = self._build_dispatcher_config(
                batch_size=len(batch),
                val_mode=val_mode,
            )

            await dispatch_rollout_trajectories(
                self.trajectories,
                dispatcher_cfg=dispatcher_cfg,
            )

            result = self._collect_batch_result()

            logger.info(f"Rollout complete: {result.metrics}")

            return result

        finally:
            # Release all environments back to pool
            if self._env_pool is not None:
                await self._release_all_envs()

            self.trajectories = {}

    async def run(
        self,
        input_batch: Union[List[Dict[str, Any]], Dict[str, Any], Iterable[Dict[str, Any]]],
        val_mode: bool = False
    ) -> RolloutOutput:
        """Run rollout on a batch of inputs and return legacy output."""
        return rollout_batch_result_to_output(
            await self.run_batch_result(input_batch, val_mode=val_mode)
        )


# ============================================================================
# Convenience function
# ============================================================================

async def rollout(
    prompts: List[str],
    mcp_servers: List[str],
    llm_type: str = "vllm_local",
    llm_config: Optional[Dict[str, Any]] = None,
    agent_mode: str = "react_train",
    num_trajectories: int = 1,
    max_iterations: int = 10
) -> RolloutOutput:
    """Simple rollout function for quick testing.

    Args:
        prompts: List of prompts to execute.
        mcp_servers: List of MCP server names.
        llm_type: LLM type (vllm_local, sglang_local, local_llm, etc.).
        llm_config: LLM config dictionary.
        agent_mode: Agent mode (react_train, harmony).
        num_trajectories: Number of trajectories per prompt.
        max_iterations: Max iterations per trajectory.

    Returns:
        RolloutOutput containing results.
    """
    config = RolloutConfig.from_dict({
        "llm_type": llm_type,
        "llm_config": llm_config or {"model_name": "Qwen3-4B-Instruct"},
        "agent_mode": agent_mode,
        "mcp_servers": [{"name": s} for s in mcp_servers],
        "generator": {
            "num_trajectories": num_trajectories,
            "max_iterations": max_iterations
        }
    })

    engine = RolloutEngine(config)

    batch = [{"instruction": p} for p in prompts]

    return await engine.run(batch)
