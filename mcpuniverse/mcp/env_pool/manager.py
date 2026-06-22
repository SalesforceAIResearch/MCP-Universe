"""
Environment Pool Manager.

Manages a pool of MCP environments: provisioning, allocation, health
monitoring, auto-recovery, and usage statistics.
"""
# pylint: disable=broad-exception-caught,too-many-instance-attributes,too-many-lines,too-many-return-statements

import asyncio
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from .base import (
    BaseProvisioner,
    EnvConfig,
    EnvInfo,
    EnvStatus,
    env_configs_compatible,
)

_MAX_TIMING_SAMPLES = 1000

# When a compatible env exists but is busy, wait at most this long for it to be
# released (reusing it beats creating a new container) before provisioning a
# fresh one. Skipped entirely when no compatible env exists (e.g. per-task
# images), so those acquisitions provision immediately instead of stalling.
_RELEASE_WAIT_SLICE_S = 5.0
_VALID_REUSE_POLICIES = {"cache", "destroy", "trimmed_cache"}


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
        provision_concurrency: int = 8,
        destroy_concurrency: int = 8,
        reuse_policy: str = "cache",
        max_ready_envs: int = 0,
        max_ready_per_key: int = 0,
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
            provision_concurrency: Max number of containers created
                concurrently (the slow ``provisioner.create()``). Bounds the
                thundering herd when many acquisitions need a fresh container
                at once; typically set to the rollout's ``max_parallel``.
            reuse_policy: What to do with envs on release:
                ``"cache"`` returns them to the ready queue, ``"destroy"``
                removes them, and ``"trimmed_cache"`` caches only within the
                configured ready-env quotas.
            max_ready_envs: Optional global ready-cache quota. ``0`` means
                unlimited for ``cache`` and no cache for ``trimmed_cache``.
            max_ready_per_key: Optional ready-cache quota per compatible
                env config. ``0`` means unlimited for ``cache`` and no per-key
                cache for ``trimmed_cache``.
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
        self.reuse_policy = self._normalize_reuse_policy(reuse_policy)
        self.max_ready_envs = max(0, int(max_ready_envs or 0))
        self.max_ready_per_key = max(0, int(max_ready_per_key or 0))

        # Environment tracking
        self._envs: Dict[str, EnvInfo] = {}
        self._ready_queue: asyncio.Queue[str] = asyncio.Queue()
        self._in_use: Set[str] = set()
        self._env_provisioner: Dict[str, BaseProvisioner] = {}

        # Concurrency control.
        # ``_acquire_lock`` serializes ONLY the fast ready-queue bookkeeping
        # (drain / restore / evict pick). The slow ``provision()`` / ``destroy()``
        # run OUTSIDE it, so acquisitions don't serialize behind container
        # creation. ``_state_lock`` guards the env dicts/stats. ``_reuse_lock``
        # serializes container reuse discovery (so two provisions don't recover
        # the same container). ``_provision_sem`` bounds how many slow
        # ``provisioner.create()`` calls run at once across ALL in-flight
        # provisions; ``_in_flight`` reserves pool slots so concurrent
        # provisions never exceed ``max_pool_size``.
        self._acquire_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._reuse_lock = asyncio.Lock()
        self.provision_concurrency = max(1, int(provision_concurrency))
        self._provision_sem = asyncio.Semaphore(self.provision_concurrency)
        self._in_flight = 0

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
        self._reaper_task: Optional[asyncio.Task] = None
        self._reaper_interval = 30.0
        # Periodic image GC (every N reaper cycles). Continuous mode runs no
        # prewarm — which is where image GC used to live — so without this the
        # host disk fills with per-task images and ``docker run`` thrashes.
        self._gc_every_cycles = 8
        self._running = False

        # env_ids with an in-flight (shielded) teardown. The reaper skips these
        # so it never races a destroy that is about to pop the env itself.
        self._destroying: Set[str] = set()

        # Async background destruction: ``release()`` for a non-reusable env just
        # marks it PENDING_DESTROY and enqueues here (fast, no docker on the
        # trajectory's critical path); dedicated destroyer workers do the actual
        # ``docker rm`` off-band (on the provisioner's separate destroy pool).
        # PENDING_DESTROY envs still count against ``max_pool_size`` until
        # removed, so a slow teardown naturally backpressures new acquisitions.
        self._destroy_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._destroyer_tasks: List[asyncio.Task] = []
        self._destroy_concurrency = max(1, int(destroy_concurrency))

    @staticmethod
    def _normalize_reuse_policy(policy: str) -> str:
        normalized = str(policy or "cache").strip().lower()
        if normalized not in _VALID_REUSE_POLICIES:
            logger.warning(
                "Unknown env reuse_policy={!r}; falling back to 'cache'",
                policy,
            )
            return "cache"
        return normalized

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
        self._destroy_queue = asyncio.Queue()
        self._acquire_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._reuse_lock = asyncio.Lock()
        self._provision_sem = asyncio.Semaphore(self.provision_concurrency)
        self._in_flight = 0

        # Re-populate the ready + destroy queues from authoritative env state
        ready_count = 0
        for env_id, env_info in self._envs.items():
            if env_info.status == EnvStatus.READY and env_id not in self._in_use:
                self._ready_queue.put_nowait(env_id)
                ready_count += 1
            elif env_info.status == EnvStatus.PENDING_DESTROY:
                self._destroy_queue.put_nowait(env_id)

        self._bound_loop = current_loop
        logger.info(
            "EnvPoolManager: rebound async primitives to current event loop "
            "({} ready environments re-queued)", ready_count,
        )
        # CRITICAL: the background destroyer + reaper tasks were created by
        # start_destroyer()/start_reaper() on the OLD loop and are awaiting the
        # OLD _destroy_queue object. After this rebind they can NEVER consume the
        # NEW _destroy_queue, so every released env (set PENDING_DESTROY + re-queued
        # above) piles up un-destroyed, capacity never frees, and the whole pool
        # hard-stalls ("Pool at capacity" while in_use collapses -- envs are never
        # torn down after a trajectory finishes). Relaunch the workers on THIS loop.
        # (start_destroyer/start_reaper call _ensure_loop_bound() again, but
        # _bound_loop is already current_loop now, so that's a no-op -> no recursion.
        # The stale old-loop task handles are dropped; if their loop is dead they are
        # GC'd, if alive they harmlessly idle on the orphaned queue.)
        if self._running:
            self._destroyer_tasks = []
            self._reaper_task = None
            self.start_destroyer()
            self.start_reaper()

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

    def _ready_count_for_config(self, config: Optional[EnvConfig]) -> int:
        """Count READY envs compatible with *config*."""
        return sum(
            1
            for env in self._envs.values()
            if env.status == EnvStatus.READY
            and self._config_compatible(env.config, config)
        )

    def _should_cache_released_env(self, env_info: EnvInfo) -> bool:
        """Whether a released env should return to the ready queue."""
        if self.reuse_policy == "destroy":
            return False

        if self.reuse_policy == "cache":
            # Cache is the backwards-compatible default. Quotas are optional.
            if self.max_ready_envs and self._stats.ready_envs >= self.max_ready_envs:
                return False
            if (
                self.max_ready_per_key
                and self._ready_count_for_config(env_info.config) >= self.max_ready_per_key
            ):
                return False
            return True

        # trimmed_cache keeps a bounded reusable cache. With no quota it behaves
        # like destroy, which is useful for SWE/R2E-style one-shot envs.
        if self.max_ready_envs <= 0 and self.max_ready_per_key <= 0:
            return False
        if self.max_ready_envs > 0 and self._stats.ready_envs >= self.max_ready_envs:
            return False
        if (
            self.max_ready_per_key > 0
            and self._ready_count_for_config(env_info.config) >= self.max_ready_per_key
        ):
            return False
        return True

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

    async def provision(  # pylint: disable=unused-argument
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
        effective_config = config or getattr(
            self.provisioner, 'default_config', EnvConfig()
        )

        # ----- Reuse unmanaged containers first (serialized so two concurrent
        # provisions can't recover the same container). _register_env handles
        # its own state locking. -----
        reused: List[EnvInfo] = []
        if reuse_existing:
            async with self._reuse_lock:
                reused = await self._try_reuse_containers(num_envs, effective_config)
            if reused:
                logger.info("Reused {} existing containers", len(reused))

        remaining = num_envs - len(reused)
        if remaining <= 0:
            return reused

        # ----- Atomically reserve pool slots so concurrent provisions never
        # push the pool past max_pool_size. ``_in_flight`` counts reserved-but-
        # not-yet-registered envs alongside the live ``_envs``. -----
        async with self._state_lock:
            # Count only LIVE envs against capacity. A TERMINATED entry can
            # linger briefly while its (shielded) teardown finishes popping it;
            # counting those would falsely report "at capacity" and stall new
            # creates. Race-free: we never pop here, just exclude from the count.
            live = sum(
                1 for info in self._envs.values()
                if info.status != EnvStatus.TERMINATED
            )
            projected = live + self._in_flight
            can_create = max(0, min(remaining, self.max_pool_size - projected))
            self._in_flight += can_create
        if can_create <= 0:
            logger.warning(
                "Pool at capacity ({}/{})",
                live + self._in_flight, self.max_pool_size,
            )
            # Yield before returning. When the pool is pinned at capacity the
            # caller (continuous pipeline) retries provision in a tight loop;
            # without a yield that retry-storm starves the background DESTROYER
            # coroutines on this same event loop, so released envs are never torn
            # down, the pool never drops below capacity, and the whole pool
            # hard-stalls (observed under the high-churn apptainer backend:
            # total_envs pinned at max while in_use collapses to a handful).
            # A short sleep throttles the storm AND lets the destroyers run.
            await asyncio.sleep(0.25)
            return reused

        logger.info("Provisioning {} new environments...", can_create)

        async def _create_one(provisioner: BaseProvisioner) -> Optional[EnvInfo]:
            env_id = f"env-{uuid.uuid4().hex[:8]}"
            try:
                # The semaphore is the ONLY throttle on the slow create; it is
                # held across all in-flight provisions so the Docker host isn't
                # hit by an unbounded burst.
                async with self._provision_sem:
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
            finally:
                async with self._state_lock:
                    self._in_flight -= 1

        # Pre-assign provisioners round-robin so parallel creates are evenly
        # distributed (least-loaded doesn't work here because load counters
        # update only after create completes). Skip provisioners marked as
        # broken (image build succeeds but image doesn't persist on the host).
        healthy = [
            p for p in self._provisioners
            if not getattr(p, '_build_broken', False)
        ]
        if not healthy:
            logger.error("All provisioners are broken, using all anyway")
            healthy = self._provisioners
        assignments = [healthy[i % len(healthy)] for i in range(can_create)]

        results = await asyncio.gather(
            *[_create_one(p) for p in assignments],
            return_exceptions=True,
        )
        new_envs = [r for r in results if isinstance(r, EnvInfo)]

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
        return env_configs_compatible(env_config, requested)

    async def acquire(self, agent_id: str, timeout: Optional[float] = None,
                      config: Optional[EnvConfig] = None) -> EnvInfo:
        """Acquire a ready environment for *agent_id*.

        When *config* specifies a ``dockerfile_path``, only containers built
        from the same Dockerfile are considered; non-matching ones are put back.

        Two-phase loop so acquisitions don't serialize behind container builds:

        - Fast path (under ``_acquire_lock``): non-blocking drain of the ready
          queue for a compatible env. Serializing only this fast bookkeeping
          stops concurrent acquirers from thrashing the queue.
        - Slow path (NO ``_acquire_lock``): ``provision()`` a new env (runs
          concurrently across acquirers, bounded by ``_provision_sem``) or evict
          an incompatible idle env when the pool is full. ``destroy()`` /
          ``provision()`` never hold ``_acquire_lock``.

        Raises ``TimeoutError`` if nothing becomes available within *timeout*.
        When ``auto_scale`` is disabled, blocks waiting for a release instead.
        """
        self._ensure_loop_bound()
        timeout = timeout or self.acquisition_timeout
        start = time.time()

        while timeout - (time.time() - start) > 0:
            # ---- Fast path: a compatible env already waiting? ----
            async with self._acquire_lock:
                env = await self._drain_ready_nowait(agent_id, config, start)
            if env is not None:
                return env

            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break

            if not self.auto_scale:
                # Static pool: block until a compatible env is released.
                env = await self._wait_ready_blocking(
                    agent_id, config, start, remaining,
                )
                if env is not None:
                    return env
                continue

            # ---- Slow path (concurrent) ----
            # If a compatible env exists but is busy, prefer reusing it via a
            # release (cheaper than a new container) — wait a bounded slice.
            # When NO compatible env exists (e.g. per-task images), skip the
            # wait and provision immediately instead of stalling.
            # ``destroy`` never reuses (released envs are torn down), so waiting
            # for a busy compatible env to free up is pointless — provision now.
            if self.reuse_policy != "destroy" and self._has_compatible_env(config):
                env = await self._wait_ready_blocking(
                    agent_id, config, start, min(remaining, _RELEASE_WAIT_SLICE_S),
                )
                if env is not None:
                    return env

            # Create a new env if capacity allows (concurrent across acquirers).
            created = await self.provision(num_envs=1, config=config)
            if not created and await self._evict_one_incompatible(agent_id, config):
                # Pool was full: evicted an incompatible idle env, now retry.
                created = await self.provision(num_envs=1, config=config)
            if created:
                async with self._acquire_lock:
                    env = await self._drain_ready_nowait(agent_id, config, start)
                if env is not None:
                    return env
                continue  # someone else grabbed it; loop and try again

            # Full and nothing evictable: wait briefly for a release, then retry.
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break
            await self._wait_for_release(min(remaining, 1.0))

        raise TimeoutError(
            f"No environment available within {timeout}s. "
            f"Pool: {self._stats.ready_envs} ready, "
            f"{self._stats.in_use_envs} in use, "
            f"{self._stats.total_envs} total"
        )

    def _has_compatible_env(self, config: Optional[EnvConfig]) -> bool:
        """True if any managed env (ready / in-use / resetting) is compatible.

        Used by ``acquire`` to decide whether waiting for a release can serve
        this request (reuse) or whether to provision immediately (no compatible
        env exists, e.g. per-task images). Synchronous: no ``await`` inside, so
        the scan is atomic w.r.t. the event loop.
        """
        for env_info in self._envs.values():
            if env_info.status in (
                EnvStatus.READY, EnvStatus.IN_USE, EnvStatus.RESETTING,
            ) and self._config_compatible(env_info.config, config):
                return True
        return False

    async def _drain_ready_nowait(self, agent_id: str,
                                  config: Optional[EnvConfig],
                                  start: float) -> Optional[EnvInfo]:
        """Non-blocking drain of the ready queue for a compatible env.

        Assigns and returns the first compatible env; restores incompatible
        ones; drops stale (non-READY) ones. Caller must hold ``_acquire_lock``.
        Returns None if nothing compatible is immediately available.
        """
        skipped: List[str] = []
        found: Optional[EnvInfo] = None
        try:
            while True:
                try:
                    env_id = self._ready_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                env_info = self._envs.get(env_id)
                if env_info and not self._config_compatible(env_info.config, config):
                    skipped.append(env_id)
                    continue
                result = await self._assign_env(env_id, agent_id, start)
                if result is not None:
                    found = result
                    break
                # stale (not READY / removed) -> drop, do not restore
        finally:
            for eid in skipped:
                if eid in self._envs:
                    self._ready_queue.put_nowait(eid)
        return found

    async def _evict_one_incompatible(self, agent_id: str,
                                      config: Optional[EnvConfig]) -> bool:
        """Destroy one idle env incompatible with *config* to free a slot.

        Only the ready-queue pick is under ``_acquire_lock``; the slow
        ``destroy()`` runs outside it. Returns True if an env was evicted.
        """
        victim: Optional[str] = None
        skipped: List[str] = []
        async with self._acquire_lock:
            try:
                while True:
                    try:
                        env_id = self._ready_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    env_info = self._envs.get(env_id)
                    if env_info and not self._config_compatible(env_info.config, config):
                        victim = env_id
                        break
                    skipped.append(env_id)
            finally:
                for eid in skipped:
                    if eid in self._envs:
                        self._ready_queue.put_nowait(eid)
        if victim is None:
            return False
        logger.info("Evicting incompatible ready environment {} for {}",
                    victim, agent_id)
        await self.destroy(victim)
        return True

    async def _wait_for_release(self, timeout: float) -> None:
        """Wait up to *timeout* for an env to return to the ready queue.

        Used when the pool is full and nothing is evictable. Pulls and restores
        one env so the next acquire iteration re-evaluates it.
        """
        try:
            env_id = await asyncio.wait_for(self._ready_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return
        self._ready_queue.put_nowait(env_id)

    async def _wait_ready_blocking(self, agent_id: str,
                                   config: Optional[EnvConfig],
                                   start: float, remaining: float) -> Optional[EnvInfo]:
        """Block up to *remaining* for a compatible released env (static pool).

        Accumulates incompatible envs and restores them before returning.
        """
        deadline = time.time() + remaining
        skipped: List[str] = []
        async with self._acquire_lock:
            try:
                while True:
                    rem = deadline - time.time()
                    if rem <= 0:
                        return None
                    try:
                        env_id = await asyncio.wait_for(
                            self._ready_queue.get(), timeout=rem,
                        )
                    except asyncio.TimeoutError:
                        return None
                    env_info = self._envs.get(env_id)
                    if env_info and not self._config_compatible(env_info.config, config):
                        skipped.append(env_id)
                        continue
                    result = await self._assign_env(env_id, agent_id, start)
                    if result is not None:
                        return result
            finally:
                for eid in skipped:
                    if eid in self._envs:
                        self._ready_queue.put_nowait(eid)

    async def release(self, env_id: str,
                      reset: Optional[bool] = None) -> bool:
        """Release an environment back to the pool."""
        self._ensure_loop_bound()
        should_cache = False
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
            self._stats.total_releases += 1
            should_cache = self._should_cache_released_env(env_info)
            provisioner = self._env_provisioner.get(env_id, self.provisioner)
            destroy_inline = bool(
                getattr(provisioner, "destroy_inline_on_release", False)
            )

            if not should_cache:
                # Mark as pending before teardown. Docker envs still go through
                # the background destroy queue (docker rm can be slow / daemon
                # hostile). Daemon-less backends such as Apptainer opt into
                # inline destruction, so release() itself completes the lifecycle
                # and no background queue is involved.
                env_info.status = EnvStatus.PENDING_DESTROY
                env_info.assigned_agent = None
                env_info.assigned_at = None
                if not destroy_inline:
                    self._destroy_queue.put_nowait(env_id)

        if not should_cache:
            if destroy_inline:
                logger.info(
                    "Environment {} released by {}; destroying inline "
                    "(reuse_policy={}, provisioner={})",
                    env_id, agent_id, self.reuse_policy,
                    provisioner.__class__.__name__,
                )
                return await self.destroy(env_id)
            logger.info(
                "Environment {} released by {}; queued for background destroy "
                "(reuse_policy={})", env_id, agent_id, self.reuse_policy,
            )
            return True

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

        logger.info("Environment {} released by {}", env_id, agent_id)
        return True

    async def destroy(self, env_id: str) -> bool:
        """Destroy an environment permanently.

        The container removal + bookkeeping (pop from ``_envs`` / decrement
        ``total_envs``) is SHIELDED from cancellation. Otherwise a teardown
        cancelled mid-flight — e.g. by the dispatcher's ``cleanup_timeout``
        during a slow-daemon window — would remove the container in the
        background but leave a TERMINATED entry in ``_envs`` forever (a phantom
        that clogs capacity accounting and eventually stalls the whole pool).
        Shielding guarantees the pop/decrement runs to completion.
        """
        self._ensure_loop_bound()
        async with self._state_lock:
            if env_id not in self._envs:
                return False
            env_info = self._envs[env_id]
            prev = env_info.status
            env_info.status = EnvStatus.TERMINATED
            self._destroying.add(env_id)

            if env_id in self._in_use:
                self._in_use.discard(env_id)
                self._decrement_stat("in_use_envs")
            elif prev == EnvStatus.READY:
                self._decrement_stat("ready_envs")
            elif prev == EnvStatus.ERROR:
                self._decrement_stat("error_envs")

        async def _teardown() -> bool:
            try:
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
            finally:
                async with self._state_lock:
                    self._destroying.discard(env_id)

        return await asyncio.shield(_teardown())

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
        await self._cancel_task(self._reaper_task)
        for t in self._destroyer_tasks:
            await self._cancel_task(t)
        self._destroyer_tasks = []

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

    def start_destroyer(self) -> None:
        """Start the background destroyer workers (idempotent).

        Consumes ``_destroy_queue`` and runs the actual ``docker rm`` off the
        trajectory critical path, on the provisioner's dedicated destroy thread
        pool — so teardown can never starve container creation. Bounded
        concurrency keeps the daemon out of the create-burst danger zone.
        """
        self._ensure_loop_bound()
        self._running = True
        self._destroyer_tasks = [t for t in self._destroyer_tasks if not t.done()]
        while len(self._destroyer_tasks) < self._destroy_concurrency:
            self._destroyer_tasks.append(asyncio.create_task(self._destroyer_loop()))

    async def _destroyer_loop(self) -> None:
        while self._running:
            try:
                env_id = await self._destroy_queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self.destroy(env_id)
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Background destroy failed for {}: {}", env_id, e)
            finally:
                self._destroy_queue.task_done()

    def start_reaper(self) -> None:
        """Start ONLY the dead-env reaper (idempotent).

        Lightweight self-healing background sweep: it removes dead envs
        (TERMINATED/ERROR) left behind by a teardown that failed (e.g. docker rm
        kept failing while the daemon was down) so they can't permanently clog
        capacity accounting. Cheap — it just scans ``_envs`` and best-effort
        re-removes leftovers; it does NOT run per-env health checks.
        """
        self._ensure_loop_bound()
        self._running = True
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def _reaper_loop(self) -> None:
        logger.info(
            "Starting env reaper loop (interval: {}s, image-gc every {} cycles)",
            self._reaper_interval, self._gc_every_cycles,
        )
        cycle = 0
        while self._running:
            try:
                await asyncio.sleep(self._reaper_interval)
                await self._reap_abandoned_envs()
                cycle += 1
                if self._gc_every_cycles > 0 and cycle % self._gc_every_cycles == 0:
                    await self._gc_unused_images()
            except asyncio.CancelledError:
                break
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error in env reaper loop: {}", e)

    async def _gc_unused_images(self) -> None:
        """Periodically GC unused docker images when host disk is high.

        Continuous mode runs no prewarm (where image GC used to live), so without
        this the host's data disk fills with per-task images (R2E images are
        ~1.2GB each) until ``docker run`` thrashes and stalls the pipeline. This
        is a no-op unless a registry is configured AND disk exceeds the
        provisioner's threshold; it never removes images used by a live
        container (evicted ones re-pull from the registry on demand).
        """
        for prov in self._provisioners:
            gc = getattr(prov, "gc_unused_images", None)
            if gc is None:
                continue
            try:
                await gc()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Periodic image GC failed: {}", e)

    async def _reap_abandoned_envs(self) -> int:
        """Sweep dead envs (TERMINATED/ERROR) with no in-flight teardown.

        Designed to NEVER block the rollout hot path (it shares the actor loop):

        - Phase 1 (under ``_state_lock``, microseconds, NO docker): force-drop
          the dead envs from the books so capacity recovers immediately. The
          lock is held only for this fast bookkeeping (no ``await`` inside).
        - Phase 2 (OUTSIDE the lock, sequential): best-effort container ``rm``.
          One docker call at a time, so it can occupy at most 1 of the bounded
          docker-executor threads and can't starve hot-path creates. Capacity
          is already recovered, so a slow ``rm`` here can't delay training.

        A normal destroy is shielded and pops its own env, so this only catches
        residue (e.g. ``docker rm`` genuinely failed while the daemon was down).
        Envs in ``_destroying`` are skipped to avoid racing that teardown's pop.
        """
        # Phase 1: instant capacity recovery (no docker, tiny lock hold).
        victims: List[Tuple[str, BaseProvisioner]] = []
        async with self._state_lock:
            for env_id in list(self._envs):
                info = self._envs.get(env_id)
                if (info is not None
                        and info.status in (EnvStatus.TERMINATED, EnvStatus.ERROR)
                        and env_id not in self._destroying):
                    prov = self._env_provisioner.get(env_id, self.provisioner)
                    victims.append((env_id, prov))
                    self._envs.pop(env_id, None)
                    self._env_provisioner.pop(env_id, None)
                    self._decrement_stat("total_envs")
        if not victims:
            return 0
        logger.warning("Env reaper swept {} abandoned dead env(s)", len(victims))

        # Phase 2: gentle, lock-free, sequential container cleanup (best-effort).
        for env_id, prov in victims:
            try:
                await prov.destroy(env_id)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        return len(victims)

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
