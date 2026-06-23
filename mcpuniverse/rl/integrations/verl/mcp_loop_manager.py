"""
MCP Loop Manager for VERL integration.

Manages async agent rollout with MCP-Universe and VERL's inference backend
(supports both vLLM and SGLang, selected by ``actor_rollout_ref.rollout.name``).
"""
# pylint: disable=too-many-lines,broad-exception-caught,protected-access
# pylint: disable=import-outside-toplevel,attribute-defined-outside-init

import asyncio
import collections
import gc
import os
import subprocess
import threading
import weakref
from typing import Any, Dict, List, Optional

from omegaconf import DictConfig, OmegaConf
from loguru import logger

from verl.protocol import DataProto
from verl.single_controller.ray.base import RayWorkerGroup
from verl.utils.fs import copy_to_local
from verl.utils import hf_tokenizer
from verl.experimental.agent_loop.agent_loop import AgentLoopManager

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.rl.core.config import RolloutConfig
from mcpuniverse.rl.core.env_pool_runtime import (
    MCPEnvPoolRuntime,
)
from mcpuniverse.rl.core.rollout import (
    build_rollout_dispatcher_config,
    prepare_mcp_servers_for_sample,
    run_tokenized_rollout_batch,
)
from mcpuniverse.rl.core.trace_logger import TrajectoryTraceLogger
from mcpuniverse.rl.core.types import RolloutSample, TokenizedRolloutBatch
from mcpuniverse.rl.core.postprocess import (
    pop_private_rollout_metrics,
    tokenize_trajectory_result,
)
from mcpuniverse.rl.core.trajectory import create_llm
from mcpuniverse.rl.core.formatters import get_formatter
from mcpuniverse.evaluator.evaluator import Evaluator

from .async_bridge import get_fallback_loop, run_async_safely
from .data_proto_adapter import (
    data_proto_to_rollout_samples,
    tokenized_rollout_batch_to_data_proto,
)
from .utils import safe_get, suppress_noisy_logs

suppress_noisy_logs()


