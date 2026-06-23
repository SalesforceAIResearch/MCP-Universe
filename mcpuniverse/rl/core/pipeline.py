"""Unified rollout pipeline: one engine for all modes.

A single `RolloutPipeline` drives the three-stage **init -> run -> eval**
flow, all stages overlapping:

* **init** stage (``max_init`` workers): acquire the env container + run the
  (slow, not task-bound) setup hook, then hand the trajectory to the run stage.
  Keeping acquisition off the run workers' hot path means the inference engines
  aren't left idle waiting for a container.
* **run** stage (``max_run`` workers): open the MCP connection (task-bound) +
  generate, then hand to eval.
* **eval** stage (``max_eval`` workers): evaluate, then release the env.

Two drive modes over the *same* engine:

* `run_batch` - submit a fixed batch, drain to completion, return. This is
  the batch dispatcher (in-process runner, hybrid trainer, slime batch path).
* streaming - `start` once, then `submit` trajectories over time and
  `quiesce` only at weight-sync boundaries (the fully-async rollouter).
  ``wait_for_capacity`` provides submit-side backpressure.

Container ownership flows with the trajectory: whichever stage is terminal for
it (init on acquire failure, run on connect/gen failure/timeout, eval otherwise)
runs ``cleanup()`` (idempotent) so the env returns to the pool exactly once.

This module is framework-agnostic - verl, slime, and the in-process runner all
build a ``RolloutPipeline`` and supply only thin glue (how to build a
trajectory, where to push results, the weight-sync callback).
"""
# pylint: disable=broad-exception-caught,try-except-raise

import asyncio
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from loguru import logger

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_INIT = 32
# Run stage has no fixed default: it scales with the init stage. Run-stage workers
# default to RUN_MULTIPLIER x the init workers (run is decoupled from init so every
# already-acquired container can generate while others are in per-turn tool-exec).
DEFAULT_RUN_MULTIPLIER = 2
DEFAULT_MAX_EVAL_PARALLEL = 64
DEFAULT_INIT_RETRIES = 3
DEFAULT_INIT_RETRY_DELAY = 5.0
DEFAULT_INIT_TIMEOUT = 60.0
DEFAULT_EXEC_TIMEOUT = 300.0  # 5 min per trajectory execution
DEFAULT_CLEANUP_TIMEOUT = 30.0  # 30s per trajectory cleanup


# ---------------------------------------------------------------------------
# Shared config extraction
# ---------------------------------------------------------------------------

class _PipelineParams(NamedTuple):
    max_init: int       # init-stage workers == how many CONTAINERS we hold (RAM-bound)
    max_run: int        # run-stage workers == how many trajectories GENERATE at once
    max_eval: int
    max_retries: int
    retry_delay: float
    init_timeout: float
    exec_timeout: float
    cleanup_timeout: float


def _parse_pipeline_params(cfg: Dict[str, Any], total: int) -> _PipelineParams:
    """Extract pipeline parameters from *cfg*, capping parallelism at *total*."""
    max_init = min(total, cfg.get("max_init_agents", DEFAULT_MAX_INIT))
    # Decouple generation concurrency (run stage) from container-acquisition
    # concurrency (init stage). When coupled (run_workers == init_workers ==
    # max_init), containers acquired ahead of the run stage sat idle in the
    # run_queue whenever all run workers were busy, leaving the inference GPUs
    # starved during per-turn tool-exec. Giving the run stage more workers lets
    # every ALREADY-acquired container generate, WITHOUT acquiring extra
    # containers (no extra RAM). Default run = DEFAULT_RUN_MULTIPLIER * max_init.
    raw_max_init = cfg.get("max_init_agents") or DEFAULT_MAX_INIT
    # `or` (not .get default) so an explicit None from the cfg builder still
    # falls back to the multiplier default rather than crashing min(total, None).
    max_run = cfg.get("max_run_agents") or (DEFAULT_RUN_MULTIPLIER * raw_max_init)
    max_run = max(max_init, min(total, max_run))
    return _PipelineParams(
        max_init=max_init,
        max_run=max_run,
        max_eval=min(total, cfg.get("max_eval_parallel_agents", DEFAULT_MAX_EVAL_PARALLEL)),
        max_retries=cfg.get("max_init_retries", DEFAULT_INIT_RETRIES),
        retry_delay=cfg.get("init_retry_delay", DEFAULT_INIT_RETRY_DELAY),
        init_timeout=cfg.get("init_timeout", DEFAULT_INIT_TIMEOUT),
        exec_timeout=cfg.get("exec_timeout", DEFAULT_EXEC_TIMEOUT),
        cleanup_timeout=cfg.get("cleanup_timeout", DEFAULT_CLEANUP_TIMEOUT),
    )


