"""Config adaptation helpers for MCP veRL integration."""

import os
from typing import Any, Tuple

from omegaconf import OmegaConf

from mcpuniverse.rl.core.config import RolloutConfig

from .utils import safe_get


def as_plain_dict(cfg: Any) -> dict:
    """Convert dict/OmegaConf config fragments to a plain dict."""
    if cfg is None:
        return {}
    if OmegaConf.is_config(cfg):
        return OmegaConf.to_container(cfg, resolve=True) or {}
    if isinstance(cfg, dict):
        return dict(cfg)
    return {}


def build_rollout_config_from_verl(
    config: Any,
    *,
    model_name: str,
    num_trajectories: int,
    fallback_rollout_mode: str = "text",
) -> Tuple[RolloutConfig, str]:
    """Build MCP ``RolloutConfig`` from the veRL trainer config.

    Returns:
        ``(rollout_config, rollout_mode)``.  The caller owns storing the
        returned rollout mode on the loop manager.
    """
    mcp_cfg = config.get("mcp_agent", {})
    mcp_raw = as_plain_dict(mcp_cfg)

    rollout_mode = safe_get(mcp_raw, "rollout_mode", fallback_rollout_mode)

    dispatcher_raw = as_plain_dict(safe_get(mcp_raw, "dispatcher", {}))
    env_pool_raw = as_plain_dict(safe_get(mcp_raw, "env_pool", {}))

    mcp_transport = safe_get(mcp_raw, "mcp_transport", "stdio")
    max_init_agents = safe_get(
        dispatcher_raw,
        "max_init_agents",
        safe_get(mcp_raw, "max_init_agents", 32),
    )

    dispatcher_cfg = {
        "max_init_agents": max_init_agents,
        # Run-stage concurrency, decoupled from init/container concurrency.
        # None -> pipeline default (2 * max_init_agents).
        "max_run_agents": safe_get(dispatcher_raw, "max_run_agents", None),
        "max_eval_parallel_agents": safe_get(
            dispatcher_raw, "max_eval_parallel_agents", 64,
        ),
        "max_init_retries": safe_get(dispatcher_raw, "max_init_retries", 3),
        "init_retry_delay": safe_get(dispatcher_raw, "init_retry_delay", 5.0),
        "init_timeout": safe_get(dispatcher_raw, "init_timeout", 300),
        "exec_timeout": safe_get(dispatcher_raw, "exec_timeout", 1500),
        "cleanup_timeout": safe_get(dispatcher_raw, "cleanup_timeout", 30.0),
    }

    env_pool_cfg = dict(env_pool_raw)
    env_pool_cfg.setdefault(
        "docker_host",
        os.environ.get("CPU_POD_DOCKER_HOST", "unix:///var/run/docker.sock"),
    )
    env_pool_cfg.setdefault("host", os.environ.get("CPU_POD_HOST", "localhost"))
    env_pool_cfg.setdefault("base_port", 9000)
    env_pool_cfg.setdefault("startup_timeout", 180.0)
    env_pool_cfg.setdefault("reuse_existing", True)
    env_pool_cfg.setdefault("reset_on_release", False)
    env_pool_cfg.setdefault("gateway_mode", "sse")
    env_pool_cfg.setdefault("network", "bridge")
    env_pool_cfg.setdefault("pool_buffer", 5)
    env_pool_cfg.setdefault(
        "acquisition_timeout",
        float(dispatcher_cfg["init_timeout"]),
    )
    env_pool_cfg.setdefault("auto_scale", True)
    if "max_pool_size" not in env_pool_cfg:
        env_pool_cfg["max_pool_size"] = (
            int(max_init_agents) + int(env_pool_cfg["pool_buffer"])
        )

    rollout_config = RolloutConfig.from_dict({
        "llm_type": safe_get(mcp_raw, "llm_type", "OpenAI"),
        "llm_config": safe_get(mcp_raw, "llm_config", {"model_name": model_name}),
        "rollout_mode": rollout_mode,
        "agent_mode": safe_get(mcp_raw, "agent_mode", "react_train"),
        "agent_config": safe_get(mcp_raw, "agent_config", {}),
        "formatter_type": safe_get(mcp_raw, "formatter_type", "gpt_oss"),
        "mcp_servers": safe_get(mcp_raw, "mcp_servers", []),
        "use_sample_servers": safe_get(mcp_raw, "use_sample_servers", True),
        "mcp_transport": mcp_transport,
        "mcp_gateway_address": safe_get(mcp_raw, "mcp_gateway_address", ""),
        "generator": {
            "num_trajectories": num_trajectories,
            "val_num_trajectories": safe_get(mcp_raw, "val_num_trajectories", 1),
            "max_iterations": safe_get(mcp_raw, "max_iterations", 10),
        },
        "dispatcher": dispatcher_cfg,
        "env_pool": env_pool_cfg,
    })
    return rollout_config, rollout_mode