class MCPLoopManager(AgentLoopManager):  # pylint: disable=too-many-instance-attributes
    """
    Agent loop manager for MCP-Universe with VERL backend.

    Supports two modes:
    - Hybrid mode: Uses parent class's _initialize_llm_servers() to start inference servers
    - Fully async mode: Uses pre-discovered server addresses (passed via server_addresses)

    Supports both vLLM and SGLang inference backends, selected by
    ``actor_rollout_ref.rollout.name`` (default: "vllm").

    In fully async mode, weights are synced via NCCL from actor to rollout workers,
    so we must use the same inference servers that receive the synced weights.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self, config: DictConfig, worker_group: RayWorkerGroup = None,
        rm_wg: RayWorkerGroup = None,  # pylint: disable=unused-argument
        rollout_resource_pool=None, reward_loop_worker_handles=None,
        server_addresses: List[str] = None, rollout_replicas: list = None,
    ):
        """
        Initialize MCP loop manager.

        Args:
            config: VERL trainer config
            worker_group: VERL actor/rollout worker group
            rm_wg: Reward model worker group (optional)
            server_addresses: Pre-discovered inference server addresses (for fully async mode).
            rollout_replicas: Pre-created rollout replica objects (for TITO mode in fully async).
        """

        hybrid_engine = OmegaConf.select(config, "actor_rollout_ref.hybrid_engine", default=True)
        self._is_async_mode = not hybrid_engine
        logger.info(f"MCPLoopManager init: hybrid_engine={hybrid_engine}, is_async_mode={self._is_async_mode}")

        mcp_cfg = config.get("mcp_agent", {})

        # Determine rollout_mode BEFORE calling parent __init__
        # (needed because _initialize_llm_servers depends on rollout_mode)
        self.rollout_mode = mcp_cfg.get("rollout_mode", "text")
        logger.info(f"MCPLoopManager: rollout_mode={self.rollout_mode}")

        # Initialize tokenizer
        model_path = config.actor_rollout_ref.model.path
        self.model_name = model_path.split("/")[-1] if "/" in model_path else model_path
        local_path = copy_to_local(config.actor_rollout_ref.model.path)
        self.tokenizer = hf_tokenizer(local_path, trust_remote_code=True)

        self.mcp_manager = MCPManager()

        # Docker Env Pool state lives entirely on ``self._env_pool_runtime``
        # (see ``mcpuniverse.rl.core.env_pool_runtime.MCPEnvPoolRuntime``).
        self._env_pool_runtime: MCPEnvPoolRuntime | None = None
        self._step_counter = 0
        self._traj_counter = 0  # persistent round-robin index for LLM/replica assignment
        # Least-loaded replica assignment: per-replica count of in-flight
        # trajectories. Incremented at assignment, decremented via weakref.finalize
        # when a trajectory drops its TITO wrapper. Lock guards the finalizer
        # possibly firing on a GC thread.
        self._replica_inflight: List[int] = []
        self._replica_lock = threading.Lock()
        # weakref.finalize callbacks run on whatever thread GC/refcount fires on, so
        # they ONLY enqueue here (deque.append is thread-safe). The actual decrement
        # is applied on the event-loop thread at the next assignment. This guarantees
        # the finalizer never acquires _replica_lock -> it can never reentrantly
        # deadlock even if a cyclic GC fired inside a locked section.
        self._replica_pending_release: "collections.deque[int]" = collections.deque()

        # Trajectory trace logger (passed to each Trajectory for per-trajectory logging)
        trace_log_dir = mcp_cfg.get("trace_log_dir", None)
        self._trace_logger = TrajectoryTraceLogger(trace_log_dir) if trace_log_dir else None

        # Rollout settings
        # MCP trainer does NOT call gen_batch.repeat(), so we generate
        # rollout_n trajectories per instance here for GRPO
        rollout_n = config.actor_rollout_ref.rollout.get("n", 1)
        self.num_trajectories = rollout_n if rollout_n > 1 else mcp_cfg.get("num_trajectories", 1)
        self.val_num_trajectories = mcp_cfg.get("val_num_trajectories", 1)
        self.max_iterations = mcp_cfg.get("max_iterations", 10)
        logger.info(f"MCPLoopManager: num_trajectories={self.num_trajectories} (from rollout.n={rollout_n})")

        # Formatter for model-specific prompt/output split
        self.formatter_type = mcp_cfg.get("formatter_type", "gpt_oss")
        self.formatter = get_formatter(self.formatter_type)

        self.config = config
        self.worker_group = worker_group

        # Inference backend name (vllm or sglang)
        self._rollout_backend = OmegaConf.select(
            config, "actor_rollout_ref.rollout.name", default="vllm"
        )

        if self._is_async_mode:
            # Fully async mode: addresses pre-discovered via rollout replicas
            if not server_addresses:
                raise ValueError("server_addresses is required for fully async mode (hybrid_engine=False)")
            logger.info("Fully async mode with pre-discovered server addresses")
            self.worker_group = worker_group
            self.rollout_replicas = rollout_replicas or []
            self.server_addresses = server_addresses
        else:
            # Hybrid mode: parent __init__ sets self.config, self.worker_group,
            # rollout_replica_class, calls _initialize_llm_servers() and
            # _init_agent_loop_workers().
            super().__init__(  # pylint: disable=unexpected-keyword-arg
                config, worker_group,
                rollout_resource_pool=rollout_resource_pool,
                reward_loop_worker_handles=reward_loop_worker_handles,
            )

        self.mcp_config = self._parse_mcp_config()
        self._env_pool_runtime = MCPEnvPoolRuntime(
            self.mcp_config,
            is_async_mode=self._is_async_mode,
        )
        self._init_llm()

        logger.info(f"MCPLoopManager initialized with model: {self.model_name}")
        logger.info(f"  Mode: {'Fully Async' if self._is_async_mode else 'Hybrid'}")
        logger.info(f"  Backend: {self._rollout_backend}")
        logger.info(f"  Inference servers: {self.server_addresses}")
        logger.info(f"  Using formatter: {self.formatter_type}")

    def __del__(self):
        """Best-effort cleanup on garbage collection.

        Explicit ``shutdown`` (or ``close()``) is the primary cleanup
        path; this fallback only fires when the caller forgot. Guarded by
        the ``_closed`` flag so a second cleanup never runs after an
        explicit shutdown. See
        ``issues/solved/mcp_loop_manager_del_cleanup_unreliable.md``.
        """
        try:
            if not getattr(self, "_closed", False):
                self.shutdown()
        except Exception:
            pass

    async def close(self) -> None:
        """Explicitly close env-pool and local rollout resources."""
        if getattr(self, "_closed", False):
            return
        try:
            await self._cleanup_env_pool()
        finally:
            trace_logger = getattr(self, "_trace_logger", None)
            if trace_logger is not None:
                trace_logger.close()
                self._trace_logger = None
            self.llms = []
            self._rollout_servers = []
            self._closed = True

    def shutdown(self) -> None:
        """Synchronous cleanup entrypoint for Ray/task runners."""
        if getattr(self, "_closed", False):
            return
        self._run_async_safely(self.close())

    def _get_env_pool_runtime(self) -> MCPEnvPoolRuntime:
        """Return the env-pool runtime, lazily constructing it if missing.

        Lazy construction supports tests that build a manager via
        ``MCPLoopManager.__new__`` without going through ``__init__``.
        Late attribute changes (``mcp_config``, ``_is_async_mode``) are
        propagated on each call so test fixtures stay in sync.
        """
        runtime = getattr(self, "_env_pool_runtime", None)
        if runtime is None:
            runtime = MCPEnvPoolRuntime(
                getattr(self, "mcp_config", None),
                is_async_mode=getattr(self, "_is_async_mode", False),
            )
            self._env_pool_runtime = runtime
        else:
            runtime.mcp_config = getattr(self, "mcp_config", runtime.mcp_config)
            runtime.is_async_mode = getattr(self, "_is_async_mode", runtime.is_async_mode)
        return runtime

    @property
    def _env_pool_active(self) -> bool:
        """Whether the docker env pool is currently initialized and alive."""
        runtime = getattr(self, "_env_pool_runtime", None)
        return runtime is not None and runtime.env_pool is not None

    def _initialize_llm_servers(self, rollout_resource_pool=None):
        """Initialize LLM servers using parent's implementation.

        Both text and token (TITO) modes use the same VERL inference servers
        (vLLM or SGLang).  TITO's key difference is in how the agent rollout
        maintains token sequences, not on the server side.
        """
        if self.rollout_mode == "token":
            logger.info("=" * 70)
            logger.info("TITO MODE: Using VERL's native token-in-token-out support")
            logger.info(f"{self._rollout_backend} server generate() returns TokenOutput(token_ids, log_probs)")
            logger.info("=" * 70)

        super()._initialize_llm_servers(  # pylint: disable=too-many-function-args
            rollout_resource_pool,
        )

    def _parse_mcp_config(self) -> RolloutConfig:
        """Parse MCP config from VERL config."""
        config = self.config
        mcp_cfg = config.get("mcp_agent", {})

        # rollout_mode already set in __init__, but re-read in case config changed
        self.rollout_mode = mcp_cfg.get("rollout_mode", "text")

        env_pool_cfg = safe_get(mcp_cfg, "env_pool", {})

        return RolloutConfig.from_dict({
            "llm_type": safe_get(mcp_cfg, "llm_type", "OpenAI"),
            "llm_config": safe_get(mcp_cfg, "llm_config", {"model_name": self.model_name}),
            "rollout_mode": self.rollout_mode,
            "agent_mode": safe_get(mcp_cfg, "agent_mode", "react_train"),
            "agent_config": safe_get(mcp_cfg, "agent_config", {}),
            "formatter_type": safe_get(mcp_cfg, "formatter_type", "gpt_oss"),
            "mcp_servers": safe_get(mcp_cfg, "mcp_servers", []),
            "use_sample_servers": safe_get(mcp_cfg, "use_sample_servers", True),
            "mcp_transport": safe_get(mcp_cfg, "mcp_transport", "stdio"),
            "mcp_gateway_address": safe_get(mcp_cfg, "mcp_gateway_address", ""),
            "generator": {
                "num_trajectories": safe_get(mcp_cfg, "num_trajectories", 1),
                "val_num_trajectories": safe_get(mcp_cfg, "val_num_trajectories", 1),
                "max_iterations": safe_get(mcp_cfg, "max_iterations", 10),
            },
            "dispatcher": {
                "max_init_agents": safe_get(mcp_cfg, "max_init_agents", 32),
                "max_init_retries": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "max_init_retries", 3),
                "init_retry_delay": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "init_retry_delay", 5.0),
                "init_timeout": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "init_timeout", 300.0),
                "exec_timeout": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "exec_timeout", 300.0),
                "cleanup_timeout": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "cleanup_timeout", 30.0),
            },
            "env_pool": {
                "enabled": safe_get(env_pool_cfg, "enabled", False),
                "docker_host": safe_get(
                    env_pool_cfg, "docker_host",
                    os.environ.get("CPU_POD_DOCKER_HOST", "unix:///var/run/docker.sock"),
                ),
                "host": safe_get(env_pool_cfg, "host", os.environ.get("CPU_POD_HOST", "localhost")),
                "base_port": safe_get(env_pool_cfg, "base_port", 9000),
                "max_pool_size": safe_get(env_pool_cfg, "max_pool_size", 20),
                "startup_timeout": safe_get(env_pool_cfg, "startup_timeout", 180.0),
                "dockerfile_path": safe_get(env_pool_cfg, "dockerfile_path", ""),
                "build_context": safe_get(env_pool_cfg, "build_context", ""),
                "auto_build": safe_get(env_pool_cfg, "auto_build", True),
                "reuse_existing": safe_get(env_pool_cfg, "reuse_existing", True),
                "reset_on_release": safe_get(env_pool_cfg, "reset_on_release", False),
                # Env reuse policy (destroy / cache / trimmed_cache) + optional
                # ready-cache quotas. These MUST be plumbed through or the env
                # pool silently falls back to "cache" and per-task-image pools fill up.
                "reuse_policy": safe_get(env_pool_cfg, "reuse_policy", "cache"),
                "max_ready_envs": safe_get(env_pool_cfg, "max_ready_envs", 0),
                "max_ready_per_key": safe_get(env_pool_cfg, "max_ready_per_key", 0),
                # Provisioner backend switch (daemon-less apptainer worker) +
                # knobs. Default "docker" keeps existing behavior; "apptainer"
                # routes envs to the per-pod apptainer worker control server.
                "provisioner_backend": safe_get(env_pool_cfg, "provisioner_backend", "docker"),
                "apptainer_worker_port": safe_get(env_pool_cfg, "apptainer_worker_port", 8900),
                "apptainer_port_range": safe_get(env_pool_cfg, "apptainer_port_range", 200),
                "cpu_limit": safe_get(env_pool_cfg, "cpu_limit", "2"),
                "memory_limit": safe_get(env_pool_cfg, "memory_limit", "4g"),
                "gateway_mode": safe_get(env_pool_cfg, "gateway_mode", "sse"),
                "network": safe_get(env_pool_cfg, "network", "bridge"),
            },
        })

    def _init_llm(self):
        """Initialize LLMs using inference server addresses.

        Supports two modes:
        - text mode: Creates HTTP endpoint LLMs (OpenAI-compatible API)
        - token mode: Uses TITO (Token In Token Out) with direct server calls

        Both vLLM and SGLang expose OpenAI-compatible HTTP APIs for text mode,
        and return TokenOutput(token_ids, log_probs) for token mode.
        """
        if not self.server_addresses:
            raise RuntimeError("No inference server address available. "
                             "Ensure _initialize_llm_servers() ran successfully.")

        llm_type = self.mcp_config.llm_type
        llm_config_base = dict(self.mcp_config.llm_config) if self.mcp_config.llm_config else {}
        self._llm_config_base = llm_config_base

        # Save validation LLM config overrides (e.g. temperature=0.0 for greedy validation)
        mcp_cfg = self.config.get("mcp_agent", {})
        val_llm_cfg = mcp_cfg.get("val_llm_config", None)
        self._val_llm_config = dict(val_llm_cfg) if val_llm_cfg else {}

        if self.rollout_mode == "token":
            # TITO: TITOLLMWrapper created per trajectory in _run_mcp_rollout
            self.llms = []
            self._rollout_servers = getattr(self, 'rollout_replicas', [])
            if not self._rollout_servers:
                logger.warning("Token mode requested but no rollout_replicas found. "
                             "Falling back to HTTP mode with post-hoc tokenization.")
                self.rollout_mode = "text"
                self._init_llm_text_mode(llm_type, llm_config_base)
            else:
                logger.info(
                    f"TITO mode: Using {len(self._rollout_servers)} "
                    f"{self._rollout_backend} servers for token-level generation"
                )
        else:
            self._init_llm_text_mode(llm_type, llm_config_base)

    def _init_llm_text_mode(self, llm_type: str, llm_config_base: dict):
        """Initialize LLMs in text mode (one per server, round-robin)."""
        self.llms = []
        for addr in self.server_addresses:
            # OpenAI-compatible endpoint; base_url should NOT include /v1
            base_url = f"http://{addr}"
            llm_config = {
                **llm_config_base,
                "model_name": llm_config_base.get("model_name", self.model_name),
                "base_url": base_url,
                "api_key": llm_config_base.get("api_key", "token-abc123"),
            }
            llm = create_llm(llm_type, llm_config)
            self.llms.append(llm)
            logger.info(f"LLM ({llm_type}) initialized with {self._rollout_backend} endpoint: {base_url}")

        logger.info(f"Text mode: {len(self.llms)} LLM instances created")

    async def _init_env_pool(self, max_parallel: int) -> None:
        """Initialize Docker Env Pool for docker_pool transport.

        Creates the pool manager only; containers are provisioned on demand
        via ``acquire(config=...)`` with per-task EnvConfig (each task can
        specify its own Dockerfile). The pool is sized to a bounded prefetch
        window (~2 * max_parallel), not the whole batch.
        """
        await self._get_env_pool_runtime().initialize(max_parallel)

    # ------------------------------------------------------------------
    # Env pool: batch dockerfile helpers
    # ------------------------------------------------------------------

    def _collect_batch_env_specs(
        self, batch: List[Any]
    ) -> Dict[str, List[str]]:
        """Return ``{dockerfile_path: [server_names]}`` from *batch*.

        Groups instances by Dockerfile and collects the union of MCP server
        names so that pre-warmed containers start with the right servers.
        """
        return self._get_env_pool_runtime().collect_batch_env_specs(batch)

    def _build_env_configs(self, env_specs: Dict[str, List[str]]) -> list:
        """Build EnvConfig objects from ``{dockerfile_path: [server_names]}``."""
        return self._get_env_pool_runtime().build_env_configs(env_specs)

    # ------------------------------------------------------------------
    # Env pool: pre-warm / reconcile / release / cleanup
    # ------------------------------------------------------------------

    async def _prewarm_env_pool(
        self, batch: List[Any], max_parallel: int
    ) -> None:
        """Pre-warm Docker containers before trajectory execution.

        Provisions ``max_parallel`` containers in parallel so that all workers
        have a ready container when the dispatcher starts.

        Also cleans up stale MCP-managed containers from previous runs
        that may be holding ports but aren't tracked by the pool.
        """
        await self._get_env_pool_runtime().prewarm(batch, max_parallel)

    async def _cleanup_stale_containers(self) -> None:
        """Remove stale MCP-managed containers from previous training runs.

        Containers from previous runs aren't tracked by the current pool
        manager but still hold host ports, causing "port already allocated"
        errors.  This finds all ``mcp.managed=true`` containers on every
        Docker host and removes those not tracked by the pool.
        """
        await self._get_env_pool_runtime().cleanup_stale_containers()

    async def _reconcile_env_pool(
        self, batch: List[Any], max_parallel: int
    ) -> None:
        """Reconcile pool contents with what the new batch needs.

        1. Identify containers whose Dockerfile matches the new batch -> keep.
        2. Evict non-matching READY containers to free capacity.
        3. Provision new containers for any shortfall.
        """
        await self._get_env_pool_runtime().reconcile(batch, max_parallel)

    async def _release_env_pool(self) -> None:
        """Release all assigned environments back to the pool.

        Containers are reset (if ``reset_on_release`` is set) and put back
        into the ready queue for the next step.  The pool itself stays alive.
        """
        await self._get_env_pool_runtime().release_assigned()

    def _start_background_prewarm(
        self, batch: List[Any], max_parallel: int
    ) -> None:
        """Schedule pre-warm reconcile on the env-pool owner loop.

        Submits the reconcile coroutine to the persistent fallback loop
        (the loop that owns the ``EnvPoolManager``'s asyncio primitives) so
        it runs concurrently with the main thread's gradient update without
        violating loop ownership. See
        ``mcpuniverse.rl.core.env_pool_runtime.MCPEnvPoolRuntime.start_background_prewarm``
        for the underlying mechanics.
        """
        self._get_env_pool_runtime().start_background_prewarm(batch, max_parallel)

    async def _await_background_prewarm(self, timeout: float = 300.0) -> None:
        """Wait for the background pre-warm thread to finish."""
        await self._get_env_pool_runtime().await_background_prewarm(timeout)

    async def _cleanup_env_pool(self) -> None:
        """Destroy the entire pool.  Called on shutdown only."""
        await self._get_env_pool_runtime().cleanup()

    async def _acquire_env_for_trajectory(
        self,
        instance_id: Any,
        traj_id: int,
        dockerfile_path: str,
        server_names: List[str] = None,
        build_args: Dict[str, str] = None,
    ) -> str:
        """Acquire an environment from the pool for a trajectory.

        Each task can specify its own Dockerfile. The pool matches containers
        by dockerfile hash and reuses them when possible.

        Args:
            instance_id: Instance identifier
            traj_id: Trajectory identifier
            dockerfile_path: Path to the Dockerfile for this task
            server_names: MCP server names (optional)

        Returns:
            Gateway address for the acquired environment
        """
        return await self._get_env_pool_runtime().acquire(
            instance_id,
            traj_id,
            dockerfile_path,
            server_names,
            build_args=build_args,
        )

    async def _release_env_for_trajectory(self, instance_id: Any, traj_id: int) -> None:
        """Release an environment back to the pool.

        Args:
            instance_id: Instance identifier
            traj_id: Trajectory identifier
        """
        await self._get_env_pool_runtime().release(instance_id, traj_id)

    def _prepare_mcp_servers(self, instance: Dict[str, Any]) -> list:
        """Prepare MCP server configs with transport settings."""
        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        mcp_gateway_address = getattr(self.mcp_config, 'mcp_gateway_address', '')
        return prepare_mcp_servers_for_sample(
            instance,
            mcp_transport=mcp_transport,
            mcp_gateway_address=mcp_gateway_address,
            env_pool_active=self._env_pool_active,
        )

    @staticmethod
    def _prepare_evaluators(instance: Dict[str, Any]) -> list:
        """Parse evaluators from instance data."""
        evaluators_raw = instance.get("evaluators", [])
        if hasattr(evaluators_raw, 'tolist'):
            evaluators_raw = evaluators_raw.tolist()
        evaluators = []
        for ev in evaluators_raw:
            if isinstance(ev, dict):
                evaluators.append(Evaluator(ev))
            elif isinstance(ev, Evaluator):
                evaluators.append(ev)
        return evaluators

    @staticmethod
    def _build_setup_hook(instance: Dict[str, Any]):
        """Build a per-trajectory setup hook from a sample's ``prepares`` spec.

        Generic and opt-in: a sample may declare preparation steps as
        ``prepares: [{"prepare_func": <name>, "prepare_args": {...},
        "module": <import path, optional>}]``. Each runs after the env is
        acquired and before the agent starts (e.g. a stateful env's ``/setup``
        resets and seeds task state, writing task-specific variables into the
        trajectory context for the evaluator). Returns None when no prepares
        are declared, so stateless tasks are unaffected.
        """
        prepares_raw = instance.get("prepares", [])
        if hasattr(prepares_raw, "tolist"):
            prepares_raw = prepares_raw.tolist()
        specs = [p for p in prepares_raw if isinstance(p, dict) and p.get("prepare_func")]
        if not specs:
            return None

        async def _setup_hook(*, context, gateway_address, **_kwargs):
            import importlib
            # Lazy intra-package import; pylint cannot introspect the submodule here.
            from mcpuniverse.benchmark.prepares import PREPARE_FUNCTIONS  # pylint: disable=no-name-in-module
            for spec in specs:
                module = spec.get("module")
                if module:
                    importlib.import_module(module)  # register prepare_func on demand
                name = spec["prepare_func"]
                func = PREPARE_FUNCTIONS.get(name)
                if func is None:
                    raise ValueError(
                        f"Prepare function '{name}' is not registered. Declare its "
                        f"import path via the sample prepares spec 'module' field."
                    )
                args = dict(spec.get("prepare_args", {}))
                args.setdefault("gateway_address", gateway_address or "")
                await func(context=context, **args)

        return _setup_hook

    @staticmethod
    def _extract_server_from_replica(replica: Any) -> Any:
        """Extract the inference server handle from a veRL rollout replica.

        veRL does not expose a stable public API for this, so we probe known
        attribute conventions in priority order. Keep this helper centralised
        so the brittle interface is patched in exactly one place when veRL's
        replica internals shift.
        """
        if hasattr(replica, '_server_handle') and replica._server_handle is not None:  # noqa: SLF001
            return replica._server_handle  # noqa: SLF001
        if hasattr(replica, 'servers') and replica.servers:
            return replica.servers[0]
        logger.error(
            "Rollout replica has no server handle or servers list. "
            "Available attributes: {}", dir(replica)
        )
        raise RuntimeError(
            "Cannot find inference server in replica. "
            "TITO mode requires direct server access."
        )

    def _release_replica(self, replica_idx: int) -> None:
        """weakref.finalize callback (runs on whatever thread GC/refcount fires on).
        It ONLY enqueues the release; the decrement is applied later on the event-loop
        thread (drained in _create_llm_for_trajectory at the next assignment). It
        deliberately does NOT take _replica_lock or touch _replica_inflight, so it can
        never reentrantly deadlock if a GC fires inside a locked section."""
        self._replica_pending_release.append(replica_idx)

    def _create_llm_for_trajectory(self, val_mode: bool):
        """Create or select an LLM for a single trajectory.

        Returns the LLM instance (TITOLLMWrapper or HTTP LLM).
        """
        if (self.rollout_mode == "token"
                and hasattr(self, '_rollout_servers') and self._rollout_servers):
            # Heavyweight import (pulls vLLM); keep lazy so non-TITO callers
            # can import this module without paying the vLLM cost.
            from mcpuniverse.llm.tito import TITOLLMWrapper

            n = len(self._rollout_servers)
            # Least-loaded replica assignment (was round-robin _traj_counter % n).
            # Pick the replica with the fewest in-flight trajectories; ties -> lowest
            # index, which naturally round-robins when balanced (since the increment
            # below bumps the chosen replica before the next pick). Prevents
            # round-robin from piling long-tail trajectories onto one replica while
            # others idle. Sticky thereafter (the wrapper stays on this replica for
            # all turns -> prefix-cache reuse). The increment is deferred to AFTER the
            # wrapper is built (see below) so a failure here can't leak a phantom
            # count; this is safe because the method is synchronous (no await) and
            # thus runs atomically on the event loop.
            with self._replica_lock:
                if len(self._replica_inflight) != n:
                    self._replica_inflight = [0] * n
                # Apply deferred releases from finished trajectories (finalizers only
                # enqueue; we decrement here on the event-loop thread). popleft is a
                # thread-safe atomic op; no allocation -> can't trip a reentrant GC.
                while self._replica_pending_release:
                    done_idx = self._replica_pending_release.popleft()
                    if 0 <= done_idx < len(self._replica_inflight) and self._replica_inflight[done_idx] > 0:
                        self._replica_inflight[done_idx] -= 1
                replica_idx = min(range(n), key=lambda i: (self._replica_inflight[i], i))
            replica = self._rollout_servers[replica_idx]
            server = self._extract_server_from_replica(replica)

            sampling_params = {
                "temperature": self._llm_config_base.get("temperature", 1.0),
                "top_p": self._llm_config_base.get("top_p", 1.0),
                "max_tokens": self._llm_config_base.get("max_tokens", 4096),
                "model_name": self._llm_config_base.get(
                    "model_name", f"tito_{self._rollout_backend}"
                ),
            }
            # Request per-token rollout log-probs from the engine when the rollout
            # config asks for them. Without this the engine returns no log-probs and
            # the batch's rollout_log_probs are silently all-zero, which makes every
            # rollout_corr / rollout_probs_diff metric meaningless (rollout_ppl=1).
            if OmegaConf.select(
                self.config, "actor_rollout_ref.rollout.calculate_log_probs", default=False,
            ):
                sampling_params["logprobs"] = True
            if val_mode and self._val_llm_config:
                sampling_params.update(self._val_llm_config)

            max_ctx = OmegaConf.select(
                self.config, "actor_rollout_ref.rollout.max_model_len", default=0,
            )
            llm = TITOLLMWrapper(
                engine=server,
                tokenizer=self.tokenizer,
                sampling_params=sampling_params,
                max_context_length=max_ctx,
                # SGLang's HttpServer.generate signature is prompt_ids: torch.Tensor,
                # while vLLM's is prompt_ids: list[int]. Pass the backend name so
                # the wrapper can convert the per-turn token_ids list to a tensor
                # before forwarding to a SGLang Ray actor. See TITOLLMWrapper.__init__.
                backend=self._rollout_backend,
            )
            # Now that the wrapper exists, mark this replica busy (+1) and arrange the
            # matching -1 for when the trajectory finishes and drops the wrapper
            # (ref drop / GC -> finalize). Incrementing only after successful creation
            # means an exception above (e.g. _extract_server_from_replica raising)
            # cannot leak a phantom in-flight count.
            with self._replica_lock:
                self._replica_inflight[replica_idx] += 1
            weakref.finalize(llm, self._release_replica, replica_idx)
        else:
            llm_idx = self._traj_counter % len(self.llms)
            llm = self.llms[llm_idx]

        self._traj_counter += 1
        return llm

    def _build_env_callbacks(self, instance_id, traj_id, instance, mcp_servers):
        """Build acquire/release env callbacks for docker_pool transport."""
        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        if mcp_transport != 'docker_pool' or not self._env_pool_active:
            return None, None

        dockerfile_path = instance.get("dockerfile_path", "")
        srv_names = [
            srv.get('name') if isinstance(srv, dict) else srv
            for srv in mcp_servers
        ]
        # Per-task docker build args (e.g. a per-task BASE_IMAGE = the task's
        # prebuilt image) so one Dockerfile wraps any task's base. Empty for
        # single-image envs, so they're unaffected.
        build_args = instance.get("build_args") or {}
        if hasattr(build_args, "items"):
            build_args = {str(k): str(v) for k, v in build_args.items()}
        else:
            build_args = {}
        _iid, _tid, _dp, _sn, _ba = instance_id, traj_id, dockerfile_path, srv_names, build_args

        async def _acquire(_iid=_iid, _tid=_tid, _dp=_dp, _sn=_sn, _ba=_ba):
            return await self._acquire_env_for_trajectory(_iid, _tid, _dp, _sn, build_args=_ba)

        async def _release(_iid=_iid, _tid=_tid):
            await self._release_env_for_trajectory(_iid, _tid)

        return _acquire, _release

    def _tokenize_result(self, traj, instance_id, traj_id):
        """veRL-side tokenize callback: delegates to the framework-neutral
        helper and adds verL-specific instrumentation on top.
        """
        is_tito = self.rollout_mode == "token" and traj.get_tito_tokens() is not None
        if not is_tito:
            trace_text = traj.get_trace_text()
            logger.info(
                f"[Trajectory] instance={instance_id}, traj={traj_id}, "
                f"words={len(trace_text.split())}, chars={len(trace_text)}"
            )

        prompt_tokens, response_tokens, loss_mask = tokenize_trajectory_result(
            traj,
            tokenizer=self.tokenizer,
            formatter=getattr(self, "formatter", None),
            rollout_mode=self.rollout_mode,
        )

        if is_tito:
            logger.info(
                f"[TITO] instance={instance_id}, traj={traj_id}, "
                f"prompt_tokens={len(prompt_tokens)}, "
                f"response_tokens={len(response_tokens)}, "
                f"trainable_tokens={sum(loss_mask)}"
            )
        else:
            logger.info(
                f"[Tokens] instance={instance_id}, traj={traj_id}, "
                f"prompt={len(prompt_tokens)}, response={len(response_tokens)}, "
                f"total={len(prompt_tokens) + len(response_tokens)}"
            )

        return prompt_tokens, response_tokens, loss_mask

    async def _run_mcp_rollout(
        self,
        samples: List[Any],
        val_mode: bool = False,
        data_proto_sink: Optional[Any] = None,
    ) -> TokenizedRolloutBatch:
        """Run MCP agent rollout using MCPTrajectory.

        When *data_proto_sink* is provided (streaming mode), each instance is
        converted to a DataProto and handed to ``data_proto_sink(instance_id,
        DataProto)`` the moment its trajectories finish - so the caller can push
        it downstream immediately instead of waiting for the whole batch. The
        full TokenizedRolloutBatch is still returned (for metrics/logging).
        """
        num_trajectories = self.val_num_trajectories if val_mode else self.num_trajectories
        dispatcher_cfg = build_rollout_dispatcher_config(
            self.mcp_config.dispatcher,
            num_instances=len(samples),
            num_trajectories=num_trajectories,
            include_init_timeout=True,
        )

        instance_sink = None
        if data_proto_sink is not None:
            async def _instance_sink(instance_id, inst_tokenized):
                # Per-instance tokenized batch -> per-instance DataProto(s).
                for data_proto in self._postprocess_per_instance(
                    inst_tokenized, val_mode=val_mode,
                ):
                    await data_proto_sink(instance_id, data_proto)
            instance_sink = _instance_sink

        tokenized = await run_tokenized_rollout_batch(
            samples,
            dispatcher_cfg=dispatcher_cfg,
            num_trajectories=num_trajectories,
            mcp_manager=self.mcp_manager,
            agent_mode=self.mcp_config.agent_mode,
            max_iterations=self.max_iterations,
            formatter_type=self.formatter_type,
            rollout_mode=self.rollout_mode,
            agent_config=self.mcp_config.agent_config,
            val_mode=val_mode,
            tokenizer=self.tokenizer,
            trace_logger=self._trace_logger,
            get_mcp_servers=self._prepare_mcp_servers,
            get_evaluators=self._prepare_evaluators,
            get_setup_hook=self._build_setup_hook,
            create_llm_for_trajectory=self._create_llm_for_trajectory,
            build_env_callbacks=self._build_env_callbacks,
            attach_tito_llm=True,
            tokenize_trajectory_fn=self._tokenize_result,
            instance_sink=instance_sink,
        )

        return self._finalize_tokenized_rollout(tokenized, samples, num_trajectories)

    def build_trajectories_for_instances(self, samples: List[Any], val_mode: bool = False):
        """Build (not dispatch) trajectories for the continuous pipeline.

        Returns ``(trajectories_dict, num_trajectories)`` where trajectories_dict
        is ``{instance_id: {traj_id: Trajectory}}``. The continuous driver
        submits these into ``RolloutPipeline`` instead of running a batch
        dispatcher.
        """
        from mcpuniverse.rl.core.rollout import build_rollout_trajectories  # local import to avoid cycle
        num_trajectories = self.val_num_trajectories if val_mode else self.num_trajectories
        trajectories = build_rollout_trajectories(
            samples,
            num_trajectories=num_trajectories,
            mcp_manager=self.mcp_manager,
            agent_mode=self.mcp_config.agent_mode,
            max_iterations=self.max_iterations,
            formatter_type=self.formatter_type,
            rollout_mode=self.rollout_mode,
            agent_config=self.mcp_config.agent_config,
            val_mode=val_mode,
            tokenizer=self.tokenizer,
            trace_logger=self._trace_logger,
            get_mcp_servers=self._prepare_mcp_servers,
            get_evaluators=self._prepare_evaluators,
            get_setup_hook=self._build_setup_hook,
            create_llm_for_trajectory=self._create_llm_for_trajectory,
            build_env_callbacks=self._build_env_callbacks,
            attach_tito_llm=True,
        )
        return trajectories, num_trajectories

    def build_instance_dataproto(
        self, instance_id: Any, trajs: dict, num_trajectories: int, val_mode: bool = False,
    ) -> list:
        """Tokenize + postprocess one finished instance into DataProto(s)."""
        from mcpuniverse.rl.core.postprocess import collect_tokenized_rollout_results  # local import
        tokenized = collect_tokenized_rollout_results(
            {instance_id: trajs},
            [None],
            num_trajectories,
            tokenizer=self.tokenizer,
            rollout_mode=self.rollout_mode,
            tokenize_trajectory_fn=self._tokenize_result,
        )
        return self._postprocess_per_instance(tokenized, val_mode=val_mode)

    def _finalize_tokenized_rollout(
        self, tokenized: TokenizedRolloutBatch, batch: list, num_trajectories: int,
    ) -> TokenizedRolloutBatch:
        """Strip private collection details and log rollout collection summary."""
        private_metrics = pop_private_rollout_metrics(tokenized.metrics)
        rollout_metrics = tokenized.metrics
        missing_results = private_metrics.get("missing_results", [])

        if missing_results:
            logger.warning(
                f"Missing results for {len(missing_results)} trajectories: "
                f"{missing_results[:20]}{'...' if len(missing_results) > 20 else ''}"
            )

        logger.info(
            f"Rollout complete: {rollout_metrics['num_collected']}/"
            f"{rollout_metrics['num_trajectories']} sequences collected "
            f"from {len(batch)} instances * {num_trajectories} trajectories"
        )
        if rollout_metrics["num_collected"] == 0:
            logger.warning("No valid trajectories collected!")

        return tokenized

    def _postprocess(self, tokenized_batch: TokenizedRolloutBatch) -> DataProto:
        """Postprocess a neutral tokenized rollout batch to VERL DataProto."""
        return tokenized_rollout_batch_to_data_proto(
            tokenized_batch,
            config=self.config,
            tokenizer=self.tokenizer,
            num_trajectories=getattr(self, "num_trajectories", 1),
        )

    def _postprocess_per_instance(
        self,
        output: TokenizedRolloutBatch,
        *,
        val_mode: bool = False,
    ) -> List[DataProto]:
        """Split one rollout result into per-instance postprocessed DataProtos.

        Groups trajectories by ``instance_id`` (or ``group_ids`` if set), then
        runs the standard ``_postprocess`` on each subgroup. Used by the
        fully-async rollouter which needs per-instance granularity for queue
        sizing and dynamic padding.
        """
        if not output.prompt_ids or not output.response_ids:
            return []

        num_trajectories = (
            self.val_num_trajectories if val_mode else self.num_trajectories
        )
        num_trajectories = max(1, int(num_trajectories or 1))

        grouped: Dict[str, TokenizedRolloutBatch] = {}
        for idx, (prompt_ids, response_ids, response_mask, reward) in enumerate(
            zip(
                output.prompt_ids,
                output.response_ids,
                output.response_mask,
                output.rewards,
            )
        ):
            traj = (
                output.trajectories[idx]
                if idx < len(output.trajectories) and isinstance(output.trajectories[idx], dict)
                else {}
            )
            if idx < len(output.group_ids):
                instance_id = str(output.group_ids[idx])
            else:
                instance_id = str(traj.get("instance_id", f"instance_{idx // num_trajectories}"))
            traj = dict(traj)
            traj.setdefault("instance_id", instance_id)

            instance_output = grouped.get(instance_id)
            if instance_output is None:
                instance_output = TokenizedRolloutBatch()
                grouped[instance_id] = instance_output

            instance_output.prompt_ids.append(prompt_ids)
            instance_output.response_ids.append(response_ids)
            instance_output.response_mask.append(response_mask)
            # Carry per-token rollout log-probs through the per-instance regroup
            # (needed for TIS / bypass mode). Missing here was dropping them so
            # rollout_log_probs never reached the training batch -> the
            # "bypass_mode=True requires rollout_log_probs" crash.
            if idx < len(output.response_logprobs):
                instance_output.response_logprobs.append(output.response_logprobs[idx])
            else:
                instance_output.response_logprobs.append([0.0] * len(response_ids))
            if idx < len(output.routed_experts):
                instance_output.routed_experts.append(output.routed_experts[idx])
            else:
                instance_output.routed_experts.append(None)
            instance_output.rewards.append(reward)
            instance_output.group_ids.append(instance_id)
            instance_output.trajectories.append(traj)

        data_protos: List[DataProto] = []
        for instance_id, instance_output in grouped.items():
            total_reward = float(sum(instance_output.rewards))
            success_count = sum(1 for reward in instance_output.rewards if reward > 0)
            num_collected = len(instance_output.rewards)
            expected = num_trajectories
            instance_output.metrics = {
                "num_instances": 1,
                "num_trajectories": expected,
                "num_collected": num_collected,
                "num_missing": max(0, expected - num_collected),
                "total_reward": total_reward,
                "success_count": success_count,
                "mean_reward": total_reward / max(num_collected, 1),
                "success_rate": success_count / max(num_collected, 1),
            }
            data_protos.append(self._postprocess(instance_output))

        logger.info(
            "Per-instance postprocess produced {} DataProtos from {} trajectories",
            len(data_protos), len(output.rewards),
        )
        return data_protos

    def ensure_env_pool(self, batch: List[Any], max_parallel: int) -> None:
        """Initialize and pre-warm Docker env pool (call once before concurrent use).

        For fully async mode: call this once during startup, then call
        ``generate_sequences(prompts, manage_pool=False)`` per instance so
        that threads don't fight over pool lifecycle.
        """
        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        if mcp_transport != 'docker_pool':
            return
        env_pool_cfg = getattr(self.mcp_config, 'env_pool', None)
        if not env_pool_cfg or not safe_get(env_pool_cfg, 'enabled', False):
            return
        if not self._env_pool_active:
            self._run_async_safely(self._init_env_pool(max_parallel))
            self._run_async_safely(self._prewarm_env_pool(batch, max_parallel))

    def generate_sequences(
        self,
        prompts: DataProto,
        manage_pool: bool = True,
        per_instance: bool = False,
    ) -> DataProto:
        """Generate trajectories for a batch of prompts.

        Args:
            prompts: DataProto containing instances to rollout.
            manage_pool: Whether to manage Docker env pool lifecycle
                (init/reconcile/release/prewarm) around the rollout.
                Set to ``False`` for fully async mode where the pool is
                initialized once via ``ensure_env_pool()`` and containers
                are acquired/released per-trajectory inside the dispatcher.

        Docker Env Pool lifecycle (when ``manage_pool=True``):

        Step 1 (first call):
          - Create pool -> pre-warm ``max_parallel`` containers -> rollout
          - After rollout: release containers back to pool (keep alive)
          - Schedule background pre-warm for next step

        Step N (subsequent calls):
          - Wait for background pre-warm (started during previous gradient update)
          - Reconcile pool: reuse matching containers, evict non-matching
          - Rollout with warm containers (near-instant acquire)
          - Release containers -> schedule background pre-warm -> return
        """

        # Weight sync (FSDP -> inference server) is managed externally by the trainer
        # via CheckpointEngineManager.update_weights() / sleep_replicas().

        sample_batch = self._parse_input_batch(prompts)
        val_mode = prompts.meta_info.get("val_mode", False)

        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        use_docker_pool = False

        if manage_pool and mcp_transport == 'docker_pool':
            env_pool_cfg = getattr(self.mcp_config, 'env_pool', None)
            if env_pool_cfg and safe_get(env_pool_cfg, 'enabled', False):
                use_docker_pool = True
                max_parallel = self.mcp_config.dispatcher.max_init_agents

                logger.info("Using docker_pool transport (per-task dockerfile)")
                logger.info(f"  Max parallel agents: {max_parallel}")

                if self._is_async_mode:
                    if not self._env_pool_active:
                        self._run_async_safely(self._init_env_pool(max_parallel))
                    self._run_async_safely(self._reconcile_env_pool(sample_batch, max_parallel))
                elif not self._env_pool_active:
                    # First step: create pool + pre-warm
                    self._run_async_safely(self._init_env_pool(max_parallel))
                    self._run_async_safely(self._prewarm_env_pool(sample_batch, max_parallel))
                else:
                    # Subsequent steps: wait for background pre-warm, then reconcile
                    self._run_async_safely(self._await_background_prewarm())
                    self._run_async_safely(self._reconcile_env_pool(sample_batch, max_parallel))
            else:
                logger.warning("docker_pool transport requested but env_pool not enabled in config")

        try:
            output = self._run_async_safely(self._run_mcp_rollout(sample_batch, val_mode))
            if per_instance:
                result = self._postprocess_per_instance(output, val_mode=val_mode)
            else:
                result = self._postprocess(output)
        finally:
            if use_docker_pool and not self._is_async_mode:
                # Release containers back to pool (not destroy) and start
                # background pre-warm that runs during gradient update
                self._run_async_safely(self._release_env_pool())
                self._start_background_prewarm(sample_batch, max_parallel)

        self._trigger_periodic_cleanup()

        return result

    def _trigger_periodic_cleanup(self):
        """Trigger periodic cleanup to prevent resource exhaustion.

        In continuous rollout modes, zombie MCP processes may accumulate over time.
        """
        self._step_counter += 1

        mcp_cfg = self.config.get('mcp_agent', {}) if hasattr(self.config, 'get') else {}
        cleanup_interval = mcp_cfg.get('cleanup_interval', 50) if hasattr(mcp_cfg, 'get') else 50
        if self._step_counter % cleanup_interval == 0:
            logger.info(f"Triggering periodic cleanup at step {self._step_counter}")
            gc.collect()

            # Kill orphaned stdio MCP server processes that weren't properly cleaned up
            mcp_server_patterns = mcp_cfg.get("cleanup_process_patterns", [])
            for pattern in mcp_server_patterns:
                try:
                    subprocess.run(
                        ["pkill", "-f", pattern, "-9"],
                        capture_output=True, timeout=5, check=False,
                    )
                except Exception as e:
                    logger.debug(f"Cleanup subprocess failed (safe to ignore): {e}")

            if mcp_server_patterns:
                logger.info(f"Cleaned up zombie MCP server processes ({len(mcp_server_patterns)} patterns)")

    @classmethod
    def _get_fallback_loop(cls) -> asyncio.AbstractEventLoop:
        """Return the shared persistent fallback event loop.

        Thin facade over ``async_bridge.get_fallback_loop`` so tests
        can monkeypatch this method on the class while production code
        keeps using the single process-wide loop.
        """
        return get_fallback_loop()

    def _run_async_safely(self, coro):
        """Run async coroutine safely from any thread context.

        Thin facade over ``async_bridge.run_async_safely``. Routes via
        ``_get_fallback_loop`` so subclasses / tests that override the
        loop selection are honoured.
        """
        return run_async_safely(coro, loop_factory=self._get_fallback_loop)

    def _parse_input_batch(self, prompts: DataProto) -> List[RolloutSample]:
        """Parse DataProto into neutral rollout samples."""
        return data_proto_to_rollout_samples(prompts)

    def _run_all(self, tasks: list):
        """Run async tasks synchronously."""
        async def run_all():
            await asyncio.gather(*tasks)
        self._run_async_safely(run_all())
