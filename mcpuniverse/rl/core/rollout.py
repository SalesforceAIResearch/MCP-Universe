"""Agentic RL Rollout Orchestration Helpers.

This module owns the "samples in, trajectories/tokenized batch out" plumbing
that every rollout caller needs - whether the high-level ``RolloutEngine`` in
``mcpuniverse.rl.runner`` or a framework integration like
``mcpuniverse.rl.integrations.verl.mcp_loop_manager``.

Callers compose these helpers with their own batching, tokenization, and result
handling code.

Layering:
    core/types.py        - data protocols (RolloutSample, TrajectoryResult, ...)
    core/trajectory.py   - single trajectory lifecycle
    core/pipeline.py     - concurrent execution of N trajectories
    core/postprocess.py  - tokenization + metrics collection
    core/rollout.py      - this file: orchestration glue
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Union

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.evaluator import Evaluator

from .config import TrajectoryConfig, MCP_TRANSPORT_SSE, MCP_TRANSPORT_DOCKER_POOL
from .pipeline import RolloutPipeline
from .postprocess import collect_tokenized_rollout_results
from .trace_logger import TrajectoryTraceLogger
from .trajectory import Trajectory, create_trajectory
from .types import (
    RolloutBatchResult,
    RolloutSample,
    TokenizedRolloutBatch,
    TrajectoryResult,
)


RolloutSampleInput = Union[Dict[str, Any], RolloutSample]


# ---------------------------------------------------------------------------
# Sample normalization
# ---------------------------------------------------------------------------


def materialize_rollout_sample(sample: RolloutSampleInput) -> Dict[str, Any]:
    """Convert a neutral rollout sample into a flat dict payload."""
    if isinstance(sample, RolloutSample):
        return sample.to_dict()
    return dict(sample)


def materialize_rollout_samples(
    samples: Iterable[RolloutSampleInput],
) -> List[Dict[str, Any]]:
    """Convert rollout samples into flat dict payloads for trajectory code."""
    return [materialize_rollout_sample(sample) for sample in samples]


def build_rollout_instance_data(instance: RolloutSampleInput) -> Dict[str, Any]:
    """Return trajectory data with the canonical ``instruction`` field populated."""
    instance = materialize_rollout_sample(instance)
    return {
        **instance,
        "instruction": instance.get("instruction") or instance.get("question", ""),
    }


# ---------------------------------------------------------------------------
# MCP server / dispatcher config preparation
# ---------------------------------------------------------------------------


def _server_config_to_dict(server: Any) -> Dict[str, Any]:
    """Normalize a server config object, dict, or name into a plain dict."""
    if isinstance(server, dict):
        return dict(server)
    if hasattr(server, "name"):
        return {
            "name": server.name,
            "tools": getattr(server, "tools", None),
            "permissions": getattr(server, "permissions", None),
            "transport": getattr(server, "transport", "stdio"),
        }
    return {"name": server}


def prepare_mcp_servers_for_sample(
    sample: RolloutSampleInput,
    *,
    default_servers: Optional[Iterable[Any]] = None,
    use_default_servers: bool = False,
    mcp_transport: str = "stdio",
    mcp_gateway_address: str = "",
    env_pool_active: bool = False,
) -> List[Dict[str, Any]]:
    """Prepare MCP server configs for one rollout sample."""
    sample = materialize_rollout_sample(sample)
    servers = sample.get("mcp_servers", [])
    if hasattr(servers, "tolist"):
        servers = servers.tolist()
    if servers is None:
        servers = []

    if not servers and use_default_servers and default_servers:
        servers = [_server_config_to_dict(server) for server in default_servers]

    if mcp_transport == MCP_TRANSPORT_DOCKER_POOL and env_pool_active:
        return [
            {**server, "transport": "sse"}
            if isinstance(server, dict)
            else {"name": server, "transport": "sse"}
            for server in servers
        ]

    if mcp_transport == MCP_TRANSPORT_SSE and mcp_gateway_address:
        return [
            {**server, "transport": "sse", "gateway_address": mcp_gateway_address}
            if isinstance(server, dict)
            else {
                "name": server,
                "transport": "sse",
                "gateway_address": mcp_gateway_address,
            }
            for server in servers
        ]

    return list(servers)


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    """Read a config value from dict-like or attribute-style config objects."""
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def build_rollout_dispatcher_config(
    dispatcher_config: Any,
    *,
    num_instances: int,
    num_trajectories: int,
    include_max_eval_parallel_agents: bool = False,
    include_init_timeout: bool = False,
) -> Dict[str, Any]:
    """Build dispatcher config while preserving caller-specific optional fields.

    ``exec_timeout`` and ``cleanup_timeout`` are always plumbed through so
    integrations don't need to opt in - they are universally consumed by
    the RolloutPipeline. Without this, user-facing knobs like
    ``mcp_agent.dispatcher.exec_timeout: 900`` silently fall back to the
    hard-coded defaults in ``core/pipeline.py`` (exec_timeout 300s,
    cleanup_timeout 30s).
    """
    cfg = {
        "max_init_agents": _config_value(dispatcher_config, "max_init_agents"),
        # Generation-stage concurrency, decoupled from init/container concurrency
        # (see core/pipeline.py::_parse_pipeline_params). None -> default
        # 2*max_init_agents. Tune via mcp_agent.dispatcher.max_run_agents.
        "max_run_agents": _config_value(dispatcher_config, "max_run_agents"),
        "max_init_retries": _config_value(dispatcher_config, "max_init_retries"),
        "init_retry_delay": _config_value(dispatcher_config, "init_retry_delay"),
        "exec_timeout": _config_value(dispatcher_config, "exec_timeout", 300.0),
        "cleanup_timeout": _config_value(dispatcher_config, "cleanup_timeout", 30.0),
        "num_instances": num_instances,
        "num_trajectories": num_trajectories,
    }
    if include_max_eval_parallel_agents:
        cfg["max_eval_parallel_agents"] = _config_value(
            dispatcher_config, "max_eval_parallel_agents",
        )
    if include_init_timeout:
        # 300s preserves veRL's historical default (cold-start of Docker env +
        # MCP server can blow past the dispatcher's 60s default).
        cfg["init_timeout"] = _config_value(dispatcher_config, "init_timeout", 300)
    return cfg


# ---------------------------------------------------------------------------
# Trajectory construction and dispatch
# ---------------------------------------------------------------------------


def create_rollout_trajectory(  # pylint: disable=too-many-arguments
    *,
    instance: RolloutSampleInput,
    instance_id: Any,
    trajectory_id: int,
    llm: Any,
    mcp_manager: MCPManager,
    mcp_servers: List[Dict[str, Any]],
    agent_mode: Any,
    max_iterations: int,
    formatter_type: str,
    rollout_mode: str,
    agent_config: Optional[Dict[str, Any]] = None,
    evaluators: Optional[List[Evaluator]] = None,
    val_mode: bool = False,
    tokenizer: Optional[Any] = None,
    acquire_env: Optional[Any] = None,
    release_env: Optional[Any] = None,
    trace_logger: Optional[TrajectoryTraceLogger] = None,
    trajectory_config_kwargs: Optional[Dict[str, Any]] = None,
    attach_tito_llm: bool = False,
    before_evaluate_hook: Optional[Any] = None,
    cleanup_hook: Optional[Any] = None,
    setup_hook: Optional[Any] = None,
) -> Trajectory:
    """Build one trajectory from rollout inputs."""
    instance = materialize_rollout_sample(instance)
    traj_cfg = TrajectoryConfig(
        instance_id=instance_id,
        trajectory_id=trajectory_id,
        max_iterations=max_iterations,
        agent_mode=agent_mode,
        formatter_type=formatter_type,
        rollout_mode=rollout_mode,
        **(trajectory_config_kwargs or {}),
    )
    traj = create_trajectory(
        cfg=traj_cfg,
        data=build_rollout_instance_data(instance),
        agent_mode=agent_mode,
        llm=llm,
        mcp_manager=mcp_manager,
        mcp_servers=mcp_servers,
        agent_config=agent_config,
        evaluators=evaluators,
        val_mode=val_mode,
        tokenizer=tokenizer,
        acquire_env=acquire_env,
        release_env=release_env,
        trace_logger=trace_logger,
        before_evaluate_hook=before_evaluate_hook,
        cleanup_hook=cleanup_hook,
        setup_hook=setup_hook,
    )
    if attach_tito_llm and rollout_mode == "token":
        traj._tito_llm = llm  # pylint: disable=protected-access
    return traj


def build_rollout_trajectories(
    batch: List[RolloutSampleInput],
    *,
    num_trajectories: int,
    mcp_manager: MCPManager,
    agent_mode: Any,
    max_iterations: int,
    formatter_type: str,
    rollout_mode: str,
    agent_config: Optional[Dict[str, Any]] = None,
    val_mode: bool = False,
    tokenizer: Optional[Any] = None,
    trace_logger: Optional[TrajectoryTraceLogger] = None,
    get_mcp_servers: Optional[Any] = None,
    get_evaluators: Optional[Any] = None,
    get_before_evaluate_hook: Optional[Any] = None,
    get_cleanup_hook: Optional[Any] = None,
    get_setup_hook: Optional[Any] = None,
    create_llm_for_trajectory: Optional[Any] = None,
    build_env_callbacks: Optional[Any] = None,
    trajectory_config_kwargs: Optional[Any] = None,
    attach_tito_llm: bool = False,
) -> Dict[Any, Dict[int, Trajectory]]:
    """Build rollout trajectories for a batch without dispatching them."""
    trajectories: Dict[Any, Dict[int, Trajectory]] = {}
    batch = materialize_rollout_samples(batch)

    for batch_idx, instance in enumerate(batch):
        instance_id = instance.get("instance_id", batch_idx)
        trajectories[instance_id] = {}

        mcp_servers = get_mcp_servers(instance) if get_mcp_servers else []
        evaluators = get_evaluators(instance) if get_evaluators else []
        before_evaluate_hook = (
            get_before_evaluate_hook(instance) if get_before_evaluate_hook else None
        )
        cleanup_hook = get_cleanup_hook(instance) if get_cleanup_hook else None
        setup_hook = get_setup_hook(instance) if get_setup_hook else None

        for traj_id in range(num_trajectories):
            llm = create_llm_for_trajectory(val_mode) if create_llm_for_trajectory else None
            if llm is None:
                raise ValueError("create_llm_for_trajectory must return an LLM instance")

            acquire_env_fn = None
            release_env_fn = None
            if build_env_callbacks is not None:
                acquire_env_fn, release_env_fn = build_env_callbacks(
                    instance_id, traj_id, instance, mcp_servers,
                )

            if trajectory_config_kwargs is None:
                traj_kwargs = None
            else:
                traj_kwargs = trajectory_config_kwargs(instance, instance_id, traj_id)

            traj = create_rollout_trajectory(
                instance=instance,
                instance_id=instance_id,
                trajectory_id=traj_id,
                llm=llm,
                mcp_manager=mcp_manager,
                mcp_servers=mcp_servers,
                agent_mode=agent_mode,
                max_iterations=max_iterations,
                formatter_type=formatter_type,
                rollout_mode=rollout_mode,
                agent_config=agent_config,
                evaluators=evaluators,
                val_mode=val_mode,
                tokenizer=tokenizer,
                acquire_env=acquire_env_fn,
                release_env=release_env_fn,
                trace_logger=trace_logger,
                trajectory_config_kwargs=traj_kwargs,
                attach_tito_llm=attach_tito_llm,
                before_evaluate_hook=before_evaluate_hook,
                cleanup_hook=cleanup_hook,
                setup_hook=setup_hook,
            )
            trajectories[instance_id][traj_id] = traj

    return trajectories


async def dispatch_rollout_trajectories(
    trajectories: Dict[Any, Dict[int, Trajectory]],
    *,
    dispatcher_cfg: Dict[str, Any],
) -> None:
    """Run the unified RolloutPipeline (batch mode) for already-built trajectories."""
    pipe = RolloutPipeline(
        dispatcher_cfg,
        on_instance_complete=dispatcher_cfg.get("on_instance_complete"),
    )
    await pipe.run_batch(trajectories)


async def run_rollout_trajectories(
    batch: List[RolloutSampleInput],
    *,
    dispatcher_cfg: Dict[str, Any],
    **build_kwargs: Any,
) -> Dict[Any, Dict[int, Trajectory]]:
    """Build trajectories, run the RolloutPipeline, and return them."""
    batch = materialize_rollout_samples(batch)
    trajectories = build_rollout_trajectories(batch, **build_kwargs)
    await dispatch_rollout_trajectories(
        trajectories,
        dispatcher_cfg=dispatcher_cfg,
    )
    return trajectories


async def run_tokenized_rollout_batch(
    samples: List[RolloutSampleInput],
    *,
    dispatcher_cfg: Dict[str, Any],
    num_trajectories: int,
    tokenizer: Optional[Any] = None,
    formatter: Optional[Any] = None,
    rollout_mode: str = "text",
    tokenize_trajectory_fn: Optional[Any] = None,
    instance_sink: Optional[Any] = None,
    **build_kwargs: Any,
) -> TokenizedRolloutBatch:
    """Run rollout samples and collect a tokenized batch.

    When *instance_sink* is provided, each instance is
    tokenized and handed to ``instance_sink(instance_id, TokenizedRolloutBatch)``
    the moment all of its trajectories reach a terminal stage - so a completed
    instance can be pushed downstream immediately instead of waiting for the
    whole batch. The full batch is still returned for metrics/return
    compatibility. When None, behaviour is identical to the batch path.
    """
    batch = materialize_rollout_samples(samples)
    trajectories = build_rollout_trajectories(
        batch,
        num_trajectories=num_trajectories,
        rollout_mode=rollout_mode,
        tokenizer=tokenizer,
        **build_kwargs,
    )

    if instance_sink is not None:
        async def _on_instance_complete(instance_id: Any) -> None:
            # Tokenize just this one instance (collect only counts len(batch),
            # so a 1-element placeholder list is fine) and stream it out.
            inst_tok = collect_tokenized_rollout_results(
                {instance_id: trajectories[instance_id]},
                [None],
                num_trajectories,
                tokenizer=tokenizer,
                formatter=formatter,
                rollout_mode=rollout_mode,
                tokenize_trajectory_fn=tokenize_trajectory_fn,
            )
            await instance_sink(instance_id, inst_tok)

        dispatcher_cfg = {**dispatcher_cfg, "on_instance_complete": _on_instance_complete}

    await dispatch_rollout_trajectories(
        trajectories,
        dispatcher_cfg=dispatcher_cfg,
    )
    return collect_tokenized_rollout_results(
        trajectories,
        batch,
        num_trajectories,
        tokenizer=tokenizer,
        formatter=formatter,
        rollout_mode=rollout_mode,
        tokenize_trajectory_fn=tokenize_trajectory_fn,
    )


# ---------------------------------------------------------------------------
# Result aggregation and metrics
# ---------------------------------------------------------------------------


def flatten_completed_trajectory_results(
    trajectories: Dict[Any, Dict[int, Trajectory]],
) -> List[TrajectoryResult]:
    """Return completed trajectory results from a dispatcher trajectory map."""
    return [
        traj.result
        for trajs in trajectories.values()
        for traj in trajs.values()
        if traj.result is not None
    ]


def compute_rollout_metrics(
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

    finish_reason_counts: Dict[str, int] = defaultdict(int)
    for result in results:
        finish_reason_counts[result.finish_reason] += 1

    instance_rewards: Dict[Any, List[float]] = defaultdict(list)
    for result in results:
        instance_rewards[result.instance_id].append(result.reward)
    num_all_resolved = sum(
        1 for rewards in instance_rewards.values() if all(reward > 0 for reward in rewards)
    )
    num_none_resolved = sum(
        1 for rewards in instance_rewards.values() if all(reward == 0 for reward in rewards)
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


def collect_rollout_batch_result(
    trajectories: Dict[Any, Dict[int, Trajectory]],
    *,
    num_instances: Optional[int] = None,
) -> RolloutBatchResult:
    """Collect completed trajectories into a framework-neutral batch result."""
    results = flatten_completed_trajectory_results(trajectories)
    instance_count = len(trajectories) if num_instances is None else num_instances
    return RolloutBatchResult(
        trajectories=results,
        metrics=compute_rollout_metrics(results, instance_count),
    )


__all__ = [
    "RolloutSampleInput",
    # Sample normalization
    "materialize_rollout_sample",
    "materialize_rollout_samples",
    "build_rollout_instance_data",
    # MCP server / dispatcher config
    "prepare_mcp_servers_for_sample",
    "build_rollout_dispatcher_config",
    # Trajectory construction and dispatch
    "create_rollout_trajectory",
    "build_rollout_trajectories",
    "dispatch_rollout_trajectories",
    "run_rollout_trajectories",
    "run_tokenized_rollout_batch",
    # Result aggregation
    "flatten_completed_trajectory_results",
    "compute_rollout_metrics",
    "collect_rollout_batch_result",
]
