"""
Shared utilities for MCP-VERL integration.
"""
# pylint: disable=broad-exception-caught

import asyncio
import concurrent.futures
import os
import random
import logging
import sys
import warnings
import numpy as np
import ray
from loguru import logger
from omegaconf import OmegaConf
from verl.protocol import DataProto


class _LazyLogger:
    """Pickle-safe logger for Ray actors.

    Ray serializes @ray.remote classes via cloudpickle. Loguru's logger
    holds file handlers (mode='a') which cannot be pickled. This wrapper
    defers the import so the unpicklable object is never captured.
    """

    def __getattr__(self, name):
        from loguru import logger as _logger  # pylint: disable=reimported,import-outside-toplevel
        return getattr(_logger, name)

    def __reduce__(self):
        return (_LazyLogger, ())


def safe_get(cfg, key: str, default=None):
    """Safely get a value from either a dict or OmegaConf object.

    Returns default if the value is None (supports YAML null values).
    """
    if cfg is None:
        return default
    if hasattr(cfg, 'get') and callable(cfg.get):
        value = cfg.get(key, default)
    else:
        value = getattr(cfg, key, default)
    return value if value is not None else default


def suppress_noisy_logs():
    """Suppress noisy logs from MCP SDK and httpx during cleanup."""
    logging.getLogger("mcp.client.sse").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def configure_task_runner_logging(config) -> None:
    """Configure loguru for the Ray TaskRunner actor.

    Two effects:

    1. ``enqueue=True`` makes logging non-blocking so Ray stdout/stderr
       backpressure cannot stall rollout postprocess.
    2. Defaults level to ``INFO`` (override with ``LOGURU_LEVEL=DEBUG``).
       Without this, loguru defaults to DEBUG, which floods the log with
       per-call ``docker inspect`` / ``docker exec curl`` polling (see
       ``mcpuniverse.mcp.env_pool.docker._run_docker_cmd``) once the
       env-pool has 100+ containers ready.

    Disable via ``mcp_agent.async_taskrunner_logging=false`` in config.
    """
    enabled = bool(OmegaConf.select(
        config, "mcp_agent.async_taskrunner_logging", default=True,
    ))
    if not enabled:
        return

    level = os.environ.get("LOGURU_LEVEL", "INFO")
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    try:
        logger.remove()
    except ValueError:
        pass
    logger.add(
        sys.stderr,
        level=level,
        format=log_format,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    logger.info(
        "TaskRunner async logging enabled (level={}); log content is "
        "preserved but Ray stdout/stderr backpressure will not block "
        "rollout postprocess.", level,
    )


def extract_reward(batch):
    """Extract reward tensor and extra info from batch.

    Compatibility shim - keeps MCP-Universe working across veRL versions.
    """
    reward_tensor = batch.batch["rm_scores"]
    reward_extra_keys = batch.meta_info.get("reward_extra_keys", [])
    reward_extra_infos_dict = {key: batch.non_tensor_batch[key] for key in reward_extra_keys}
    return reward_tensor, reward_extra_infos_dict


def compute_reward(data: DataProto, reward_fn) -> tuple:
    """Compute reward for a batch of data.

    Compatibility shim - veRL v0.7 had this, v0.8 removed it.
    """
    try:
        reward_result = reward_fn(data, return_dict=True)
        reward_tensor = reward_result["reward_tensor"]
        reward_extra_infos_dict = reward_result.get("reward_extra_info", {})
    except Exception:
        reward_tensor = reward_fn(data)
        reward_extra_infos_dict = {}
    return reward_tensor, reward_extra_infos_dict


def compute_validation_reward_metrics(
    sample_scores,
    *,
    num_requested: int | None = None,
    prefix: str = "val",
) -> dict:
    """Compute validation reward metrics with rollout failures in the denominator.

    Missing validation trajectories should not be materialized as training rows,
    but they must count as zero-reward validation attempts.  ``sample_scores``
    therefore contains only collected rows, while ``num_requested`` is the
    requested validation trajectory count.
    """
    if sample_scores is None:
        sample_scores = []
    scores_arr = np.asarray(sample_scores, dtype=float)
    num_collected = int(scores_arr.size)

    if num_requested is None:
        if num_collected == 0:
            return {}
        requested = num_collected
    else:
        requested = max(int(num_requested), num_collected)

    if requested <= 0:
        return {}

    total_reward = float(scores_arr.sum()) if num_collected else 0.0
    success_count = int((scores_arr > 0).sum()) if num_collected else 0
    num_missing = max(requested - num_collected, 0)

    metric_dict = {
        f"{prefix}/success_rate": success_count / requested,
        f"{prefix}/mean_reward": total_reward / requested,
        f"{prefix}/num_samples": requested,
        f"{prefix}/num_collected": num_collected,
        f"{prefix}/num_missing": num_missing,
    }

    if num_collected > 0:
        metric_dict[f"{prefix}/success_rate_collected"] = success_count / num_collected
        metric_dict[f"{prefix}/mean_reward_collected"] = total_reward / num_collected
    else:
        metric_dict[f"{prefix}/success_rate_collected"] = 0.0
        metric_dict[f"{prefix}/mean_reward_collected"] = 0.0

    return metric_dict


@ray.remote(num_cpus=1)
def compute_reward_async(data: DataProto, config=None, tokenizer=None, reward_fn=None):
    """Compute reward asynchronously in a Ray worker.

    Compatibility shim - veRL v0.7 had this, v0.8 removed it.
    """
    if reward_fn is None:
        assert config is not None and tokenizer is not None
        warnings.warn("using config and tokenizer with compute_reward_async is deprecated", stacklevel=2)
        from verl.trainer.ppo.reward import load_reward_manager  # pylint: disable=import-outside-toplevel
        reward_fn = load_reward_manager(
            config, tokenizer, num_examine=0, **config.reward_model.get("reward_kwargs", {})
        )
    return compute_reward(data, reward_fn)


def retry_delay(
    attempt: int,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    backoff_factor: float = 1.5,
) -> float:
    """Calculate retry delay with exponential backoff + jitter."""
    return min(base_delay * (backoff_factor ** attempt) + random.uniform(0, 1), max_delay)


def init_ray(config, *, clean_tiktoken_cache: bool = False) -> None:
    """Initialize Ray cluster with proper environment setup.

    Handles:
    - Connecting to existing clusters (via RAY_ADDRESS or cluster file)
    - Starting new clusters when none exists
    - Setting up inference engine, tiktoken, WANDB env vars in Ray runtime

    Args:
        config: Hydra/OmegaConf training config with ``ray_init`` section.
        clean_tiktoken_cache: If True, remove potentially corrupted tiktoken
            vocab files before Ray init (workaround for HarmonyError).
    """
    from verl.trainer.constants_ppo import PPO_RAY_RUNTIME_ENV  # pylint: disable=import-outside-toplevel

    if ray.is_initialized():
        return

    # -- env vars ----------------------------------------------------------
    vllm_v1 = os.environ.get("VLLM_USE_V1", "1")
    PPO_RAY_RUNTIME_ENV["env_vars"].update({"VLLM_USE_V1": vllm_v1})

    # Do not force NVTE_* backends via runtime_env. Let Megatron/TE choose
    # backend from --attention-backend (or auto) on each worker.
    PPO_RAY_RUNTIME_ENV["env_vars"].pop("NVTE_FLASH_ATTN", None)
    PPO_RAY_RUNTIME_ENV["env_vars"].pop("NVTE_FUSED_ATTN", None)
    PPO_RAY_RUNTIME_ENV["env_vars"].pop("NVTE_UNFUSED_ATTN", None)

    tiktoken_cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", "/tmp/tiktoken-rs-cache")
    PPO_RAY_RUNTIME_ENV["env_vars"]["TIKTOKEN_CACHE_DIR"] = tiktoken_cache_dir

    if clean_tiktoken_cache and os.path.exists(tiktoken_cache_dir):
        _clean_tiktoken(tiktoken_cache_dir)

    if os.environ.get("LD_LIBRARY_PATH"):
        PPO_RAY_RUNTIME_ENV["env_vars"]["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]

    # Propagate NCCL env vars to Ray workers (e.g. NCCL_SHM_DISABLE for small /dev/shm)
    nccl_keys = (
        "NCCL_SHM_DISABLE", "NCCL_P2P_LEVEL", "NCCL_DEBUG",
        "NCCL_NVLS_ENABLE", "NCCL_CUMEM_ENABLE",
    )
    for nccl_key in nccl_keys:
        nccl_val = os.environ.get(nccl_key)
        if nccl_val:
            PPO_RAY_RUNTIME_ENV["env_vars"][nccl_key] = nccl_val

    # Propagate entropy-memory switches to Ray actors. The MCPFullyAsyncTrainer
    # actor reads these from os.environ to build its worker_env (which then
    # forwards them, clobber-safe, into the Megatron WorkerDict actors at
    # base.py:643). Without runtime_env propagation the actor never sees the
    # launcher shell's `export` (Ray actors don't inherit it), so
    # MCP_FUSED_LOGPROB_ENTROPY is missing from worker_env and the fused
    # logprob+entropy kernel silently stays DISABLED -> entropy-in-loss runs the
    # OOM-prone clone path. (PYTORCH_CUDA_ALLOC_CONF avoided this only because it
    # is a hardcoded literal in worker_env.)
    for mem_key in (
        "MCP_FUSED_LOGPROB_ENTROPY",
        "MCP_FUSED_LE_CHUNK",
        "MCP_VOCAB_ENTROPY_CHUNK_NNZ",
    ):
        mem_val = os.environ.get(mem_key)
        if mem_val is not None:
            PPO_RAY_RUNTIME_ENV["env_vars"][mem_key] = mem_val

    # Propagate CPU pod Docker host config to Ray workers (for MCP env pool)
    for cpu_key in (
        "CPU_POD_DOCKER_HOST",
        "CPU_POD_HOST",
        "CPU_POD_DOCKER_HOST_2",
        "CPU_POD_HOST_2",
        "DOCKER_API_VERSION",
    ):
        cpu_val = os.environ.get(cpu_key)
        if cpu_val:
            PPO_RAY_RUNTIME_ENV["env_vars"][cpu_key] = cpu_val

    # Propagate MCP tool API keys to Ray workers so the rollouter actor's
    # env_pool.resolve_forward_env_vars() can read them from os.environ and
    # forward them into each docker_pool MCP container (search tools such as
    # serper / jina + their summary LLM). Without this, the rollouter
    # ray worker has no keys to forward and every search/scrape fails.
    for tool_key in (
        "SERPER_API_KEY",
        "SERPER_BASE_URL",
        "JINA_API_KEY",
        "JINA_BASE_URL",
        "OPENAI_API_KEY",
        "SUMMARY_LLM_BASE_URL",
        "SUMMARY_LLM_MODEL_NAME",
        "SUMMARY_LLM_API_KEY",
        "SERP_API_KEY",
        # Fixed docker_pool container server surface for pool reuse (stateful envs).
        # The hydra list override doesn't survive the driver->rollouter config
        # hand-off, so the rollouter reads this comma-separated fallback from
        # os.environ instead. See env_pool_runtime._resolve_env_servers.
        "MCP_ENV_SERVERS",
        # Robust docker build context (e.g. a Dockerfile that does COPY .). Same hand-off
        # caveat as MCP_ENV_SERVERS. See env_pool_runtime.initialize.
        "MCP_BUILD_CONTEXT",
        # Image registry for the env pool (pull-before-build / push-after-build /
        # GC). Same hand-off caveat. See env_pool_runtime.initialize.
        "MCP_ENV_REGISTRY",
        # Per-env aux control-port templates (JSON object, e.g. MY_CTRL_PORT).
        # Same hand-off caveat: the nested control_port_vars dict doesn't survive
        # the driver->rollouter hand-off, so without this the worker gets no
        # unique control port and every env collides on the image-default port in
        # apptainer's shared netns. See env_pool_runtime._resolve_control_port_vars.
        "MCP_CONTROL_PORT_VARS",
        # Pool-slot acquisition timeout (raise for many-distinct-image envs).
        "MCP_ENV_ACQUISITION_TIMEOUT",
        # Docker host endpoints the rollouter uses to provision env containers.
        "CPU_POD_DOCKER_HOST",
        "CPU_POD_HOST",
    ):
        tool_val = os.environ.get(tool_key)
        if tool_val:
            PPO_RAY_RUNTIME_ENV["env_vars"][tool_key] = tool_val

    wandb_api_key = os.environ.get("WANDB_API_KEY")
    if wandb_api_key:
        PPO_RAY_RUNTIME_ENV["env_vars"]["WANDB_API_KEY"] = wandb_api_key
        logger.info("WANDB_API_KEY added to Ray runtime environment")
    else:
        logger.warning("WANDB_API_KEY not found in environment variables")

    # -- connect / start ---------------------------------------------------
    ray_address = os.environ.get("RAY_ADDRESS")
    # veRL 0.7+ moved ray_init under ray_kwargs; support both layouts
    if hasattr(config, "ray_init"):
        ray_cfg = config.ray_init
    elif hasattr(config, "ray_kwargs") and hasattr(config.ray_kwargs, "ray_init"):
        ray_cfg = config.ray_kwargs.ray_init
    else:
        ray_cfg = {}
    num_cpus = ray_cfg.get("num_cpus", None) if hasattr(ray_cfg, "get") else None

    if ray_address:
        logger.info(f"Connecting to existing Ray cluster at {ray_address}")
        ray.init(address=ray_address, runtime_env=PPO_RAY_RUNTIME_ENV)
        logger.info("Ray connected to existing cluster")
        return

    # Check for existing cluster via cluster file
    ray_cluster_file = "/tmp/ray/ray_current_cluster"
    if os.path.exists(ray_cluster_file):
        with open(ray_cluster_file, "r", encoding="utf-8") as f:
            ray_address = f.read().strip()
        if not ray_address:
            raise RuntimeError(f"Ray cluster file is empty: {ray_cluster_file}")
        logger.info(f"Existing Ray cluster detected via {ray_cluster_file}: {ray_address}")
        ray.init(address=ray_address, runtime_env=PPO_RAY_RUNTIME_ENV)
        logger.info("Ray connected to existing cluster")
        return

    # Auto-detect or start new
    try:
        logger.info("Attempting to auto-detect Ray cluster...")
        ray.init(runtime_env=PPO_RAY_RUNTIME_ENV)
        logger.info("Ray connected to existing cluster (auto-detected)")
    except (ConnectionError, ValueError) as e:
        error_msg = str(e).lower()
        if "num_cpus" in error_msg or "existing cluster" in error_msg:
            logger.warning(f"Retrying Ray init without num_cpus: {e}")
            ray.init(runtime_env=PPO_RAY_RUNTIME_ENV)
        elif isinstance(e, ConnectionError) and num_cpus is not None:
            logger.info(f"No existing cluster found, starting new with {num_cpus} CPUs")
            ray.init(runtime_env=PPO_RAY_RUNTIME_ENV, num_cpus=num_cpus)
        else:
            raise

    logger.info("Ray initialized")


def _clean_tiktoken(cache_dir: str) -> None:
    """Remove potentially corrupted tiktoken vocab files."""
    try:
        for root, _dirs, files in os.walk(cache_dir):
            for fname in files:
                if fname.endswith('.vocab') or 'vocab' in fname.lower():
                    fpath = os.path.join(root, fname)
                    try:
                        os.remove(fpath)
                        logger.info(f"Removed tiktoken vocab file: {fpath}")
                    except OSError as e:
                        logger.warning(f"Failed to remove {fpath}: {e}")
    except Exception as e:
        logger.warning(f"Error cleaning tiktoken cache: {e}")


def run_async_safely(coro):
    """Run an async coroutine safely, handling existing event loops (e.g. in Ray actors).

    Tries ``asyncio.run()`` first; falls back to running in a new thread
    if an event loop is already running.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    # Event loop already running (e.g. inside Ray actor) -- run in thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def flatten_dataproto_metrics_inplace(dataproto) -> None:
    """Flatten nested-list metric values produced by per-rank dispatch concat.

    Failure mode this guards against (controller side, i.e. trainer process):

    - ``verl/single_controller/base/decorator.py:collect_lazy_compute_data_proto``
      gathers ``DataProto`` from each ray worker and routes through
      ``_concat_data_proto_or_future -> DataProto.concat``.
    - ``DataProto.concat`` (verl/protocol.py) merges per-worker
      ``meta_info["metrics"]`` via ``list_of_dict_to_dict_of_list``:
      each worker's ``{key: [m0, m1, ...]}`` becomes
      ``{key: [[r0_m0, r0_m1, ...], [r1_m0, r1_m1]]}``.
    - With Megatron + dynamic-bsz, different DP / PP-last ranks can produce
      different numbers of micro-batches, so the per-worker lists are of
      different lengths -> ragged ``list[list[float]]``.
    - ``verl.utils.metric.utils.reduce_metrics`` then feeds the value to
      ``np.mean`` / ``np.max`` / ``np.min`` and crashes with::

          ValueError: setting an array element with a sequence.
          The detected shape was (2,) + inhomogeneous part.

    This helper recursively flattens any nested list/tuple/numpy/tensor
    value into a flat list of Python scalars so the downstream reducer
    works regardless of cross-rank micro-batch count.

    Where to call it:
    - **Trainer side** (after dispatch concat returns, before reduce_metrics).
      See ``MCPFullyAsyncTrainer._fit_update_actor``.
    - Also called defensively on worker side in
      ``MCPMegatronDetachActorWorker.update_actor`` for nested tensor/array
      flattening within a single worker, even though that alone is not
      sufficient because concat re-nests.

    Notes:
    - Only operates on ``meta_info["metrics"]``; other meta_info keys are
      untouched.
    - Non-numeric or unknown structures are left as-is (wrapped in a 1-list)
      so we never lose data; the downstream reducer will then fail with a
      clearer error.
    - Modifies ``dataproto.meta_info["metrics"]`` in-place when possible.
    """
    if dataproto is None:
        return
    meta_info = getattr(dataproto, "meta_info", None)
    if not isinstance(meta_info, dict):
        return
    metrics = meta_info.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return

    def _flatten(val):
        # tensor / numpy scalar / array  ->  python list of scalars
        if hasattr(val, "detach"):
            try:
                val = val.detach().cpu()
            except Exception:  # pylint: disable=broad-except
                pass
        if hasattr(val, "tolist"):
            try:
                val = val.tolist()
            except Exception:  # pylint: disable=broad-except
                pass
        if isinstance(val, (list, tuple)):
            out = []
            for item in val:
                flat = _flatten(item)
                if isinstance(flat, list):
                    out.extend(flat)
                else:
                    out.append(flat)
            return out
        return val

    cleaned: dict = {}
    for key, val in metrics.items():
        flat = _flatten(val)
        # Ensure final shape is always a list (downstream np.mean expects iterable)
        if not isinstance(flat, list):
            flat = [flat]
        cleaned[key] = flat
    meta_info["metrics"] = cleaned


def flatten_and_reduce_metrics_inplace(dataproto, target_metrics: dict) -> None:
    """Flatten + verl-reduce a per-rank-concat DataProto's metrics into a dict.

    Module-level helper (not a class method) so callers can test the
    flatten-then-reduce sequence directly. The class method version
    ``MCPFullyAsyncTrainer._reduce_actor_or_critic_metrics`` is just a
    thin wrapper that delegates here; testing the class method runs into
    ray's global class-method tracing wrapper which makes unit-test
    invocation awkward.

    Steps:
    1. Flatten ragged ``list[list[float]]`` values produced by
       ``DataProto.concat -> list_of_dict_to_dict_of_list`` -- see
       ``flatten_dataproto_metrics_inplace`` docstring for the full
       failure mode.
    2. Apply verl's ``reduce_metrics`` which dispatches to
       ``np.mean / np.max / np.min`` based on key substring.
    3. ``target_metrics.update(reduced)`` to merge in-place; existing keys
       in ``target_metrics`` are preserved (only collisions are overwritten).
    """
    from verl.utils.metric import reduce_metrics  # pylint: disable=import-outside-toplevel

    flatten_dataproto_metrics_inplace(dataproto)
    reduced = reduce_metrics(dataproto.meta_info["metrics"])
    target_metrics.update(reduced)
