"""Async dispatcher for concurrent trajectory execution.

Inspired by https://github.com/NovaSky-AI/SkyRL/tree/main/skyrl-agent/skyrl_agent/dispatcher

Dispatch strategies:
- async_pipeline: Queue-based worker pool, run/eval stages overlap. Default.
- async_batch:    All trajectories launched simultaneously, no concurrency cap.
- sequential:     One at a time. For debugging.
"""
# pylint: disable=broad-exception-caught,try-except-raise

import asyncio
import time
from typing import Any, Dict, Callable, List, NamedTuple, Tuple
from loguru import logger


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DISPATCHER_REGISTRY: Dict[str, Callable] = {}


def register_dispatcher(name: str) -> Callable:
    """Register a dispatcher function under *name*."""
    def decorator(fn: Callable) -> Callable:
        DISPATCHER_REGISTRY[name] = fn
        return fn
    return decorator


def get_dispatcher(name: str) -> Callable:
    """Look up a dispatcher by *name*.  Raises ``ValueError`` if unknown."""
    if name not in DISPATCHER_REGISTRY:
        raise ValueError(
            f"Unknown dispatcher: {name}. "
            f"Available: {list(DISPATCHER_REGISTRY.keys())}"
        )
    return DISPATCHER_REGISTRY[name]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_PARALLEL = 32
DEFAULT_MAX_EVAL_PARALLEL = 64
DEFAULT_INIT_RETRIES = 3
DEFAULT_INIT_RETRY_DELAY = 5.0
DEFAULT_INIT_TIMEOUT = 60.0
DEFAULT_EXEC_TIMEOUT = 300.0  # 5 min per trajectory execution


# ---------------------------------------------------------------------------
# Shared config extraction
# ---------------------------------------------------------------------------

class _DispatcherParams(NamedTuple):
    max_parallel: int
    max_eval: int
    max_retries: int
    retry_delay: float
    init_timeout: float
    exec_timeout: float


def _parse_dispatcher_params(cfg: Dict[str, Any], total: int) -> _DispatcherParams:
    """Extract common dispatcher parameters from *cfg*, capping parallelism at *total*."""
    return _DispatcherParams(
        max_parallel=min(total, cfg.get("max_parallel_agents", DEFAULT_MAX_PARALLEL)),
        max_eval=min(total, cfg.get("max_eval_parallel_agents", DEFAULT_MAX_EVAL_PARALLEL)),
        max_retries=cfg.get("max_init_retries", DEFAULT_INIT_RETRIES),
        retry_delay=cfg.get("init_retry_delay", DEFAULT_INIT_RETRY_DELAY),
        init_timeout=cfg.get("init_timeout", DEFAULT_INIT_TIMEOUT),
        exec_timeout=cfg.get("exec_timeout", DEFAULT_EXEC_TIMEOUT),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten(trajectories: Dict[Any, Dict[int, Any]]) -> List[Tuple[Any, int]]:
    """Flatten nested trajectory dict into ``[(instance_id, traj_id), ...]``."""
    return [
        (iid, tid)
        for iid in trajectories
        for tid in trajectories[iid]
    ]


async def _safe_cleanup(traj) -> None:
    """Best-effort agent cleanup (no-op if already cleaned)."""
    if hasattr(traj, "agent") and hasattr(traj.agent, "cleanup"):
        try:
            await asyncio.wait_for(traj.agent.cleanup(), timeout=5.0)
        except Exception:
            pass


async def _init_with_retry(
    traj,
    label: str,
    max_retries: int = DEFAULT_INIT_RETRIES,
    retry_delay: float = DEFAULT_INIT_RETRY_DELAY,
    init_timeout: float = DEFAULT_INIT_TIMEOUT,
) -> bool:
    """Initialize *traj* with timeout and retry.

    Returns True on success, False if all attempts failed.
    On failure the agent is cleaned up so the worker can move on.
    """
    for attempt in range(max_retries):
        try:
            await asyncio.wait_for(
                traj.initialize_trajectory(), timeout=init_timeout,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Init timeout for {} (attempt {}/{}, {:.0f}s)",
                label, attempt + 1, max_retries, init_timeout,
            )
            await _safe_cleanup(traj)
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(
                    "Init failed for {} (attempt {}/{}): {}  retry in {:.1f}s",
                    label, attempt + 1, max_retries, exc, retry_delay,
                )
                await _safe_cleanup(traj)
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    "Init failed for {} after {} attempts: {}",
                    label, max_retries, exc,
                )
                await _safe_cleanup(traj)
    return False


