"""
MCP Loop Manager for VERL integration.

Manages async agent rollout with MCP-Universe and VERL's inference backend
(supports both vLLM and SGLang, selected by ``actor_rollout_ref.rollout.name``).
"""
# pylint: disable=too-many-lines,broad-exception-caught,protected-access
# pylint: disable=import-outside-toplevel,attribute-defined-outside-init

import asyncio
import json
import os
import threading
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from omegaconf import DictConfig, OmegaConf
from tensordict import TensorDict
from loguru import logger

from verl.protocol import DataProto
from verl.single_controller.ray.base import RayWorkerGroup
from verl.utils.fs import copy_to_local
from verl.utils import hf_tokenizer
from verl.experimental.agent_loop.agent_loop import AgentLoopManager

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.rl.config import RolloutConfig, TrajectoryConfig
from mcpuniverse.rl.trace_logger import TrajectoryTraceLogger
from mcpuniverse.rl.trajectory import create_trajectory, create_llm
from mcpuniverse.rl.dispatcher import get_dispatcher
from mcpuniverse.rl.formatters import get_formatter
from mcpuniverse.evaluator.evaluator import Evaluator
from mcpuniverse.mcp.env_pool import EnvPoolManager, EnvConfig
from mcpuniverse.mcp.env_pool.base import EnvStatus
from mcpuniverse.mcp.env_pool.docker import DockerProvisioner

