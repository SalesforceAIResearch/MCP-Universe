"""
RolloutEngine - Main entry point for MCP-Universe rollout engine.

Uses MCP-Universe's native Agent and LLM components for rollout.

Supports three MCP transport modes:
- "stdio": Each agent creates new MCP process (original mode)
- "sse": All agents share a single Gateway via SSE
- "docker_pool": Each agent gets isolated Docker container with Gateway (Env Pool)
"""
# pylint: disable=broad-exception-caught
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Iterable
import os

from loguru import logger

from mcpuniverse.mcp.env_pool import (
    DockerProvisioner, EnvPoolManager, EnvConfig
)
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.benchmark.task import Task
from mcpuniverse.evaluator import Evaluator

from .config import (
    RolloutConfig, TrajectoryConfig,
    MCP_TRANSPORT_SSE, MCP_TRANSPORT_DOCKER_POOL
)
from .trace_logger import TrajectoryTraceLogger
from .trajectory import create_trajectory, create_llm, Trajectory, TrajectoryResult
from .dispatcher import get_dispatcher


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
                task = Task(task_path, benchmark_id=self.cfg.benchmark_id)
                self._tasks[task_path] = task

    def _get_sample_servers(self, sample: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract MCP servers from a sample.

        Args:
            sample: Sample dictionary potentially containing mcp_servers.

        Returns:
            List of MCP server configuration dictionaries.
        """
        servers = sample.get("mcp_servers", [])
        if not servers and not self.cfg.use_sample_servers:
            # Use config-level servers
            servers = [
                {
                    "name": s.name,
                    "tools": s.tools,
                    "permissions": s.permissions,
                    "transport": s.transport
                }
                for s in self.cfg.mcp_servers
            ]
        return servers

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

        num_trajectories = (
            self.cfg.generator.val_num_trajectories if val_mode
            else self.cfg.generator.num_trajectories
        )

        # Determine MCP gateway address based on transport mode
        # For docker_pool mode, each trajectory will get its own address later
        base_gateway_address = ""
        if self.cfg.mcp_transport == MCP_TRANSPORT_SSE:
            base_gateway_address = self.cfg.mcp_gateway_address

        for batch_idx, instance in enumerate(batch):
            instance_id = instance.get("instance_id", batch_idx)
            self.trajectories[instance_id] = {}

            # Get evaluators
            evaluators = self._get_evaluators(instance)

            # Get MCP servers for this sample
            mcp_servers = self._get_sample_servers(instance)

            # Prepare data
            data = {
                **instance,
                "instruction": instance.get("instruction") or instance.get("question", "")
            }

            for traj_id in range(num_trajectories):
                # For token mode, forward sampling params from llm_config
                # to TrajectoryConfig so that TITOLLMWrapper gets the
                # correct temperature, stop tokens, etc.
                traj_kwargs = {}
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
                        # Start from TrajectoryConfig defaults, then overlay
                        sp = dict(TrajectoryConfig().sampling_params)
                        sp.update(overrides)
                        traj_kwargs["sampling_params"] = sp

                traj_cfg = TrajectoryConfig(
                    instance_id=instance_id,
                    trajectory_id=traj_id,
                    max_iterations=self.cfg.generator.max_iterations,
                    agent_mode=self.cfg.agent_mode,
                    formatter_type=self.cfg.formatter_type,
                    rollout_mode=self.cfg.rollout_mode,
                    mcp_gateway_address=base_gateway_address,  # Will be updated for docker_pool
                    **traj_kwargs,
                )

                # Build env pool closures if pool is active
                acquire_env_fn = None
                release_env_fn = None
                if self._env_pool is not None:
                    _iid, _tid = instance_id, traj_id

                    async def _acquire(_iid=_iid, _tid=_tid):
                        return await self._acquire_env_for_trajectory(_iid, _tid)

                    async def _release(_iid=_iid, _tid=_tid):
                        key = f"{_iid}-{_tid}"
                        env_id = self._env_assignments.pop(key, None)
                        if env_id:
                            await self._env_pool.release(env_id)

                    acquire_env_fn, release_env_fn = _acquire, _release

                traj = create_trajectory(
                    cfg=traj_cfg,
                    data=data,
                    agent_mode=self.cfg.agent_mode,
                    llm=self.llm,
                    mcp_manager=self.mcp_manager,
                    mcp_servers=mcp_servers,
                    agent_config=self.cfg.agent_config,
                    evaluators=evaluators,
                    val_mode=val_mode,
                    acquire_env=acquire_env_fn,
                    release_env=release_env_fn,
                    trace_logger=self._trace_logger,
                )

                self.trajectories[instance_id][traj_id] = traj

    @staticmethod
    def _compute_rollout_metrics(
        results: List[TrajectoryResult],
        num_instances: int,
    ) -> Dict[str, Any]:
        """Compute aggregated rollout metrics from a flat list of results."""
        n = len(results)
        safe_n = max(n, 1)

        total_reward = sum(r.reward for r in results)
        success_count = sum(1 for r in results if r.reward > 0)
        error_count = sum(1 for r in results if r.error)
        total_steps = sum(r.num_steps for r in results)
        total_tool_calls = sum(r.num_tool_calls for r in results)
        total_running_time = sum(r.running_time for r in results)

        # Finish reason breakdown
        finish_reason_counts: Dict[str, int] = defaultdict(int)
        for r in results:
            finish_reason_counts[r.finish_reason] += 1

        # Instance-level resolution
        instance_rewards: Dict[Any, List[float]] = defaultdict(list)
        for r in results:
            instance_rewards[r.instance_id].append(r.reward)
        num_all_resolved = sum(
            1 for rws in instance_rewards.values() if all(r > 0 for r in rws)
        )
        num_none_resolved = sum(
            1 for rws in instance_rewards.values() if all(r == 0 for r in rws)
        )

        metrics: Dict[str, Any] = {
            "rollout_metrics/num_instances": num_instances,
            "rollout_metrics/num_trajectories": n,
            "rollout_metrics/total_reward": total_reward,
            "rollout_metrics/mean_reward": total_reward / safe_n,
            "rollout_metrics/success_rate": success_count / safe_n,
            "rollout_metrics/error_rate": error_count / safe_n,
            "rollout_metrics/total_steps": total_steps,
            "rollout_metrics/mean_steps": total_steps / safe_n,
            "rollout_metrics/total_tool_calls": total_tool_calls,
            "rollout_metrics/mean_tool_calls": total_tool_calls / safe_n,
            "rollout_metrics/total_running_time": total_running_time,
            "rollout_metrics/mean_running_time": total_running_time / safe_n,
            "rollout_metrics/num_all_resolved": num_all_resolved,
            "rollout_metrics/num_none_resolved": num_none_resolved,
        }

        for reason, count in finish_reason_counts.items():
            safe_reason = str(reason).lower().replace(" ", "_")
            metrics[f"rollout_metrics/finish_{safe_reason}"] = count
            metrics[f"rollout_metrics/finish_{safe_reason}_ratio"] = count / safe_n

        return metrics

    def _postprocess_results(self) -> RolloutOutput:
        """Collect trajectory results and compute metrics.

        Returns:
            RolloutOutput containing all processed results and metrics.
        """
        results = [
            traj.result
            for trajs in self.trajectories.values()
            for traj in trajs.values()
            if traj.result is not None
        ]

        metrics = self._compute_rollout_metrics(results, len(self.trajectories))

        return RolloutOutput(
            responses=[r.response for r in results],
            rewards=[r.reward for r in results],
            finish_reasons=[r.finish_reason for r in results],
            trajectories=[r.to_dict() for r in results],
            rollout_metrics=metrics,
        )

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

    async def run(
        self,
        input_batch: Union[List[Dict[str, Any]], Dict[str, Any], Iterable[Dict[str, Any]]],
        val_mode: bool = False
    ) -> RolloutOutput:
        """Run rollout on a batch of inputs.

        Args:
            input_batch: List of instances, each containing:
                - instruction/question: The task prompt
                - mcp_servers: Optional MCP servers (dynamic mode)
                - evaluators: Optional evaluators (dynamic mode)
                - output_format: Optional expected output format
            val_mode: Whether to use validation settings.

        Returns:
            RolloutOutput with rollout results.
        """
        # Parse input batch
        if isinstance(input_batch, dict):
            if "batch" in input_batch:
                batch = input_batch["batch"]
                if hasattr(batch, "tolist"):
                    batch = batch.tolist()
            else:
                batch = [input_batch]
        elif hasattr(input_batch, "__iter__"):
            batch = list(input_batch)
        else:
            batch = [input_batch]

        mode = "dynamic" if self.cfg.use_sample_servers else "static"
        transport = self.cfg.mcp_transport
        logger.info(f"Running rollout on {len(batch)} instances, "
                   f"mode={mode}, transport={transport}, val_mode={val_mode}, "
                   f"num_trajectories={self.cfg.generator.num_trajectories}")

        # Initialize trajectories
        self._initialize_trajectories(batch, val_mode)

        try:
            # For docker_pool mode: provision environments based on max_parallel_agents
            # Trajectories will acquire/release environments dynamically during execution
            if self._env_pool is not None:
                # Only provision max_parallel_agents environments (not total_trajectories)
                # This allows environment reuse across batches
                max_parallel = self.cfg.dispatcher.max_parallel_agents
                await self._provision_env_pool(num_envs=max_parallel)

            # Get dispatcher
            dispatcher = get_dispatcher(self.cfg.dispatcher.type)

            # Build dispatcher config
            num_trajectories = (
                self.cfg.generator.val_num_trajectories if val_mode
                else self.cfg.generator.num_trajectories
            )

            dispatcher_cfg = {
                "max_parallel_agents": self.cfg.dispatcher.max_parallel_agents,
                "max_eval_parallel_agents": self.cfg.dispatcher.max_eval_parallel_agents,
                "max_init_retries": self.cfg.dispatcher.max_init_retries,
                "init_retry_delay": self.cfg.dispatcher.init_retry_delay,
                "num_instances": len(batch),
                "num_trajectories": num_trajectories,
            }

            # Run dispatcher
            await dispatcher(dispatcher_cfg, self.trajectories)

            # Postprocess results
            output = self._postprocess_results()

            logger.info(f"Rollout complete: {output.rollout_metrics}")

            return output

        finally:
            # Release all environments back to pool
            if self._env_pool is not None:
                await self._release_all_envs()

            self.trajectories = {}


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