class _Progress:
    """Thread-safe (single-threaded async) progress counter with periodic logging."""

    def __init__(self, total: int, stage: str = "run"):
        self.total = total
        self.stage = stage
        self._done = 0
        self._errors = 0
        self._t0 = time.monotonic()

    def __str__(self) -> str:
        """Return a summary of current progress."""
        elapsed = time.monotonic() - self._t0
        tps = self._done / elapsed if elapsed > 0 else 0
        return (f"[{self.stage}] {self._done}/{self.total} "
                f"(errors={self._errors}) {elapsed:.1f}s, {tps:.2f} traj/s")

    def tick(self, error: bool = False) -> None:
        """Record completion of one item, logging progress periodically."""
        self._done += 1
        if error:
            self._errors += 1
        elapsed = time.monotonic() - self._t0
        # Log every 10% or every 10 tasks, whichever comes first
        interval = max(1, min(self.total // 10, 10))
        if self._done % interval == 0 or self._done == self.total:
            tps = self._done / elapsed if elapsed > 0 else 0
            logger.info(
                "[{}] {}/{} done (errors={}) {:.1f}s elapsed, {:.2f} traj/s",
                self.stage, self._done, self.total,
                self._errors, elapsed, tps,
            )


# ---------------------------------------------------------------------------
# async_pipeline  (default, recommended)
# ---------------------------------------------------------------------------

@register_dispatcher("async_pipeline")
async def async_pipeline_dispatcher(
    cfg: Dict[str, Any],
    trajectories: Dict[Any, Dict[int, Any]],
) -> None:
    """Queue-based pipeline dispatcher.

    - ``max_parallel_agents`` run workers (init + generate, same task for
      cancel-scope safety).
    - ``max_eval_parallel_agents`` eval workers.
    - Run and eval stages **overlap**: as soon as a trajectory finishes
      generate, it enters the eval queue while other workers keep running.
    - Init retry with configurable timeout / retry count / delay.
    - Progress logging.
    """
    items = _flatten(trajectories)
    total = len(items)
    if total == 0:
        return

    p = _parse_dispatcher_params(cfg, total)

    logger.info(
        "Pipeline: {} trajectories, run_workers={}, eval_workers={}",
        total, p.max_parallel, p.max_eval,
    )

    run_queue: asyncio.Queue = asyncio.Queue()
    eval_queue: asyncio.Queue = asyncio.Queue()
    progress = _Progress(total, "run")

    for item in items:
        await run_queue.put(item)

    # ---- run worker ----
    _eval_submitted = [0]  # mutable counter visible to closures

    async def run_worker() -> None:
        while True:
            try:
                iid, tid = await run_queue.get()
            except asyncio.CancelledError:
                break

            label = f"{iid}-{tid}"
            traj = trajectories[iid][tid]
            error = False

            try:
                ok = await _init_with_retry(
                    traj, label, p.max_retries, p.retry_delay, p.init_timeout,
                )
                if not ok:
                    logger.error("Skipping {}: init failed", label)
                    error = True
                    continue

                await asyncio.wait_for(
                    traj.generate_trajectory(), timeout=p.exec_timeout,
                )
                if traj.result is None:
                    logger.error("Run completed but result is None for {}", label)
                    error = True
                else:
                    await eval_queue.put((iid, tid))
                    _eval_submitted[0] += 1
            except asyncio.TimeoutError:
                logger.error(
                    "Exec timeout for {} ({:.0f}s), skipping", label, p.exec_timeout,
                )
                await _safe_cleanup(traj)
                error = True
            except asyncio.CancelledError:
                logger.warning("Run cancelled for {}", label)
                error = True
                raise
            except Exception as exc:
                logger.error("Run error for {}: {}", label, exc)
                await _safe_cleanup(traj)
                error = True
            finally:
                progress.tick(error=error)
                run_queue.task_done()

    # ---- eval worker ----
    eval_progress = _Progress(total, "eval")

    async def eval_worker() -> None:
        while True:
            try:
                iid, tid = await eval_queue.get()
            except asyncio.CancelledError:
                break

            label = f"{iid}-{tid}"
            try:
                await trajectories[iid][tid].evaluate_trajectory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Eval error for {}: {}", label, exc)
            finally:
                eval_progress.tick()
                eval_queue.task_done()

    # ---- launch ----
    run_tasks = [asyncio.create_task(run_worker()) for _ in range(p.max_parallel)]
    eval_tasks = [asyncio.create_task(eval_worker()) for _ in range(p.max_eval)]

    await run_queue.join()
    for t in run_tasks:
        t.cancel()

    # Update eval total to actual submitted count (some items may have
    # been skipped due to init failure).
    eval_progress.total = _eval_submitted[0]

    await eval_queue.join()
    for t in eval_tasks:
        t.cancel()

    await asyncio.gather(*run_tasks, *eval_tasks, return_exceptions=True)
    logger.info("Pipeline complete")


# ---------------------------------------------------------------------------
# async_batch
# ---------------------------------------------------------------------------

@register_dispatcher("async_batch")
async def async_batch_dispatcher(
    cfg: Dict[str, Any],
    trajectories: Dict[Any, Dict[int, Any]],
) -> None:
    """All trajectories launched concurrently, no concurrency limit.

    Includes init retry and progress logging.
    """
    items = _flatten(trajectories)
    total = len(items)
    if total == 0:
        return

    p = _parse_dispatcher_params(cfg, total)
    progress = _Progress(total, "batch")

    logger.info("Batch: {} trajectories (unlimited concurrency)", total)

    async def run_one(iid, tid) -> None:
        label = f"{iid}-{tid}"
        traj = trajectories[iid][tid]
        error = False
        try:
            ok = await _init_with_retry(
                traj, label, p.max_retries, p.retry_delay, p.init_timeout,
            )
            if not ok:
                error = True
                return
            await asyncio.wait_for(
                traj.generate_trajectory(), timeout=p.exec_timeout,
            )
            await traj.evaluate_trajectory()
        except asyncio.TimeoutError:
            logger.error(
                "Exec timeout for {} ({:.0f}s), skipping", label, p.exec_timeout,
            )
            await _safe_cleanup(traj)
            error = True
        except Exception as exc:
            logger.error("Error for {}: {}", label, exc)
            await _safe_cleanup(traj)
            error = True
        finally:
            progress.tick(error=error)

    await asyncio.gather(
        *[asyncio.create_task(run_one(iid, tid)) for iid, tid in items],
        return_exceptions=True,
    )
    logger.info("Batch complete")


# ---------------------------------------------------------------------------
# sequential
# ---------------------------------------------------------------------------

@register_dispatcher("sequential")
async def sequential_dispatcher(
    cfg: Dict[str, Any],
    trajectories: Dict[Any, Dict[int, Any]],
) -> None:
    """One trajectory at a time.  For debugging."""
    items = _flatten(trajectories)
    total = len(items)
    if total == 0:
        return

    p = _parse_dispatcher_params(cfg, total)
    progress = _Progress(total, "seq")

    logger.info("Sequential: {} trajectories", total)

    for iid, tid in items:
        label = f"{iid}-{tid}"
        traj = trajectories[iid][tid]
        error = False
        try:
            ok = await _init_with_retry(
                traj, label, p.max_retries, p.retry_delay, p.init_timeout,
            )
            if not ok:
                error = True
                continue
            await asyncio.wait_for(
                traj.generate_trajectory(), timeout=p.exec_timeout,
            )
            await traj.evaluate_trajectory()
        except asyncio.TimeoutError:
            logger.error(
                "Exec timeout for {} ({:.0f}s), skipping", label, p.exec_timeout,
            )
            await _safe_cleanup(traj)
            error = True
        except Exception as exc:
            logger.error("Error for {}: {}", label, exc)
            await _safe_cleanup(traj)
            error = True
        finally:
            progress.tick(error=error)

    logger.info("Sequential complete")