from .mcp_backend import MCPGeneratorOutput
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

        # Docker Env Pool state
        self._env_pool: EnvPoolManager = None
        self._env_assignments: Dict[str, str] = {}
        self._step_counter = 0
        self._traj_counter = 0  # persistent round-robin index for LLM/replica assignment
        self._prewarm_thread: Optional[threading.Thread] = None  # background pre-warm thread

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
        self._init_llm()

        logger.info(f"MCPLoopManager initialized with model: {self.model_name}")
        logger.info(f"  Mode: {'Fully Async' if self._is_async_mode else 'Hybrid'}")
        logger.info(f"  Backend: {self._rollout_backend}")
        logger.info(f"  Inference servers: {self.server_addresses}")
        logger.info(f"  Using formatter: {self.formatter_type}")

    def __del__(self):
        """Cleanup pool on garbage collection."""
        if self._env_pool is not None:
            try:
                self._run_async_safely(self._cleanup_env_pool())
            except Exception:
                pass

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
                "max_parallel_agents": safe_get(mcp_cfg, "max_parallel_agents", 32),
                "max_init_retries": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "max_init_retries", 3),
                "init_retry_delay": safe_get(safe_get(mcp_cfg, "dispatcher", {}), "init_retry_delay", 5.0),
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
                "cpu_limit": safe_get(env_pool_cfg, "cpu_limit", "2"),
                "memory_limit": safe_get(env_pool_cfg, "memory_limit", "4g"),
                "gateway_mode": safe_get(env_pool_cfg, "gateway_mode", "sse"),
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
        specify its own Dockerfile).

        Args:
            max_parallel: Maximum number of parallel agents (determines pool size)
        """
        env_pool_cfg = getattr(self.mcp_config, 'env_pool', None)
        if not env_pool_cfg or not safe_get(env_pool_cfg, 'enabled', False):
            logger.warning("Env pool not enabled in config, skipping initialization")
            return

        if self._env_pool is not None:
            logger.info("Cleaning up existing env pool before creating new one")
            await self._cleanup_env_pool()

        logger.info("Initializing Docker Env Pool (per-task dockerfile mode)")
        logger.info(f"  Docker host: {safe_get(env_pool_cfg, 'docker_host')}")
        logger.info(f"  Gateway host: {safe_get(env_pool_cfg, 'host')}")
        logger.info(f"  Max pool size: {max_parallel + 5}")

        # Create DockerProvisioner(s)
        docker_hosts = safe_get(env_pool_cfg, 'docker_hosts', [])

        # Also discover hosts from CPU_POD_DOCKER_HOST[_N] env vars (like benchmark)
        if not docker_hosts:
            dh = os.environ.get("CPU_POD_DOCKER_HOST")
            if dh:
                docker_hosts.append({
                    "docker_host": dh,
                    "host": os.environ.get("CPU_POD_HOST", "localhost"),
                })
                for i in range(2, 20):
                    dh_i = os.environ.get(f"CPU_POD_DOCKER_HOST_{i}")
                    if not dh_i:
                        break
                    docker_hosts.append({
                        "docker_host": dh_i,
                        "host": os.environ.get(f"CPU_POD_HOST_{i}", "localhost"),
                    })

        # build_context lives inside env_pool.build (DockerBuildConfig)
        build_cfg = getattr(env_pool_cfg, 'build', None)
        build_context = (
            safe_get(build_cfg, 'build_context', '.')
            if build_cfg
            else safe_get(env_pool_cfg, 'build_context', '.')
        )

        auto_build = (
            safe_get(build_cfg, 'auto_build', True)
            if build_cfg
            else safe_get(env_pool_cfg, 'auto_build', True)
        )
        common_kwargs = {
            "base_port": safe_get(env_pool_cfg, 'base_port', 9000),
            "startup_timeout": safe_get(env_pool_cfg, 'startup_timeout', 180.0),
            "auto_build": auto_build,
            "build_context": build_context,
        }

        if docker_hosts:
            provisioners = []
            for host_cfg in docker_hosts:
                p = DockerProvisioner(
                    docker_host=host_cfg.get('docker_host'),
                    host=host_cfg.get('host', 'localhost'),
                    **common_kwargs,
                )
                provisioners.append(p)
                logger.info(f"  Added Docker host: {host_cfg.get('docker_host')} "
                           f"(gateway: {host_cfg.get('host')})")
            provisioner = provisioners[0]
        else:
            provisioner = DockerProvisioner(
                docker_host=safe_get(env_pool_cfg, 'docker_host'),
                host=safe_get(env_pool_cfg, 'host'),
                **common_kwargs,
            )
            provisioners = None

        self._env_pool = EnvPoolManager(
            provisioner=provisioner,
            provisioners=provisioners,
            max_pool_size=max_parallel + 5,
            reset_on_release=safe_get(env_pool_cfg, 'reset_on_release', True),
            acquisition_timeout=120.0,
            auto_scale=True,
        )

        logger.info("Env Pool manager created (containers will be provisioned on demand)")

    # ------------------------------------------------------------------
    # Env pool: batch dockerfile helpers
    # ------------------------------------------------------------------

    def _collect_batch_env_specs(
        self, batch: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """Return ``{dockerfile_path: [server_names]}`` from *batch*.

        Groups instances by Dockerfile and collects the union of MCP server
        names so that pre-warmed containers start with the right servers.
        """
        specs: Dict[str, List[str]] = {}
        for instance in batch:
            dp = instance.get("dockerfile_path", "")
            if not dp:
                continue
            mcp_servers = instance.get("mcp_servers", [])
            if hasattr(mcp_servers, 'tolist'):
                mcp_servers = mcp_servers.tolist()
            srv_names = [
                srv.get('name') if isinstance(srv, dict) else srv
                for srv in mcp_servers
            ]
            if dp not in specs:
                specs[dp] = list(srv_names)
            else:
                # Union of server names across instances with same Dockerfile
                existing = set(specs[dp])
                for s in srv_names:
                    if s not in existing:
                        specs[dp].append(s)
                        existing.add(s)
        return specs

    def _build_env_configs(self, env_specs: Dict[str, List[str]]) -> List[EnvConfig]:
        """Build EnvConfig objects from ``{dockerfile_path: [server_names]}``."""
        env_pool_cfg = getattr(self.mcp_config, 'env_pool', {})
        configs = []
        for dp, srv_names in env_specs.items():
            configs.append(EnvConfig(
                servers=srv_names,
                dockerfile_path=dp,
                cpu_limit=safe_get(env_pool_cfg, 'cpu_limit', '2'),
                memory_limit=safe_get(env_pool_cfg, 'memory_limit', '4g'),
                gateway_mode=safe_get(env_pool_cfg, 'gateway_mode', 'sse'),
                use_dockerfile_cmd=safe_get(env_pool_cfg, 'use_dockerfile_cmd', False),
            ))
        return configs

    # ------------------------------------------------------------------
    # Env pool: pre-warm / reconcile / release / cleanup
    # ------------------------------------------------------------------

    async def _prewarm_env_pool(
        self, batch: List[Dict[str, Any]], max_parallel: int
    ) -> None:
        """Pre-warm Docker containers before trajectory execution.

        Provisions ``max_parallel`` containers in parallel so that all workers
        have a ready container when the dispatcher starts.

        Also cleans up stale MCP-managed containers from previous runs
        that may be holding ports but aren't tracked by the pool.
        """
        if self._env_pool is None:
            return

        # Clean up stale containers from previous runs before provisioning.
        # These containers hold ports but aren't tracked by the pool manager,
        # causing "port already allocated" errors on new container creation.
        await self._cleanup_stale_containers()

        env_specs = self._collect_batch_env_specs(batch)
        if not env_specs:
            logger.info("No dockerfile_path in batch, skipping pre-warm")
            return

        configs = self._build_env_configs(env_specs)
        per_config = max(1, max_parallel // len(configs))
        total_prewarm = min(max_parallel, self._env_pool.max_pool_size)

        logger.info(
            f"Pre-warming env pool: {total_prewarm} containers "
            f"({len(configs)} unique Dockerfiles, {per_config} each)"
        )

        for cfg in configs:
            n = min(per_config, total_prewarm)
            if n <= 0:
                break
            try:
                envs = await self._env_pool.provision(
                    num_envs=n, config=cfg, parallel=True,
                )
                logger.info(
                    f"Pre-warmed {len(envs)} containers for "
                    f"dockerfile={cfg.dockerfile_path}"
                )
                total_prewarm -= len(envs)
            except Exception as e:
                logger.warning(f"Pre-warm failed for {cfg.dockerfile_path}: {e}")

        logger.info(
            f"Pre-warm complete. Pool: {self._env_pool._stats.ready_envs} ready, "
            f"{self._env_pool._stats.total_envs} total"
        )

    async def _cleanup_stale_containers(self) -> None:
        """Remove stale MCP-managed containers from previous training runs.

        Containers from previous runs aren't tracked by the current pool
        manager but still hold host ports, causing "port already allocated"
        errors.  This finds all ``mcp.managed=true`` containers on every
        Docker host and removes those not tracked by the pool.
        """
        if self._env_pool is None:
            return

        tracked_ids = set(self._env_pool._envs.keys())
        total_removed = 0

        for provisioner in self._env_pool._provisioners:
            if not hasattr(provisioner, 'docker_host'):
                continue
            try:
                result = await provisioner._run_docker_cmd(
                    ["ps", "-a", "--filter", "label=mcp.managed=true",
                     "--format", "{{.Names}}\t{{.Status}}"],
                    check=False,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    continue

                for line in result.stdout.strip().split('\n'):
                    parts = line.split('\t')
                    name = parts[0].strip()
                    if not name.startswith("mcp-env-"):
                        continue
                    env_id = name[len("mcp-env-"):]
                    if env_id in tracked_ids:
                        continue  # tracked by current pool, keep it

                    # Stale container — remove it
                    logger.info(
                        "Removing stale container {} from {} (not tracked by pool)",
                        name, provisioner.docker_host or "local",
                    )
                    await provisioner._run_docker_cmd(
                        ["rm", "-f", name], check=False,
                    )
                    total_removed += 1
            except Exception as e:
                logger.warning(
                    "Failed to cleanup stale containers on {}: {}",
                    getattr(provisioner, 'docker_host', 'local'), e,
                )

        if total_removed:
            logger.info("Cleaned up {} stale containers", total_removed)

    async def _reconcile_env_pool(
        self, batch: List[Dict[str, Any]], max_parallel: int
    ) -> None:
        """Reconcile pool contents with what the new batch needs.

        1. Identify containers whose Dockerfile matches the new batch → keep.
        2. Evict non-matching READY containers to free capacity.
        3. Provision new containers for any shortfall.
        """
        if self._env_pool is None:
            return

        env_specs = self._collect_batch_env_specs(batch)
        if not env_specs:
            return

        needed_dockerfiles = set(env_specs.keys())

        # Classify existing containers
        all_envs = self._env_pool.get_all_envs()
        matching = 0
        non_matching_ids: List[str] = []

        for env_info in all_envs:
            if env_info.status == EnvStatus.TERMINATED:
                continue
            if (env_info.config
                    and env_info.config.dockerfile_path in needed_dockerfiles):
                matching += 1
            else:
                # Only evict READY containers (not IN_USE)
                if env_info.status == EnvStatus.READY:
                    non_matching_ids.append(env_info.env_id)

        logger.info(
            f"Pool reconciliation: {matching} matching, "
            f"{len(non_matching_ids)} non-matching READY containers"
        )

        # Evict non-matching containers to free capacity for new ones
        want = min(max_parallel, self._env_pool.max_pool_size)
        to_evict = max(0, (matching + len(non_matching_ids)) - want)
        # Also evict enough to make room for shortfall
        shortfall = max(0, want - matching)
        to_evict = max(to_evict, min(shortfall, len(non_matching_ids)))

        evicted = 0
        for env_id in non_matching_ids[:to_evict]:
            try:
                await self._env_pool.destroy(env_id)
                evicted += 1
            except Exception as e:
                logger.warning(f"Failed to evict {env_id}: {e}")

        if evicted:
            logger.info(f"Evicted {evicted} non-matching containers")

        # Provision new containers for the shortfall
        need_new = max(0, want - matching)
        if need_new > 0:
            configs = self._build_env_configs(env_specs)
            per_config = max(1, need_new // len(configs))
            remaining = need_new
            for cfg in configs:
                n = min(per_config, remaining)
                if n <= 0:
                    break
                try:
                    envs = await self._env_pool.provision(
                        num_envs=n, config=cfg, parallel=True,
                    )
                    remaining -= len(envs)
                    logger.info(
                        f"Provisioned {len(envs)} containers for "
                        f"dockerfile={cfg.dockerfile_path}"
                    )
                except Exception as e:
                    logger.warning(f"Provision failed for {cfg.dockerfile_path}: {e}")
        else:
            logger.info(
                f"Pool already has {matching} matching containers, "
                f"no additional provisioning needed"
            )

        logger.info(
            f"Reconciliation done. Pool: "
            f"{self._env_pool._stats.ready_envs} ready, "
            f"{self._env_pool._stats.total_envs} total"
        )

    async def _release_env_pool(self) -> None:
        """Release all assigned environments back to the pool.

        Containers are reset (if ``reset_on_release`` is set) and put back
        into the ready queue for the next step.  The pool itself stays alive.
        """
        if self._env_pool is None:
            return

        released = 0
        for _, env_id in list(self._env_assignments.items()):
            try:
                await self._env_pool.release(env_id)
                released += 1
            except Exception as e:
                logger.warning(f"Failed to release env {env_id}: {e}")
        self._env_assignments = {}

        logger.info(
            f"Released {released} environments. Pool: "
            f"{self._env_pool._stats.ready_envs} ready, "
            f"{self._env_pool._stats.total_envs} total"
        )

    def _start_background_prewarm(
        self, batch: List[Dict[str, Any]], max_parallel: int
    ) -> None:
        """Run pre-warming in a background thread.

        Creates a new event loop in a daemon thread so the pre-warm runs
        concurrently with the main thread's gradient update.
        """
        if self._env_pool is None:
            return

        # Wait for previous pre-warm thread if still running
        if self._prewarm_thread and self._prewarm_thread.is_alive():
            logger.info("Previous pre-warm still running, waiting...")
            self._prewarm_thread.join(timeout=60)

        def _bg():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._reconcile_env_pool(batch, max_parallel))
                loop.close()
            except Exception as e:
                logger.warning(f"Background pre-warm failed: {e}")

        self._prewarm_thread = threading.Thread(target=_bg, daemon=True)
        self._prewarm_thread.start()
        logger.info("Background pre-warm started in thread (runs during gradient update)")

    async def _await_background_prewarm(self, timeout: float = 300.0) -> None:
        """Wait for the background pre-warm thread to finish."""
        if self._prewarm_thread is None or not self._prewarm_thread.is_alive():
            self._prewarm_thread = None
            return
        logger.info("Waiting for background pre-warm thread to complete...")
        # Use asyncio.to_thread to avoid blocking the event loop
        await asyncio.to_thread(self._prewarm_thread.join, timeout)
        if self._prewarm_thread.is_alive():
            logger.warning(
                f"Background pre-warm timed out after {timeout}s, "
                f"proceeding with available containers"
            )
        else:
            logger.info("Background pre-warm completed")
        self._prewarm_thread = None

    async def _cleanup_env_pool(self) -> None:
        """Destroy the entire pool.  Called on shutdown only."""
        if self._prewarm_thread and self._prewarm_thread.is_alive():
            self._prewarm_thread.join(timeout=10)
        self._prewarm_thread = None

        if self._env_pool is None:
            return

        logger.info("Cleaning up Docker Env Pool (full destroy)...")

        for _, env_id in list(self._env_assignments.items()):
            try:
                await self._env_pool.release(env_id)
            except Exception as e:
                logger.warning(f"Failed to release env {env_id}: {e}")
        self._env_assignments = {}

        await self._env_pool.cleanup()
        self._env_pool = None
        logger.info("Env Pool cleaned up")

    async def _acquire_env_for_trajectory(
        self,
        instance_id: Any,
        traj_id: int,
        dockerfile_path: str,
        server_names: List[str] = None,
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
        if self._env_pool is None:
            raise RuntimeError("Env pool not initialized")

        traj_key = f"{instance_id}-{traj_id}"
        agent_id = f"agent-{traj_key}"

        env_pool_cfg = getattr(self.mcp_config, 'env_pool', {})
        config = EnvConfig(
            servers=server_names or [],
            dockerfile_path=dockerfile_path,
            cpu_limit=safe_get(env_pool_cfg, 'cpu_limit', '2'),
            memory_limit=safe_get(env_pool_cfg, 'memory_limit', '4g'),
            gateway_mode=safe_get(env_pool_cfg, 'gateway_mode', 'sse'),
            use_dockerfile_cmd=safe_get(env_pool_cfg, 'use_dockerfile_cmd', False),
        )

        env = await self._env_pool.acquire(agent_id=agent_id, config=config)
        self._env_assignments[traj_key] = env.env_id

        logger.debug(f"Acquired env {env.env_id} for {traj_key} "
                     f"(dockerfile={dockerfile_path}): {env.gateway_address}")
        return env.gateway_address

    async def _release_env_for_trajectory(self, instance_id: Any, traj_id: int) -> None:
        """Release an environment back to the pool.

        Args:
            instance_id: Instance identifier
            traj_id: Trajectory identifier
        """
        if self._env_pool is None:
            return

        traj_key = f"{instance_id}-{traj_id}"
        env_id = self._env_assignments.pop(traj_key, None)

        if env_id:
            try:
                await self._env_pool.release(env_id)
                logger.debug(f"Released env {env_id} for {traj_key}")
            except Exception as e:
                logger.warning(f"Failed to release env {env_id} for {traj_key}: {e}")

    def _prepare_mcp_servers(self, instance: Dict[str, Any]) -> list:
        """Prepare MCP server configs with transport settings."""
        mcp_servers = instance.get("mcp_servers", [])
        if hasattr(mcp_servers, 'tolist'):
            mcp_servers = mcp_servers.tolist()

        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        mcp_gateway_address = getattr(self.mcp_config, 'mcp_gateway_address', '')

        if mcp_transport == 'docker_pool' and self._env_pool is not None:
            mcp_servers = [
                {**srv, "transport": "sse"} if isinstance(srv, dict)
                else {"name": srv, "transport": "sse"}
                for srv in mcp_servers
            ]
        elif mcp_transport == 'sse' and mcp_gateway_address:
            mcp_servers = [
                {**srv, "transport": "sse", "gateway_address": mcp_gateway_address}
                if isinstance(srv, dict)
                else {"name": srv, "transport": "sse", "gateway_address": mcp_gateway_address}
                for srv in mcp_servers
            ]
        return mcp_servers

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

    def _create_llm_for_trajectory(self, val_mode: bool):
        """Create or select an LLM for a single trajectory.

        Returns the LLM instance (TITOLLMWrapper or HTTP LLM).
        """
        if (self.rollout_mode == "token"
                and hasattr(self, '_rollout_servers') and self._rollout_servers):
            from mcpuniverse.llm.tito import TITOLLMWrapper

            replica_idx = self._traj_counter % len(self._rollout_servers)
            replica = self._rollout_servers[replica_idx]

            if hasattr(replica, '_server_handle') and replica._server_handle is not None:
                server = replica._server_handle
            elif hasattr(replica, 'servers') and replica.servers:
                server = replica.servers[0]
            else:
                logger.error(
                    f"Rollout replica has no server handle or servers list. "
                    f"Available attributes: {dir(replica)}"
                )
                raise RuntimeError(
                    "Cannot find inference server in replica. "
                    "TITO mode requires direct server access."
                )

            sampling_params = {
                "temperature": self._llm_config_base.get("temperature", 1.0),
                "top_p": self._llm_config_base.get("top_p", 1.0),
                "max_tokens": self._llm_config_base.get("max_tokens", 4096),
                "model_name": self._llm_config_base.get(
                    "model_name", f"tito_{self._rollout_backend}"
                ),
            }
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
            )
        else:
            llm_idx = self._traj_counter % len(self.llms)
            llm = self.llms[llm_idx]

        self._traj_counter += 1
        return llm

    def _build_env_callbacks(self, instance_id, traj_id, instance, mcp_servers):
        """Build acquire/release env callbacks for docker_pool transport."""
        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        if mcp_transport != 'docker_pool' or self._env_pool is None:
            return None, None

        dockerfile_path = instance.get("dockerfile_path", "")
        srv_names = [
            srv.get('name') if isinstance(srv, dict) else srv
            for srv in mcp_servers
        ]
        _iid, _tid, _dp, _sn = instance_id, traj_id, dockerfile_path, srv_names

        async def _acquire(_iid=_iid, _tid=_tid, _dp=_dp, _sn=_sn):
            return await self._acquire_env_for_trajectory(_iid, _tid, _dp, _sn)

        async def _release(_iid=_iid, _tid=_tid):
            await self._release_env_for_trajectory(_iid, _tid)

        return _acquire, _release

    def _tokenize_result(self, traj, instance_id, traj_id):
        """Tokenize a trajectory result into prompt/response tokens and loss mask."""
        result = traj.result

        if self.rollout_mode == "token" and hasattr(traj, '_tito_llm'):
            tito_llm = traj._tito_llm
            prompt_tokens = tito_llm.get_prompt_ids()
            response_tokens = tito_llm.get_response_ids()
            loss_mask = [1 if m else 0 for m in tito_llm.get_loss_mask()]

            logger.info(
                f"[TITO] instance={instance_id}, traj={traj_id}, "
                f"prompt_tokens={len(prompt_tokens)}, "
                f"response_tokens={len(response_tokens)}, "
                f"trainable_tokens={sum(loss_mask)}"
            )
        else:
            full_trace_text = result.trace.full_text or ""
            logger.info(
                f"[Trajectory] instance={instance_id}, traj={traj_id}, "
                f"words={len(full_trace_text.split())}, chars={len(full_trace_text)}"
            )

            if full_trace_text:
                formatter_output = self.formatter.format_trace(
                    full_trace_text, traj.data.get("instruction", "")
                )
                prompt_tokens, response_tokens, loss_mask = (
                    self.formatter.tokenize_with_mask(formatter_output, self.tokenizer)
                )
            else:
                prompt_text = traj.data.get("instruction", "")
                prompt_tokens = self.tokenizer.encode(prompt_text, add_special_tokens=True)
                response_text = result.response or ""
                if isinstance(response_text, dict):
                    response_text = json.dumps(response_text, ensure_ascii=False)
                response_tokens = self.tokenizer.encode(response_text, add_special_tokens=False)
                loss_mask = [1] * len(response_tokens)

            logger.info(
                f"[Tokens] instance={instance_id}, traj={traj_id}, "
                f"prompt={len(prompt_tokens)}, response={len(response_tokens)}, "
                f"total={len(prompt_tokens) + len(response_tokens)}"
            )

        return prompt_tokens, response_tokens, loss_mask

    async def _run_mcp_rollout(
        self,
        batch: List[Dict[str, Any]],
        val_mode: bool = False
    ) -> MCPGeneratorOutput:
        """Run MCP agent rollout using MCPTrajectory."""
        num_trajectories = self.val_num_trajectories if val_mode else self.num_trajectories
        trajectories = {}

        for batch_idx, instance in enumerate(batch):
            instance_id = instance.get("instance_id", batch_idx)
            trajectories[instance_id] = {}

            mcp_servers = self._prepare_mcp_servers(instance)
            evaluators = self._prepare_evaluators(instance)
            data = {
                **instance,
                "instruction": instance.get("instruction") or instance.get("question", ""),
            }

            for traj_id in range(num_trajectories):
                llm = self._create_llm_for_trajectory(val_mode)
                traj_cfg = TrajectoryConfig(
                    instance_id=instance_id,
                    trajectory_id=traj_id,
                    max_iterations=self.max_iterations,
                    agent_mode=self.mcp_config.agent_mode,
                    formatter_type=self.formatter_type,
                    rollout_mode=self.rollout_mode,
                )
                acquire_env_fn, release_env_fn = self._build_env_callbacks(
                    instance_id, traj_id, instance, mcp_servers,
                )
                traj = create_trajectory(
                    cfg=traj_cfg, data=data,
                    agent_mode=self.mcp_config.agent_mode,
                    llm=llm, mcp_manager=self.mcp_manager,
                    mcp_servers=mcp_servers,
                    agent_config=self.mcp_config.agent_config,
                    evaluators=evaluators, val_mode=val_mode,
                    tokenizer=self.tokenizer,
                    acquire_env=acquire_env_fn,
                    release_env=release_env_fn,
                    trace_logger=self._trace_logger,
                )
                if self.rollout_mode == "token":
                    traj._tito_llm = llm
                trajectories[instance_id][traj_id] = traj

        # Run dispatcher
        dispatcher = get_dispatcher("async_pipeline")
        dispatcher_cfg = {
            "max_parallel_agents": self.mcp_config.dispatcher.max_parallel_agents,
            "num_instances": len(batch),
            "num_trajectories": num_trajectories,
            "max_init_retries": self.mcp_config.dispatcher.max_init_retries,
            "init_retry_delay": self.mcp_config.dispatcher.init_retry_delay,
            "init_timeout": getattr(self.mcp_config.dispatcher, 'init_timeout', 300),
        }
        await dispatcher(dispatcher_cfg, trajectories)

        # Collect results
        output = self._collect_rollout_results(trajectories, batch, num_trajectories)
        return output

    def _collect_rollout_results(
        self, trajectories: dict, batch: list, num_trajectories: int,
    ) -> MCPGeneratorOutput:
        """Collect and aggregate results from completed trajectories."""
        output = MCPGeneratorOutput()
        rollout_metrics = {
            "num_instances": len(batch),
            "num_trajectories": len(batch) * num_trajectories,
            "total_reward": 0.0,
            "success_count": 0,
        }

        missing_results = []
        for instance_id, trajs in trajectories.items():
            for traj_id, traj in trajs.items():
                if not traj.result:
                    missing_results.append(f"{instance_id}-{traj_id}")
                    continue

                prompt_tokens, response_tokens, loss_mask = self._tokenize_result(
                    traj, instance_id, traj_id,
                )
                output.prompt_token_ids.append(prompt_tokens)
                output.response_ids.append(response_tokens)
                output.loss_masks.append(loss_mask)
                output.rewards.append(traj.result.reward)

                traj_dict = traj.result.to_dict() if hasattr(traj.result, 'to_dict') else {}
                traj_dict["instance_id"] = instance_id
                traj_dict["trajectory_id"] = traj_id
                output.trajectories.append(traj_dict)

                rollout_metrics["total_reward"] += traj.result.reward
                if traj.result.reward > 0:
                    rollout_metrics["success_count"] += 1

        total_expected = len(batch) * num_trajectories
        total_collected = len(output.rewards)
        rollout_metrics["num_trajectories"] = total_expected
        rollout_metrics["num_collected"] = total_collected
        rollout_metrics["num_missing"] = total_expected - total_collected
        rollout_metrics["mean_reward"] = (
            rollout_metrics["total_reward"] / max(total_collected, 1)
        )
        rollout_metrics["success_rate"] = (
            rollout_metrics["success_count"] / max(total_collected, 1)
        )
        output.rollout_metrics = rollout_metrics

        if missing_results:
            logger.warning(
                f"Missing results for {len(missing_results)} trajectories: "
                f"{missing_results[:20]}{'...' if len(missing_results) > 20 else ''}"
            )

        logger.info(
            f"Rollout complete: {total_collected}/{total_expected} sequences collected "
            f"from {len(batch)} instances * {num_trajectories} trajectories"
        )
        if total_collected == 0:
            logger.warning("No valid trajectories collected! Checking results...")
            for instance_id, trajs in trajectories.items():
                for traj_id, traj in trajs.items():
                    logger.warning(
                        f"  Instance {instance_id}, Traj {traj_id}: "
                        f"result={traj.result is not None}"
                    )

        return output

    def _postprocess(self, output: MCPGeneratorOutput) -> DataProto:
        """Postprocess rollout output to VERL DataProto format."""
        if not output.prompt_token_ids or not output.response_ids:
            return DataProto(
                batch=None,
                non_tensor_batch={"rewards": np.array([]), "uid": np.array([], dtype=object)},
                meta_info={"rollout_metrics": output.rollout_metrics, "timing": {}},
            )

        # Configured limits for truncation
        cfg_max_prompt = OmegaConf.select(self.config, "data.max_prompt_length", default=65536)
        cfg_max_response = OmegaConf.select(self.config, "data.max_response_length", default=65536)

        # Truncate sequences that exceed configured limits
        truncated_count = 0
        for i, _ in enumerate(output.prompt_token_ids):
            if len(output.prompt_token_ids[i]) > cfg_max_prompt:
                # Truncate prompt from the left (keep the end)
                output.prompt_token_ids[i] = output.prompt_token_ids[i][-cfg_max_prompt:]
                truncated_count += 1
            if len(output.response_ids[i]) > cfg_max_response:
                # Truncate response from the right (keep the beginning)
                output.response_ids[i] = output.response_ids[i][:cfg_max_response]
                output.loss_masks[i] = output.loss_masks[i][:cfg_max_response]
                truncated_count += 1
        if truncated_count > 0:
            logger.warning(
                f"Truncated {truncated_count} sequences to fit configured limits "
                f"(max_prompt={cfg_max_prompt}, max_response={cfg_max_response})"
            )

        # Prompts: left pad to actual max length (dynamic padding)
        self.tokenizer.padding_side = "left"
        max_prompt_length = max(len(ids) for ids in output.prompt_token_ids)
        prompt_outputs = self.tokenizer.pad(
            [{"input_ids": ids} for ids in output.prompt_token_ids],
            padding="max_length",
            max_length=max_prompt_length,
            return_tensors="pt",
            return_attention_mask=True,
        )
        prompt_ids = prompt_outputs["input_ids"]
        prompt_attention_mask = prompt_outputs["attention_mask"]

        # Responses: right pad to actual max length (dynamic padding)
        self.tokenizer.padding_side = "right"
        max_response_length = max(len(ids) for ids in output.response_ids)
        response_outputs = self.tokenizer.pad(
            [{"input_ids": ids} for ids in output.response_ids],
            padding="max_length",
            max_length=max_response_length,
            return_tensors="pt",
            return_attention_mask=True,
        )
        response_ids = response_outputs["input_ids"]
        response_attention_mask = response_outputs["attention_mask"]

        # Build response_mask from per-trajectory loss masks
        response_length = response_ids.shape[1]
        loss_masks = []
        for mask in output.loss_masks:
            padding_length = max(0, response_length - len(mask))
            loss_masks.append(mask + [0] * padding_length)
        response_mask = torch.tensor(loss_masks, dtype=torch.long)
        response_mask = response_mask * response_attention_mask

        logger.info(f"[Dynamic Padding] prompt_len={max_prompt_length}, "
                    f"response_len={max_response_length}, "
                    f"total_seq_len={max_prompt_length + max_response_length}")

        input_ids = torch.cat([prompt_ids, response_ids], dim=1)
        attention_mask = torch.cat([prompt_attention_mask, response_attention_mask], dim=1)
        position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask

        batch = TensorDict(
            {
                "prompts": prompt_ids,
                "responses": response_ids,
                "response_mask": response_mask,
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
            },
            batch_size=len(input_ids),
        )

        non_tensor_batch = {"rewards": np.array(output.rewards)}

        # uid for GRPO: same instance_id -> same uid for group advantage computation
        uids = []
        for i, traj in enumerate(output.trajectories or []):
            if isinstance(traj, dict):
                instance_id = traj.get("instance_id", f"instance_{i // self.num_trajectories}")
                uids.append(str(instance_id))
            else:
                uids.append(f"instance_{i // max(self.num_trajectories, 1)}")
        non_tensor_batch["uid"] = np.array(uids, dtype=object)

        if output.trajectories:
            non_tensor_batch["trajectories"] = np.array(output.trajectories, dtype=object)

        return DataProto(
            batch=batch,
            non_tensor_batch=non_tensor_batch,
            meta_info={"rollout_metrics": output.rollout_metrics, "timing": {}},
        )

    def ensure_env_pool(self, batch: List[Dict[str, Any]], max_parallel: int) -> None:
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
        if self._env_pool is None:
            self._run_async_safely(self._init_env_pool(max_parallel))
            self._run_async_safely(self._prewarm_env_pool(batch, max_parallel))

    def generate_sequences(self, prompts: DataProto,
                           manage_pool: bool = True) -> DataProto:
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
          - Create pool → pre-warm ``max_parallel`` containers → rollout
          - After rollout: release containers back to pool (keep alive)
          - Schedule background pre-warm for next step

        Step N (subsequent calls):
          - Wait for background pre-warm (started during previous gradient update)
          - Reconcile pool: reuse matching containers, evict non-matching
          - Rollout with warm containers (near-instant acquire)
          - Release containers → schedule background pre-warm → return
        """

        # Weight sync (FSDP -> inference server) is managed externally by the trainer
        # via CheckpointEngineManager.update_weights() / sleep_replicas().

        batch = self._parse_input_batch(prompts)
        val_mode = prompts.meta_info.get("val_mode", False)

        mcp_transport = getattr(self.mcp_config, 'mcp_transport', 'stdio')
        use_docker_pool = False

        if manage_pool and mcp_transport == 'docker_pool':
            env_pool_cfg = getattr(self.mcp_config, 'env_pool', None)
            if env_pool_cfg and safe_get(env_pool_cfg, 'enabled', False):
                use_docker_pool = True
                max_parallel = self.mcp_config.dispatcher.max_parallel_agents

                logger.info("Using docker_pool transport (per-task dockerfile)")
                logger.info(f"  Max parallel agents: {max_parallel}")

                if self._env_pool is None:
                    # First step: create pool + pre-warm
                    self._run_async_safely(self._init_env_pool(max_parallel))
                    self._run_async_safely(self._prewarm_env_pool(batch, max_parallel))
                else:
                    # Subsequent steps: wait for background pre-warm, then reconcile
                    self._run_async_safely(self._await_background_prewarm())
                    self._run_async_safely(self._reconcile_env_pool(batch, max_parallel))
            else:
                logger.warning("docker_pool transport requested but env_pool not enabled in config")

        try:
            output = self._run_async_safely(self._run_mcp_rollout(batch, val_mode))
            result = self._postprocess(output)
        finally:
            if use_docker_pool:
                # Release containers back to pool (not destroy) and start
                # background pre-warm that runs during gradient update
                self._run_async_safely(self._release_env_pool())
                self._start_background_prewarm(batch, max_parallel)

        self._trigger_periodic_cleanup()

        return result

    def _trigger_periodic_cleanup(self):
        """Trigger periodic cleanup to prevent resource exhaustion.

        In continuous rollout modes, zombie MCP processes may accumulate over time.
        """
        import gc

        self._step_counter += 1

        mcp_cfg = self.config.get('mcp_agent', {}) if hasattr(self.config, 'get') else {}
        cleanup_interval = mcp_cfg.get('cleanup_interval', 50) if hasattr(mcp_cfg, 'get') else 50
        if self._step_counter % cleanup_interval == 0:
            logger.info(f"Triggering periodic cleanup at step {self._step_counter}")
            gc.collect()

            # Kill orphaned stdio MCP server processes that weren't properly cleaned up
            import subprocess
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

    # Persistent fallback event loop for running async code when the main
    # loop (e.g. Ray's uvloop) doesn't support nest_asyncio.  Shared across
    # all instances so asyncio primitives (Lock, Queue) created in one
    # _run_async_safely call remain valid in subsequent calls.
    _fallback_loop: Optional[asyncio.AbstractEventLoop] = None
    _fallback_thread: Optional[threading.Thread] = None
    _fallback_lock = threading.Lock()  # protects _fallback_loop creation

    @classmethod
    def _get_fallback_loop(cls) -> asyncio.AbstractEventLoop:
        """Return a persistent SelectorEventLoop running in a daemon thread.

        All _run_async_safely calls that fall through to the uvloop-incompatible
        path share this single loop, ensuring asyncio primitives (locks, queues,
        subprocess transports) created in one call remain valid in the next.
        """
        def _quiet_handler(_loop, context):
            exc = context.get('exception')
            if exc:
                msg = str(exc)
                if 'asynchronous generator' in msg or 'aclose()' in msg:
                    return
            logger.debug("Fallback loop async exception: {}", context.get('message', 'unknown'))

        with cls._fallback_lock:
            if cls._fallback_loop is None or cls._fallback_loop.is_closed():
                loop = asyncio.SelectorEventLoop()
                loop.set_exception_handler(_quiet_handler)
                thread = threading.Thread(
                    target=loop.run_forever,
                    daemon=True,
                    name="mcp-fallback-loop",
                )
                thread.start()
                cls._fallback_loop = loop
                cls._fallback_thread = thread
                logger.info("Created persistent fallback SelectorEventLoop in background thread")
            return cls._fallback_loop

    def _run_async_safely(self, coro):
        """Run async coroutine safely from any thread context.

        Always submits to a persistent background SelectorEventLoop via
        ``run_coroutine_threadsafe``.  This handles all scenarios:

        - Ray actor thread with running uvloop (can't nest, can't patch)
        - ThreadPoolExecutor thread with no event loop
        - Any other thread

        Using a single shared loop also ensures asyncio primitives (Lock,
        Queue inside EnvPoolManager) are always accessed from the same loop,
        preventing ``RuntimeError: ... attached to a different loop``.
        """
        fallback = self._get_fallback_loop()
        future = asyncio.run_coroutine_threadsafe(coro, fallback)
        return future.result()

    def _parse_input_batch(self, prompts: DataProto) -> List[Dict[str, Any]]:
        """Parse DataProto to list of instance dicts."""
        batch = []
        non_tensor_batch = prompts.non_tensor_batch

        first_key = next(iter(non_tensor_batch.keys()))
        num_entries = len(non_tensor_batch[first_key])

        for i in range(num_entries):
            item = {key: non_tensor_batch[key][i] for key in non_tensor_batch.keys()}
            batch.append(item)

        return batch

    def _run_all(self, tasks: list):
        """Run async tasks synchronously."""
        async def run_all():
            await asyncio.gather(*tasks)
        self._run_async_safely(run_all())