# ---------------------------------------------------------------------------
# Helpers (init/cleanup with retry; progress)
# ---------------------------------------------------------------------------

def _flatten(trajectories: Dict[Any, Dict[int, Any]]) -> List[Tuple[Any, int]]:
    """Flatten nested trajectory dict into ``[(instance_id, traj_id), ...]``."""
    return [
        (iid, tid)
        for iid in trajectories
        for tid in trajectories[iid]
    ]


async def _safe_cleanup(traj) -> None:
    """Best-effort agent cleanup (no-op if already cleaned).

    Used between retry attempts to clear half-built agent state. Does NOT release
    the env pool container; that is ``_run_cleanup``'s job at end-of-trajectory.
    """
    if hasattr(traj, "agent") and hasattr(traj.agent, "cleanup"):
        try:
            await asyncio.wait_for(traj.agent.cleanup(), timeout=5.0)
        except Exception:
            pass


async def _run_cleanup(traj, label: str, timeout: float = DEFAULT_CLEANUP_TIMEOUT) -> None:
    """Run terminal cleanup for a trajectory (agent + env release).

    Wraps ``traj.cleanup()`` (idempotent) so every trajectory's env is returned
    to the pool exactly once, regardless of success / failure path.
    """
    if not hasattr(traj, "cleanup"):
        return
    try:
        await asyncio.wait_for(traj.cleanup(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("Cleanup timeout for {} ({:.0f}s)", label, timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Cleanup error for {}: {}", label, exc)


async def _release_env_best_effort(traj) -> None:
    """Release a trajectory's acquired env between init-stage retries.

    A failed init attempt may have already acquired a container (before setup
    failed); releasing it before the retry re-acquires avoids leaking it.
    """
    release = getattr(traj, "_release_env", None)
    if release is None:
        return
    try:
        await asyncio.wait_for(release(), timeout=5.0)
    except Exception:
        pass


async def _init_stage_with_retry(
    traj,
    label: str,
    *,
    what: str,
    stage_fn: Callable[[], Any],
    between_attempt: Callable[[Any], Any],
    max_retries: int = DEFAULT_INIT_RETRIES,
    retry_delay: float = DEFAULT_INIT_RETRY_DELAY,
    timeout: float = DEFAULT_INIT_TIMEOUT,
    handle_spurious_cancel: bool = True,
) -> bool:
    """Run an init stage coroutine (``stage_fn()``) with timeout + retry.

    *what* labels the stage in logs ("Init" / "Env acquire" / "Connect").
    ``between_attempt(traj)`` is awaited after a failed attempt to clear partial
    state (close a half-open agent, or release a half-acquired env) before
    retrying. Returns True on success, False if all attempts failed.

    Cancel handling (only when ``handle_spurious_cancel`` is True):
        ``asyncio.CancelledError`` is BaseException-derived and is NOT caught by
        ``except Exception``. The MCP client uses anyio TaskGroups internally;
        when a sub-task fails (e.g. SSE connect to a container whose MCP server
        is still loading), anyio cancels the OUTER (worker) task. We treat it as
        a transient failure and retry, using ``Task.uncancel()`` (3.11+) to
        clear the latent cancel. Stages without an anyio MCP connection (env
        acquire) pass ``handle_spurious_cancel=False``.
    """
    for attempt in range(max_retries):
        try:
            await asyncio.wait_for(stage_fn(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "{} timeout for {} (attempt {}/{}, {:.0f}s)",
                what, label, attempt + 1, max_retries, timeout,
            )
            await between_attempt(traj)
        except asyncio.CancelledError:
            if not handle_spurious_cancel:
                raise
            # Best-effort: clear the pending cancel so the retry's awaits
            # aren't immediately re-cancelled. uncancel() is Python 3.11+.
            current = asyncio.current_task()
            uncancel = getattr(current, "uncancel", None) if current else None
            if uncancel is not None:
                try:
                    uncancel()
                except Exception:
                    pass
            if attempt < max_retries - 1:
                logger.warning(
                    "{} spurious-cancel for {} (attempt {}/{}); retry in {:.1f}s",
                    what, label, attempt + 1, max_retries, retry_delay,
                )
                await between_attempt(traj)
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    "{} spurious-cancel for {} after {} attempts",
                    what, label, max_retries,
                )
                await between_attempt(traj)
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(
                    "{} failed for {} (attempt {}/{}): {}  retry in {:.1f}s",
                    what, label, attempt + 1, max_retries, exc, retry_delay,
                )
                await between_attempt(traj)
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    "{} failed for {} after {} attempts: {}",
                    what, label, max_retries, exc,
                )
                await between_attempt(traj)
    return False


async def _acquire_with_retry(
    traj,
    label: str,
    max_retries: int = DEFAULT_INIT_RETRIES,
    retry_delay: float = DEFAULT_INIT_RETRY_DELAY,
    init_timeout: float = DEFAULT_INIT_TIMEOUT,
) -> bool:
    """Init stage: acquire env container + setup hook (not task-bound)."""
    return await _init_stage_with_retry(
        traj, label, what="Env acquire", stage_fn=traj.initialize_env,
        between_attempt=_release_env_best_effort,
        max_retries=max_retries, retry_delay=retry_delay, timeout=init_timeout,
        handle_spurious_cancel=False,
    )


async def _connect_with_retry(
    traj,
    label: str,
    max_retries: int = DEFAULT_INIT_RETRIES,
    retry_delay: float = DEFAULT_INIT_RETRY_DELAY,
    init_timeout: float = DEFAULT_INIT_TIMEOUT,
) -> bool:
    """Run stage: open the MCP connection (task-bound; anyio spurious-cancel aware)."""
    return await _init_stage_with_retry(
        traj, label, what="Connect", stage_fn=traj.connect,
        between_attempt=_safe_cleanup,
        max_retries=max_retries, retry_delay=retry_delay, timeout=init_timeout,
        handle_spurious_cancel=True,
    )


# ---------------------------------------------------------------------------
# RolloutPipeline - the one engine (batch + continuous)
# ---------------------------------------------------------------------------

class RolloutPipeline:
    """Long-lived init -> run -> eval pipeline, drivable as batch or streaming.

    * `run_batch` submits a fixed batch and drains it (the batch
      dispatcher; per-batch barrier).
    * `submit` + `quiesce` drive it as a continuous stream with no
      per-batch barrier, so a slow trajectory only holds up its own instance.

    ``on_instance_complete(iid)`` fires the moment every trajectory of an
    instance reaches a terminal stage (eval done OR failed at init/run), so the
    caller can stream that instance out immediately.
    """

    def __init__(self, cfg: Dict[str, Any], *, on_instance_complete: Optional[Callable] = None):
        self._cfg = dict(cfg) if cfg else {}
        # Streaming default: no total cap (bounded by the caller's submit pacing).
        # run_batch() re-parses with total=batch size to cap worker counts.
        self.p = _parse_pipeline_params(self._cfg, total=10 ** 9)
        self.on_instance_complete = on_instance_complete
        self._env_queue: asyncio.Queue = asyncio.Queue()
        self._run_queue: asyncio.Queue = asyncio.Queue()
        self._eval_queue: asyncio.Queue = asyncio.Queue()
        self._instance_remaining: Dict[Any, int] = {}
        self._in_flight = 0
        self._env_inflight = 0
        self._run_inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._capacity_changed = asyncio.Condition()
        self._tasks: List[asyncio.Task] = []
        self._started = False

    @property
    def in_flight(self) -> int:
        """Number of trajectories submitted but not yet terminal."""
        return self._in_flight

    @property
    def env_inflight(self) -> int:
        """Number of trajectories queued for or currently in init/acquisition."""
        return self._env_inflight

    @property
    def run_inflight(self) -> int:
        """Number of trajectories past init but not terminal."""
        return self._run_inflight

    def stats(self) -> Dict[str, int]:
        """Snapshot of pipeline stage occupancy."""
        return {
            "in_flight": self._in_flight,
            "env_inflight": self._env_inflight,
            "run_inflight": self._run_inflight,
            "env_queue_size": self._env_queue.qsize(),
            "run_queue_size": self._run_queue.qsize(),
            "eval_queue_size": self._eval_queue.qsize(),
            "active_instances": len(self._instance_remaining),
        }

    def start(self) -> None:
        """Launch the init/run/eval worker pools (idempotent)."""
        if self._started:
            return
        self._started = True
        # init workers gate container acquisition (RAM); run workers gate
        # generation (GPU). Decoupled so every in-flight container generates.
        for _ in range(self.p.max_init):
            self._tasks.append(asyncio.create_task(self._env_worker()))
        for _ in range(self.p.max_run):
            self._tasks.append(asyncio.create_task(self._run_worker()))
        for _ in range(self.p.max_eval):
            self._tasks.append(asyncio.create_task(self._eval_worker()))

    async def submit(self, iid: Any, tid: int, traj: Any, instance_size: int) -> None:
        """Feed one trajectory in. Caller submits all ``instance_size`` of an iid."""
        if iid not in self._instance_remaining:
            self._instance_remaining[iid] = instance_size
        async with self._capacity_changed:
            self._in_flight += 1
            self._env_inflight += 1
            self._idle.clear()
            self._capacity_changed.notify_all()
        await self._env_queue.put((iid, tid, traj))

    async def wait_for_capacity(
        self,
        *,
        max_total: int,
        max_env: int,
        need: int = 1,
    ) -> None:
        """Wait until there is room to submit ``need`` more init-stage items."""
        need = max(1, int(need))
        async with self._capacity_changed:
            await self._capacity_changed.wait_for(
                lambda: (
                    self._in_flight + need <= max_total
                    and self._env_inflight + need <= max_env
                )
            )

    async def quiesce(self) -> None:
        """Block until no trajectory is in flight (stop submitting first)."""
        await self._idle.wait()

    async def aclose(self) -> None:
        """Drain in-flight work, then stop the workers."""
        await self._idle.wait()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._started = False

    async def run_batch(self, trajectories: Dict[Any, Dict[int, Any]]) -> None:
        """Submit a fixed batch, drain to completion, then stop the workers."""
        items = _flatten(trajectories)
        total = len(items)
        if total == 0:
            return
        # Cap worker pools at the batch size for the one-shot case.
        self.p = _parse_pipeline_params(self._cfg, total)
        logger.info(
            "Pipeline batch: {} trajectories, init={}, run={}, eval={}",
            total, self.p.max_init, self.p.max_run, self.p.max_eval,
        )
        self.start()
        for iid, inner in trajectories.items():
            size = len(inner)
            for tid, traj in inner.items():
                await self.submit(iid, tid, traj, size)
        await self.quiesce()
        await self.aclose()
        logger.info("Pipeline batch complete")

    async def _mark_terminal(self, iid: Any, traj: Any, label: str, stage: str) -> None:
        """One terminal point per trajectory: release env, advance instance/in-flight."""
        await _run_cleanup(traj, label, self.p.cleanup_timeout)
        remaining = self._instance_remaining.get(iid)
        if remaining is not None:
            remaining -= 1
            self._instance_remaining[iid] = remaining
            if remaining <= 0:
                self._instance_remaining.pop(iid, None)
                if self.on_instance_complete is not None:
                    try:
                        await self.on_instance_complete(iid)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.error("on_instance_complete failed for {}: {}", iid, exc)
        async with self._capacity_changed:
            self._in_flight -= 1
            if stage == "env":
                self._env_inflight -= 1
            else:
                self._run_inflight -= 1
            self._in_flight = max(0, self._in_flight)
            self._env_inflight = max(0, self._env_inflight)
            self._run_inflight = max(0, self._run_inflight)
            if self._in_flight <= 0:
                self._idle.set()
            self._capacity_changed.notify_all()

    async def _env_worker(self) -> None:
        while True:
            try:
                iid, tid, traj = await self._env_queue.get()
            except asyncio.CancelledError:
                break
            label = f"{iid}-{tid}"
            handed = False
            try:
                ok = await _acquire_with_retry(
                    traj, label, self.p.max_retries, self.p.retry_delay, self.p.init_timeout,
                )
                if not ok:
                    logger.error("Skipping {}: env acquire failed", label)
                    continue
                async with self._capacity_changed:
                    self._env_inflight -= 1
                    self._run_inflight += 1
                    self._env_inflight = max(0, self._env_inflight)
                    self._capacity_changed.notify_all()
                await self._run_queue.put((iid, tid, traj))
                handed = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Init stage error for {}: {}", label, exc)
            finally:
                self._env_queue.task_done()
                if not handed:
                    await self._mark_terminal(iid, traj, label, "env")

    async def _run_worker(self) -> None:
        while True:
            try:
                iid, tid, traj = await self._run_queue.get()
            except asyncio.CancelledError:
                break
            label = f"{iid}-{tid}"
            handed = False
            try:
                ok = await _connect_with_retry(
                    traj, label, self.p.max_retries, self.p.retry_delay, self.p.init_timeout,
                )
                if not ok:
                    logger.error("Skipping {}: connect failed", label)
                    continue
                await asyncio.wait_for(traj.generate(), timeout=self.p.exec_timeout)
                if traj.result is None:
                    logger.error("Run completed but result is None for {}", label)
                else:
                    await self._eval_queue.put((iid, tid, traj))
                    handed = True
            except asyncio.TimeoutError:
                logger.error("Exec timeout for {} ({:.0f}s)", label, self.p.exec_timeout)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Run error for {}: {}", label, exc)
            finally:
                self._run_queue.task_done()
                if not handed:
                    await self._mark_terminal(iid, traj, label, "run")

    async def _eval_worker(self) -> None:
        while True:
            try:
                iid, tid, traj = await self._eval_queue.get()
            except asyncio.CancelledError:
                break
            label = f"{iid}-{tid}"
            try:
                await traj.evaluate()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Eval error for {}: {}", label, exc)
            finally:
                self._eval_queue.task_done()
                # Env stays alive throughout evaluate() so evaluators that need a
                # live env (db rows, container files, etc.) can query it; cleanup
                # releases it afterwards. Terminal (normal completion path).
                await self._mark_terminal(iid, traj, label, "run")
