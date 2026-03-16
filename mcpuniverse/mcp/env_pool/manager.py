"""
Environment Pool Manager.

Manages a pool of MCP environments: provisioning, allocation, health
monitoring, auto-recovery, and usage statistics.
"""
# pylint: disable=broad-exception-caught,too-many-instance-attributes

import asyncio
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from loguru import logger

from .base import (
    BaseProvisioner,
    EnvConfig,
    EnvInfo,
    EnvStatus,
)

_MAX_TIMING_SAMPLES = 1000


@dataclass
class PoolStats:
    """Statistics about the environment pool."""
    total_envs: int = 0
    ready_envs: int = 0
    in_use_envs: int = 0
    error_envs: int = 0

    total_acquisitions: int = 0
    total_releases: int = 0
    total_resets: int = 0

    avg_acquisition_wait_ms: float = 0.0
    avg_usage_duration_s: float = 0.0

    created_at: float = field(default_factory=time.time)


class EnvPoolManager:
    """Manages a pool of MCP environments.

    Usage::

        pool = EnvPoolManager(provisioner, max_pool_size=20)
        await pool.provision(num_envs=10)

        env = await pool.acquire(agent_id="agent-1")
        # ... agent uses env.gateway_address ...
        await pool.release(env.env_id)

        await pool.cleanup()
    """

    def __init__(
        self,
        provisioner: BaseProvisioner,
        max_pool_size: int = 50,
        min_ready_envs: int = 0,
        auto_scale: bool = False,
        health_check_interval: float = 30.0,
        reset_on_release: bool = False,
        acquisition_timeout: float = 60.0,
        provisioners: Optional[List[BaseProvisioner]] = None,
        scheduling: str = "least-loaded",
    ):
        """Initialize the pool manager.

        Args:
            provisioner: Default environment provisioner.
            max_pool_size: Maximum number of environments in the pool.
            min_ready_envs: Minimum ready environments to maintain.
            auto_scale: Auto-provision when demand exceeds supply.
            health_check_interval: Seconds between health check rounds.
            reset_on_release: Reset environments on release.
            acquisition_timeout: Default timeout for ``acquire()`` (seconds).
            provisioners: Optional list for multi-host round-robin.
                Falls back to ``[provisioner]`` when not set.
            scheduling: Provisioner selection strategy.
                ``"least-loaded"`` (default) picks the provisioner currently
                managing the fewest environments.  ``"round-robin"`` cycles
                through provisioners in order regardless of load.
        """
        self.provisioner = provisioner
        self._provisioners = provisioners or [provisioner]
        self._provisioner_idx = 0
        self._scheduling = scheduling
        self.max_pool_size = max_pool_size
        self.min_ready_envs = min_ready_envs
        self.auto_scale = auto_scale
        self.health_check_interval = health_check_interval
        self.reset_on_release = reset_on_release
        self.acquisition_timeout = acquisition_timeout

        # Environment tracking
        self._envs: Dict[str, EnvInfo] = {}
        self._ready_queue: asyncio.Queue[str] = asyncio.Queue()
        self._in_use: Set[str] = set()
        self._env_provisioner: Dict[str, BaseProvisioner] = {}

        # Locks
        self._provision_lock = asyncio.Lock()
        self._acquire_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        # Track which event loop the async primitives are bound to.
        # _ensure_loop_bound() recreates them when the loop changes.
        self._bound_loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            self._bound_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        # Statistics
        self._stats = PoolStats()
        self._acquisition_times: deque = deque(maxlen=_MAX_TIMING_SAMPLES)
        self._usage_durations: deque = deque(maxlen=_MAX_TIMING_SAMPLES)

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._auto_scale_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------
    # Event-loop rebinding
    # ------------------------------------------------------------------

    def _ensure_loop_bound(self) -> None:
        """Recreate asyncio primitives if the event loop has changed.

        ``asyncio.Queue`` and ``asyncio.Lock`` are bound to the event loop
        that was running when they were created.  When the pool is used from
        a different loop (e.g. ``_run_async_safely`` creates a new one), all
        async operations on the old objects raise
        ``RuntimeError: ... bound to a different event loop``.

        This method detects the mismatch and rebuilds the primitives in the
        current loop, repopulating the ready-queue from authoritative state
        (``self._envs`` / ``self._in_use``).
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop — nothing to rebind

        if current_loop is self._bound_loop:
            return  # same loop — all good

        # Rebuild async primitives in the new event loop
        self._ready_queue = asyncio.Queue()
        self._provision_lock = asyncio.Lock()
        self._acquire_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        # Re-populate the ready queue from authoritative env state
        ready_count = 0
        for env_id, env_info in self._envs.items():
            if env_info.status == EnvStatus.READY and env_id not in self._in_use:
                self._ready_queue.put_nowait(env_id)
                ready_count += 1

        logger.info(
            "EnvPoolManager: rebound async primitives to current event loop "
            "({} ready environments re-queued)", ready_count,
        )
        self._bound_loop = current_loop

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _provisioner_load(self, provisioner: BaseProvisioner) -> int:
        """Count environments currently managed by *provisioner*."""
        return sum(1 for p in self._env_provisioner.values() if p is provisioner)

    def _next_provisioner(self) -> BaseProvisioner:
        """Return the next provisioner to use for environment creation.

        Skips provisioners marked as broken (``_build_broken=True``).

        When ``scheduling`` is ``"round-robin"`` (or there is only one
        provisioner), provisioners are cycled in order.  When ``scheduling``
        is ``"least-loaded"``, the provisioner currently managing the fewest
        environments is selected; ties are broken by index order.
        """
        healthy = [
            p for p in self._provisioners
            if not getattr(p, '_build_broken', False)
        ]
        if not healthy:
            healthy = self._provisioners  # fall back to all

        if self._scheduling == "round-robin" or len(healthy) == 1:
            p = healthy[self._provisioner_idx % len(healthy)]
            self._provisioner_idx += 1
            return p
        # least-loaded: pick the provisioner with the fewest environments.
        # On ties, prefer the one with the lower index (stable ordering).
        return min(healthy, key=self._provisioner_load)

    def _decrement_stat(self, attr: str, amount: int = 1) -> None:
        """Decrement a PoolStats counter, clamping at zero."""
        current = getattr(self._stats, attr)
        setattr(self._stats, attr, max(0, current - amount))

    def _update_avg_acquisition(self, wait_time_ms: float) -> None:
        self._acquisition_times.append(wait_time_ms)
        self._stats.avg_acquisition_wait_ms = (
            sum(self._acquisition_times) / len(self._acquisition_times)
        )

    def _update_avg_usage(self, duration_s: float) -> None:
        self._usage_durations.append(duration_s)
        self._stats.avg_usage_duration_s = (
            sum(self._usage_durations) / len(self._usage_durations)
        )

    @staticmethod
    async def _cancel_task(task: Optional[asyncio.Task]) -> None:
        """Cancel an asyncio task and suppress CancelledError."""
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _assign_env(self, env_id: str, agent_id: str,
                          start_time: float,
                          log_suffix: str = "") -> Optional[EnvInfo]:
        """Assign *env_id* to *agent_id* under ``_state_lock``.

        Returns the EnvInfo on success, or None if the env is stale.
        """
        async with self._state_lock:
            env_info = self._envs.get(env_id)
            if not env_info or env_info.status != EnvStatus.READY:
                return None

            env_info.status = EnvStatus.IN_USE
            env_info.assigned_agent = agent_id
            env_info.assigned_at = time.time()
            self._in_use.add(env_id)

            self._decrement_stat("ready_envs")
            self._stats.in_use_envs += 1
            self._stats.total_acquisitions += 1

            wait_time = (time.time() - start_time) * 1000
            self._update_avg_acquisition(wait_time)

        logger.info("Environment {} acquired by {} (wait: {:.1f}ms{})",
                     env_id, agent_id, wait_time, log_suffix)
        return env_info

    async def _handle_unhealthy_env(self, env_id: str,
                                    provisioner: BaseProvisioner) -> None:
        """Handle a failed health check: reset READY envs, error IN_USE ones."""
        logger.warning("Environment {} failed health check", env_id)

        async with self._state_lock:
            env_info = self._envs.get(env_id)
            if not env_info:
                return
            if env_info.status == EnvStatus.READY:
                self._decrement_stat("ready_envs")
                env_info.status = EnvStatus.RESETTING
            elif env_info.status == EnvStatus.IN_USE:
                env_info.status = EnvStatus.ERROR
                self._stats.error_envs += 1
                return
            else:
                return

        reset_ok = await provisioner.reset(env_id)

        async with self._state_lock:
            env_info = self._envs.get(env_id)
            if not env_info:
                return
            if reset_ok:
                env_info.status = EnvStatus.READY
                self._stats.ready_envs += 1
            else:
                env_info.status = EnvStatus.ERROR
                self._stats.error_envs += 1

    async def _register_env(self, env_id: str, env_info: EnvInfo,
                            provisioner: BaseProvisioner) -> None:
        """Register a newly created/recovered env under ``_state_lock``."""
        async with self._state_lock:
            self._envs[env_id] = env_info
            self._env_provisioner[env_id] = provisioner
            if env_info.status == EnvStatus.READY:
                await self._ready_queue.put(env_id)
                self._stats.ready_envs += 1
            self._stats.total_envs += 1

    # ------------------------------------------------------------------
    # Provision
    # ------------------------------------------------------------------

    async def provision(
        self,
        num_envs: int = 1,
        config: Optional[EnvConfig] = None,
        parallel: bool = True,
        reuse_existing: bool = True,
    ) -> List[EnvInfo]:
        """Provision environments into the pool.

        Prefers reusing existing containers with matching config (by reset)
        over creating new ones.
        """
        self._ensure_loop_bound()
        async with self._provision_lock:
            effective_config = config or getattr(
                self.provisioner, 'default_config', EnvConfig()
            )

            reused: List[EnvInfo] = []
            if reuse_existing:
                reused = await self._try_reuse_containers(num_envs, effective_config)
                if reused:
                    logger.info("Reused {} existing containers", len(reused))

            remaining = num_envs - len(reused)
            if remaining <= 0:
                return reused

            current = len(self._envs)
            can_create = min(remaining, self.max_pool_size - current)
            if can_create <= 0:
                logger.warning("Pool at capacity ({}/{})", current, self.max_pool_size)
                return reused

            logger.info("Provisioning {} new environments...", can_create)

            async def _create_one(provisioner: BaseProvisioner) -> Optional[EnvInfo]:
                env_id = f"env-{uuid.uuid4().hex[:8]}"
                try:
                    env_info = await provisioner.create(env_id, effective_config)
                    await self._register_env(env_id, env_info, provisioner)
                    return env_info
                except Exception as e:
                    err_msg = str(e) or repr(e)
                    logger.error(
                        "Failed to create environment {} ({}): {}\n{}",
                        env_id, type(e).__name__, err_msg,
                        traceback.format_exc(),
                    )
                    return None

            if parallel:
                # Pre-assign provisioners round-robin so parallel creates
                # are evenly distributed (least-loaded doesn't work here
                # because load counters update only after create completes).
                # Skip provisioners marked as broken (e.g. image build
                # succeeds but image doesn't persist on the Docker host).
                healthy = [
                    p for p in self._provisioners
                    if not getattr(p, '_build_broken', False)
                ]
                if not healthy:
                    logger.error("All provisioners are broken, using all anyway")
                    healthy = self._provisioners
                assignments = [
                    healthy[i % len(healthy)]
                    for i in range(can_create)
                ]
                results = await asyncio.gather(
                    *[_create_one(p) for p in assignments],
                    return_exceptions=True,
                )
                new_envs = [r for r in results if isinstance(r, EnvInfo)]
            else:
                new_envs = []
                for _ in range(can_create):
                    env = await _create_one(self._next_provisioner())
                    if env:
                        new_envs.append(env)

            all_envs = reused + new_envs
            logger.info("Provisioned {} environments ({} reused, {} new). "
                        "Pool: {}/{}", len(all_envs), len(reused),
                        len(new_envs), len(self._envs), self.max_pool_size)
            return all_envs

    async def _try_reuse_containers(self, num_needed: int,
                                    config: EnvConfig) -> List[EnvInfo]:
        """Find unmanaged containers with matching config and recover them."""
        try:
            # Compute current dockerfile hash for matching
            current_hash = ""
            if config.dockerfile_path:
                for p in self._provisioners:
                    if hasattr(p, 'compute_dockerfile_hash'):
                        try:
                            current_hash = p.compute_dockerfile_hash(config.dockerfile_path)
                            break
                        except Exception:
                            pass

            # Discover containers across all provisioners
            candidates = []  # (provisioner, ContainerInfo)
            for p in self._provisioners:
                if not all(hasattr(p, m) for m in
                           ('find_existing_containers', 'configs_match', 'recover_container')):
                    continue
                try:
                    for ci in await p.find_existing_containers():
                        candidates.append((p, ci))
                except Exception as e:
                    logger.warning(
                        "Failed to find containers on provisioner ({}): {}",
                        type(e).__name__, str(e) or repr(e),
                    )

            if not candidates:
                return []

            logger.info("Found {} existing containers, checking for matches...",
                        len(candidates))

            # Filter matching candidates
            matched = []
            for src_prov, ci in candidates:
                if len(matched) >= num_needed:
                    break
                if ci.env_id in self._envs:
                    continue
                if not ci.host_port:
                    continue
                if not src_prov.configs_match(config, ci.config,
                                              current_hash, ci.dockerfile_hash):
                    continue
                matched.append((src_prov, ci))

            if not matched:
                return []

            logger.info("Recovering {} containers in parallel...", len(matched))

            # Recover all matched containers in parallel
            async def _recover_one(src_prov, ci):
                logger.info("Reusing container mcp-env-{} (status={}, port={})",
                            ci.env_id, ci.status, ci.host_port)
                env_info = await src_prov.recover_container(
                    ci.env_id, config, ci.host_port,
                )
                return (ci.env_id, env_info, src_prov) if env_info else None

            results = await asyncio.gather(
                *[_recover_one(p, c) for p, c in matched],
                return_exceptions=True,
            )

            reused: List[EnvInfo] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Container recovery failed: {}", result)
                    continue
                if result is None:
                    continue
                env_id, env_info, src_prov = result
                await self._register_env(env_id, env_info, src_prov)
                reused.append(env_info)

            return reused
        except Exception as e:
            logger.warning("Error trying to reuse containers: {}", e)
            return []

    # ------------------------------------------------------------------
    # Acquire / Release / Destroy
    # ------------------------------------------------------------------

    @staticmethod
    def _config_compatible(env_config: Optional[EnvConfig],
                           requested: Optional[EnvConfig]) -> bool:
        """Check whether *env_config* can serve *requested*.

        Compares ``dockerfile_path`` (the main differentiator between
        container images).  When either side is ``None`` or empty, the
        check is skipped (any container is acceptable).
        """
        if not requested or not requested.dockerfile_path:
            return True
        if not env_config or not env_config.dockerfile_path:
            return True
        return env_config.dockerfile_path == requested.dockerfile_path

    async def acquire(self, agent_id: str, timeout: Optional[float] = None,
                      config: Optional[EnvConfig] = None) -> EnvInfo:
        """Acquire a ready environment for *agent_id*.

        When *config* specifies a ``dockerfile_path``, only containers
        built from the same Dockerfile are considered.  Non-matching
        containers are put back into the ready queue.

        Raises ``TimeoutError`` if nothing is available within *timeout*.
        When ``auto_scale`` is enabled, provisions a new env on demand.
        """
        self._ensure_loop_bound()
        timeout = timeout or self.acquisition_timeout
        start = time.time()

        async with self._acquire_lock:
            skipped: List[str] = []
            try:
                # Drain entries until we find a compatible, valid one
                while True:
                    remaining = timeout - (time.time() - start)
                    if remaining <= 0:
                        break
                    try:
                        env_id = await asyncio.wait_for(
                            self._ready_queue.get(), timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        break

                    # Check config compatibility (dockerfile match)
                    env_info = self._envs.get(env_id)
                    if env_info and not self._config_compatible(env_info.config, config):
                        skipped.append(env_id)
                        continue

                    result = await self._assign_env(env_id, agent_id, start)
                    if result is not None:
                        return result
            finally:
                # Put back non-matching containers so others can use them
                for eid in skipped:
                    await self._ready_queue.put(eid)

            # Auto-provision if allowed
            if self.auto_scale and len(self._envs) < self.max_pool_size:
                logger.info("No compatible environment, auto-provisioning for {}", agent_id)
                envs = await self.provision(num_envs=1, config=config)
                if envs and envs[0].status == EnvStatus.READY:
                    try:
                        env_id = await asyncio.wait_for(
                            self._ready_queue.get(), timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    else:
                        result = await self._assign_env(
                            env_id, agent_id, start,
                            log_suffix=", auto-provisioned",
                        )
                        if result is not None:
                            return result

            raise TimeoutError(
                f"No environment available within {timeout}s. "
                f"Pool: {self._stats.ready_envs} ready, "
                f"{self._stats.in_use_envs} in use, "
                f"{self._stats.total_envs} total"
            )

    async def release(self, env_id: str,
                      reset: Optional[bool] = None) -> bool:
        """Release an environment back to the pool."""
        self._ensure_loop_bound()
        async with self._state_lock:
            if env_id not in self._envs:
                logger.warning("Unknown environment {}", env_id)
                return False
            env_info = self._envs[env_id]
            if env_id not in self._in_use:
                logger.warning("Environment {} not in use", env_id)
                return False

            if env_info.assigned_at:
                self._update_avg_usage(time.time() - env_info.assigned_at)

            agent_id = env_info.assigned_agent
            self._in_use.discard(env_id)
            self._decrement_stat("in_use_envs")

        # Optional reset (outside lock)
        should_reset = reset if reset is not None else self.reset_on_release
        if should_reset:
            logger.info("Resetting environment {}", env_id)
            async with self._state_lock:
                self._stats.total_resets += 1
            provisioner = self._env_provisioner.get(env_id, self.provisioner)
            if not await provisioner.reset(env_id):
                logger.error("Failed to reset environment {}, destroying", env_id)
                async with self._state_lock:
                    self._stats.error_envs += 1
                await self.destroy(env_id)
                return False

        # Return to ready pool
        async with self._state_lock:
            if env_id not in self._envs:
                logger.warning("Environment {} removed during release", env_id)
                return False
            env_info = self._envs[env_id]
            env_info.status = EnvStatus.READY
            env_info.assigned_agent = None
            env_info.assigned_at = None
            await self._ready_queue.put(env_id)
            self._stats.ready_envs += 1
            self._stats.total_releases += 1

        logger.info("Environment {} released by {}", env_id, agent_id)
        return True

    async def destroy(self, env_id: str) -> bool:
        """Destroy an environment permanently."""
        self._ensure_loop_bound()
        async with self._state_lock:
            if env_id not in self._envs:
                return False
            env_info = self._envs[env_id]
            prev = env_info.status
            env_info.status = EnvStatus.TERMINATED

            if env_id in self._in_use:
                self._in_use.discard(env_id)
                self._decrement_stat("in_use_envs")
            elif prev == EnvStatus.READY:
                self._decrement_stat("ready_envs")
            elif prev == EnvStatus.ERROR:
                self._decrement_stat("error_envs")

        provisioner = self._env_provisioner.get(env_id, self.provisioner)
        success = await provisioner.destroy(env_id)

        async with self._state_lock:
            if success:
                self._envs.pop(env_id, None)
                self._env_provisioner.pop(env_id, None)
                self._decrement_stat("total_envs")
            elif env_id in self._envs:
                self._envs[env_id].status = EnvStatus.ERROR
        return success

    # ------------------------------------------------------------------
    # Cleanup & background tasks
    # ------------------------------------------------------------------

    async def cleanup(self) -> int:
        """Destroy all environments and stop background tasks."""
        self._ensure_loop_bound()
        logger.info("Cleaning up environment pool...")
        self._running = False
        await self._cancel_task(self._health_check_task)
        await self._cancel_task(self._auto_scale_task)

        count = 0
        for env_id in list(self._envs):
            if await self.destroy(env_id):
                count += 1
        logger.info("Cleaned up {} environments", count)
        return count

    def start_background_tasks(self) -> None:
        """Start health-check and (optionally) auto-scale loops."""
        self._ensure_loop_bound()
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        if self.auto_scale:
            self._auto_scale_task = asyncio.create_task(self._auto_scale_loop())

    async def _health_check_loop(self) -> None:
        logger.info("Starting health check loop (interval: {}s)",
                     self.health_check_interval)
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                async with self._state_lock:
                    snapshot = [
                        eid for eid, ei in self._envs.items()
                        if ei.status in (EnvStatus.READY, EnvStatus.IN_USE)
                    ]
                for env_id in snapshot:
                    prov = self._env_provisioner.get(env_id, self.provisioner)
                    if not await prov.health_check(env_id):
                        await self._handle_unhealthy_env(env_id, prov)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in health check loop: {}", e)

    async def _auto_scale_loop(self) -> None:
        logger.info("Starting auto-scale loop")
        while self._running:
            try:
                await asyncio.sleep(10.0)
                if self._stats.ready_envs < self.min_ready_envs:
                    need = self.min_ready_envs - self._stats.ready_envs
                    logger.info("Auto-scaling: provisioning {} environments", need)
                    try:
                        await asyncio.wait_for(
                            self.provision(num_envs=need), timeout=300.0,
                        )
                    except asyncio.TimeoutError:
                        logger.error("Auto-scale provisioning timed out (300s)")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in auto-scale loop: {}", e)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_stats(self) -> PoolStats:
        """Return current pool statistics."""
        return self._stats

    def get_provisioner_stats(self) -> List[Dict[str, object]]:
        """Per-provisioner environment counts."""
        results = []
        for i, p in enumerate(self._provisioners):
            load = self._provisioner_load(p)
            results.append({
                "index": i,
                "provisioner": repr(p),
                "env_count": load,
            })
        return results

    def get_all_envs(self) -> List[EnvInfo]:
        """Return info for all managed environments."""
        return list(self._envs.values())

    def get_ready_count(self) -> int:
        """Return number of ready environments."""
        return self._stats.ready_envs

    def get_in_use_count(self) -> int:
        """Return number of in-use environments."""
        return self._stats.in_use_envs

    async def get_env_info(self, env_id: str) -> Optional[EnvInfo]:
        """Return info for a specific environment, or None."""
        return self._envs.get(env_id)

    def __repr__(self) -> str:
        return (f"EnvPoolManager(total={self._stats.total_envs}, "
                f"ready={self._stats.ready_envs}, "
                f"in_use={self._stats.in_use_envs}, "
                f"max={self.max_pool_size})")
