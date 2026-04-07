"""
Shared utilities for MCP-VERL integration.
"""
# pylint: disable=broad-exception-caught

import asyncio
import concurrent.futures
import os
import random
import logging
import warnings
import ray
from loguru import logger
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


def extract_reward(batch):
    """Extract reward tensor and extra info from batch.

    Compatibility shim — keeps MCP-Universe working across veRL versions.
    """
    reward_tensor = batch.batch["rm_scores"]
    reward_extra_keys = batch.meta_info.get("reward_extra_keys", [])
    reward_extra_infos_dict = {key: batch.non_tensor_batch[key] for key in reward_extra_keys}
    return reward_tensor, reward_extra_infos_dict


def compute_reward(data: DataProto, reward_fn) -> tuple:
    """Compute reward for a batch of data.

    Compatibility shim — veRL v0.7 had this, v0.8 removed it.
    """
    try:
        reward_result = reward_fn(data, return_dict=True)
        reward_tensor = reward_result["reward_tensor"]
        reward_extra_infos_dict = reward_result.get("reward_extra_info", {})
    except Exception:
        reward_tensor = reward_fn(data)
        reward_extra_infos_dict = {}
    return reward_tensor, reward_extra_infos_dict


@ray.remote(num_cpus=1)
def compute_reward_async(data: DataProto, config=None, tokenizer=None, reward_fn=None):
    """Compute reward asynchronously in a Ray worker.

    Compatibility shim — veRL v0.7 had this, v0.8 removed it.
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
        logger.info("Existing Ray cluster detected (via cluster file)")
        ray.init(runtime_env=PPO_RAY_RUNTIME_ENV)
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
