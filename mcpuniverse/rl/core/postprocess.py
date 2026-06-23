"""Agentic RL Rollout Postprocessing.

This module turns completed rollout trajectories into a
`TokenizedRolloutBatch` ready for any RL trainer. It depends only on
the `TokenizableTrajectory` Protocol for per-trajectory data and the
`TrajectoryResult` dataclass for the flattened record schema.
"""

from collections.abc import Callable, Iterable
from typing import Any

from .types import TokenizableTrajectory, TokenizedRolloutBatch

PRIVATE_ROLLOUT_METRIC_KEYS = ("missing_results",)


def tokenize_trajectory_result(
    traj: TokenizableTrajectory,
    *,
    tokenizer: Any,
    formatter: Any,
    rollout_mode: str = "text",
) -> tuple[list[int], list[int], list[int]]:
    """Tokenize a completed trajectory into ``(prompt_ids, response_ids, response_mask)``.

    Three branches, tried in order:

    1. **Token (TITO) mode** - ``traj.get_tito_tokens()`` returns pre-computed
       IDs from the LLM wrapper; no tokenizer/formatter needed.
    2. **Text mode with trace** - format the captured trace via ``formatter``
       and tokenize with the chat template, producing a loss mask that
       excludes the prompt and tool outputs.
    3. **Bare fallback** - tokenize the raw instruction and response directly
       with ``add_special_tokens``; full response participates in the loss.
    """
    if traj.result is None:
        raise ValueError("Cannot tokenize trajectory without a result")

    if rollout_mode == "token":
        tito_tokens = traj.get_tito_tokens()
        if tito_tokens is not None:
            return tito_tokens

    trace_text = traj.get_trace_text()
    instruction = traj.get_instruction()

    if trace_text:
        formatter_output = formatter.format_trace(trace_text, instruction)
        prompt_tokens, response_tokens, response_mask = formatter.tokenize_with_mask(
            formatter_output, tokenizer,
        )
        return (
            list(prompt_tokens),
            list(response_tokens),
            [int(mask) for mask in response_mask],
        )

    prompt_tokens = tokenizer.encode(instruction, add_special_tokens=True)
    response_text = traj.get_response_text()
    response_tokens = tokenizer.encode(response_text, add_special_tokens=False)
    response_mask = [1] * len(response_tokens)
    return list(prompt_tokens), list(response_tokens), response_mask


def trajectory_result_to_rollout_record(
    result: Any,
    *,
    instance_id: Any,
    trajectory_id: int,
) -> dict[str, Any]:
    """Materialize one trajectory result into a flat rollout record dict.

    Prefers `TrajectoryResult.to_rollout_record` (which owns the schema);
    falls back to ``to_dict()`` + key injection for test doubles or alternative result shapes.
    """
    if hasattr(result, "to_rollout_record"):
        return result.to_rollout_record(
            instance_id=instance_id,
            trajectory_id=trajectory_id,
        )

    record = result.to_dict() if hasattr(result, "to_dict") else {}
    record["instance_id"] = instance_id
    record["trajectory_id"] = trajectory_id
    return record


def pop_private_rollout_metrics(
    metrics: dict[str, Any],
    private_metric_keys: Iterable[str] = PRIVATE_ROLLOUT_METRIC_KEYS,
) -> dict[str, Any]:
    """Remove private collection details from public rollout metrics.

    Keys listed in ``private_metric_keys`` (e.g. ``missing_results``) are
    popped from ``metrics`` and returned separately, so the public metrics
    stay clean for wandb/tensorboard reporting while the orchestration layer keeps the diagnostic data.
    """
    private_metrics: dict[str, Any] = {}
    for key in private_metric_keys:
        if key in metrics:
            private_metrics[key] = metrics.pop(key)
    return private_metrics


def collect_tokenized_rollout_results(
    trajectories: dict[Any, dict[int, TokenizableTrajectory]],
    batch: list[dict[str, Any]],
    num_trajectories: int,
    *,
    tokenizer: Any = None,
    formatter: Any = None,
    rollout_mode: str = "text",
    tokenize_trajectory_fn: Callable[[Any, Any, int], tuple[Any, Any, Any]] | None = None,
) -> TokenizedRolloutBatch:
    """Aggregate completed trajectories into a tokenized batch.

    For each ``(instance_id, traj_id)`` pair:

    * skip and record as missing if no result is attached;
    * tokenize via ``tokenize_trajectory_fn`` (caller-provided override) or
      the default `tokenize_trajectory_result`;
    * flatten the result via `trajectory_result_to_rollout_record`;
    * accumulate batch-level metrics (mean reward, success rate, missing).
    """
    tokenized = TokenizedRolloutBatch()
    metrics: dict[str, Any] = {
        "num_instances": len(batch),
        "num_trajectories": len(batch) * num_trajectories,
        "total_reward": 0.0,
        "success_count": 0,
    }

    missing_results: list[str] = []
    for instance_id, trajs in trajectories.items():
        for traj_id, traj in trajs.items():
            result = traj.result
            if not result:
                missing_results.append(f"{instance_id}-{traj_id}")
                continue

            if tokenize_trajectory_fn is None:
                prompt_tokens, response_tokens, response_mask = tokenize_trajectory_result(
                    traj,
                    tokenizer=tokenizer,
                    formatter=formatter,
                    rollout_mode=rollout_mode,
                )
            else:
                prompt_tokens, response_tokens, response_mask = tokenize_trajectory_fn(
                    traj, instance_id, traj_id,
                )
            tokenized.prompt_ids.append(prompt_tokens)
            tokenized.response_ids.append(response_tokens)
            tokenized.response_mask.append(response_mask)

            # Per-response-token rollout log-probs (TITO/token mode) for TIS /
            # train-inference mismatch correction. Aligned with response_tokens;
            # 0.0 where unavailable (non-TITO or length mismatch).
            get_lp = getattr(traj, "get_tito_logprobs", None)
            traj_logprobs = get_lp() if callable(get_lp) else None
            if traj_logprobs is not None and len(traj_logprobs) == len(response_tokens):
                tokenized.response_logprobs.append([float(x) for x in traj_logprobs])
            else:
                tokenized.response_logprobs.append([0.0] * len(response_tokens))

            get_re = getattr(traj, "get_tito_routed_experts", None)
            tokenized.routed_experts.append(get_re() if callable(get_re) else None)

            reward = getattr(result, "reward", 0.0)
            tokenized.rewards.append(reward)
            tokenized.group_ids.append(str(instance_id))

            tokenized.trajectories.append(
                trajectory_result_to_rollout_record(
                    result,
                    instance_id=instance_id,
                    trajectory_id=traj_id,
                )
            )

            reward_value = float(reward)
            metrics["total_reward"] += reward_value
            if reward_value > 0:
                metrics["success_count"] += 1

    total_expected = len(batch) * num_trajectories
    total_collected = len(tokenized.rewards)
    metrics["num_trajectories"] = total_expected
    metrics["num_collected"] = total_collected
    metrics["num_missing"] = total_expected - total_collected
    metrics["mean_reward"] = metrics["total_reward"] / max(total_collected, 1)
    metrics["success_rate"] = metrics["success_count"] / max(total_collected, 1)
    if missing_results:
        metrics["missing_results"] = missing_results
    tokenized.metrics = metrics

    return tokenized


__all__ = [
    "collect_tokenized_rollout_results",
    "pop_private_rollout_metrics",
    "tokenize_trajectory_result",
    "trajectory_result_to_rollout_record",
]
