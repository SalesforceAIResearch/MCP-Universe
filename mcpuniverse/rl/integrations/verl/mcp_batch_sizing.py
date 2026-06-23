"""Explicit batch sizing helpers for MCP veRL trainers.

The user-facing veRL ``actor.ppo_mini_batch_size`` is a prompt/task count.
MCP rollouts materialize ``rollout.n`` trajectories per prompt before PPO
updates, so trainer-side code must distinguish prompt, trajectory, and local
DP units instead of reusing the same name for all three.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

try:
    from omegaconf import OmegaConf
except ImportError:  # pragma: no cover - omegaconf is present in training envs.
    OmegaConf = None


# Default cap on the fraction of a training batch that may be repeat-padded.
# 0.1 = at most 10% of the batch can be duplicates before the trainer refuses
# to take a gradient step on the over-biased batch.
DEFAULT_MAX_PAD_RATIO = 0.1


class ExcessivePaddingException(Exception):
    """Raised when rollout under-collection forces a pad ratio above
    ``mcp_agent.batch_sizing.max_pad_ratio``.

    Trainers catch this at the outer ``fit`` loop and skip the step rather
    than apply a heavily-biased gradient update (e.g. if 50% of the batch
    is duplicated, those samples contribute 2x weight and dominate the
    gradient direction). The caller is expected to advance to the next
    iteration and re-collect a fresh batch.
    """

    def __init__(self, pad_size: int, batch_size: int, threshold: float):
        self.pad_size = int(pad_size)
        self.batch_size = int(batch_size)
        self.pad_ratio = float(pad_size) / float(batch_size) if batch_size else 0.0
        self.threshold = float(threshold)
        super().__init__(
            f"Pad ratio {self.pad_ratio:.3f} exceeds limit {self.threshold:.3f} "
            f"(pad_size={self.pad_size}, batch_size={self.batch_size}); "
            f"refusing to take a biased PPO step."
        )


@dataclass(frozen=True)
class MCPBatchSizing:
    """Single source of truth for derived MCP PPO batch sizes.

    Consumers (``MCPFullyAsyncRollouter``, ``MCPFullyAsyncTrainer``,
    ``MCPPPOTrainer``, ``mcp_async_main.validate_async_config``) should
    construct ONE instance via ``compute_mcp_batch_sizing`` and read
    fields from it instead of recomputing the same arithmetic locally.
    See ``issues/fully_async_batch_sizing_notes.md`` ("Open Design Issue"
    section) for rationale.

    Field units:

    * ``ppo_prompt_mini_batch_size`` - yaml-level value, in **prompt count**
    * ``rollout_n``                  - trajectories per prompt
    * ``require_batches``            - fully-async-only: how many ``ppo_mini``
                                       units the trainer pulls per fit_step
    * ``dp``                         - actor data-parallel size (FSDP
                                       ``world / sp``, Megatron ordinary
                                       ``world / (TP*CP*PP)``)
    * ``required_tasks``             - task items (= prompts) the trainer
                                       collects per fit_step
    * ``global_trajectory_minibatch``- ``ppo_prompt_mini * rollout_n``,
                                       padding/alignment unit at trainer
    * ``required_trajectories``      - ``required_tasks * rollout_n``,
                                       trajectory-unit target per fit_step
    * ``local_actor_minibatch``      - per-DP-rank trajectory count after
                                       worker init normalization (0 if not
                                       evenly divisible)
    * ``alignment_unit``             - currently == global_trajectory_minibatch
    """

    strategy: str
    ppo_prompt_mini_batch_size: int
    rollout_n: int
    require_batches: int
    dp: int
    required_tasks: int
    global_trajectory_minibatch: int
    required_trajectories: int
    local_actor_minibatch: int
    alignment_unit: int

    def to_meta_info(self, prefix: str = "fully_async/") -> dict:
        """Serialize key fields into a ``DataProto.meta_info``-style dict.

        Used by trainer's ``_get_samples_from_queue`` to tag each batch
        with the plan it was assembled against; downstream metrics /
        debugging tools can read these without re-importing the plan.
        """
        return {
            f"{prefix}required_tasks": self.required_tasks,
            f"{prefix}required_trajectories": self.required_trajectories,
            f"{prefix}global_trajectory_minibatch": self.global_trajectory_minibatch,
            f"{prefix}local_actor_minibatch": self.local_actor_minibatch,
            f"{prefix}alignment_unit": self.alignment_unit,
        }

    def describe(self) -> str:
        """One-line human-readable summary, suitable for ``logger.info`` at init."""
        return (
            f"strategy={self.strategy} "
            f"ppo_prompt_mini_batch_size={self.ppo_prompt_mini_batch_size} "
            f"rollout_n={self.rollout_n} "
            f"require_batches={self.require_batches} "
            f"required_tasks={self.required_tasks} "
            f"global_trajectory_minibatch={self.global_trajectory_minibatch} "
            f"required_trajectories={self.required_trajectories} "
            f"actor_dp={self.dp} "
            f"local_actor_minibatch={self.local_actor_minibatch} "
            f"alignment_unit={self.alignment_unit}"
        )


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _select(config: Any, path: str, default: Any = None) -> Any:
    if OmegaConf is not None:
        try:
            value = OmegaConf.select(config, path, default=default)
            return default if value is None else value
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    cur = config
    for part in path.split("."):
        if cur is None:
            return default
        if hasattr(cur, "get") and callable(cur.get):
            cur = cur.get(part, default)
        else:
            cur = getattr(cur, part, default)
        if cur is default:
            return default
    return default if cur is None else cur


def _select_first(config: Any, paths: tuple[str, ...], default: Any = None) -> Any:
    for path in paths:
        value = _select(config, path, None)
        if value is not None:
            return value
    return default


def _trainer_total_gpus(config: Any) -> int:
    return (
        _int(_select(config, "trainer.n_gpus_per_node", 0), 0)
        * _int(_select(config, "trainer.nnodes", 0), 0)
    )


def compute_fsdp_dp_size(config: Any) -> int:
    """Return the FSDP data-parallel size used for actor PPO batches."""

    total_gpus = _trainer_total_gpus(config)
    sp_size = max(1, _int(
        _select(config, "actor_rollout_ref.actor.ulysses_sequence_parallel_size", 1),
        1,
    ))
    if total_gpus <= 0 or total_gpus % sp_size != 0:
        return 0
    return total_gpus // sp_size


def compute_megatron_dp_size(config: Any) -> int:
    """Return ordinary Megatron DP size for actor PPO batches.

    Megatron-Core keeps ordinary and expert DP groups separate:
    ordinary DP = world / (TP * CP * PP)
    expert DP   = world / (ETP * EP * PP)

    Actor PPO batch splitting uses ordinary DP, not expert DP.
    """

    tp = _int(_select_first(config, (
        "actor_rollout_ref.actor.megatron.tensor_model_parallel_size",
        "actor_rollout_ref.model.tensor_model_parallel_size",
        "actor_rollout_ref.actor.tensor_model_parallel_size",
    ), 1), 1)
    pp = _int(_select_first(config, (
        "actor_rollout_ref.actor.megatron.pipeline_model_parallel_size",
        "actor_rollout_ref.model.pipeline_model_parallel_size",
    ), 1), 1)
    cp = _int(_select_first(config, (
        "actor_rollout_ref.actor.megatron.context_parallel_size",
        "actor_rollout_ref.model.context_parallel_size",
    ), 1), 1)
    product = tp * cp * pp
    total_gpus = _trainer_total_gpus(config)
    if product <= 0 or total_gpus <= 0 or total_gpus % product != 0:
        return 0
    return total_gpus // product


def compute_actor_dp_size(config: Any) -> int:
    """Return actor PPO DP size for the configured strategy."""

    strategy = _select(config, "actor_rollout_ref.actor.strategy", "fsdp2")
    if strategy == "megatron":
        return compute_megatron_dp_size(config)
    if strategy in {"fsdp", "fsdp2"}:
        return compute_fsdp_dp_size(config)
    return 0


def compute_mcp_batch_sizing(config: Any, require_batches: int | None = None) -> MCPBatchSizing:
    """Compute prompt, trajectory, and local-DP batch sizes for MCP PPO."""

    strategy = _select(config, "actor_rollout_ref.actor.strategy", "fsdp2")
    ppo_prompt_mini_batch_size = max(
        1,
        _int(_select(config, "actor_rollout_ref.actor.ppo_mini_batch_size", 1), 1),
    )
    rollout_n = max(1, _int(_select(config, "actor_rollout_ref.rollout.n", 1), 1))
    if require_batches is None:
        require_batches = _int(_select(config, "async_training.require_batches", 1), 1)
    require_batches = max(1, _int(require_batches, 1))

    required_tasks = ppo_prompt_mini_batch_size * require_batches
    global_trajectory_minibatch = ppo_prompt_mini_batch_size * rollout_n
    required_trajectories = required_tasks * rollout_n
    dp = compute_actor_dp_size(config)
    local_actor_minibatch = (
        global_trajectory_minibatch // dp
        if dp > 0 and global_trajectory_minibatch % dp == 0
        else 0
    )

    return MCPBatchSizing(
        strategy=strategy,
        ppo_prompt_mini_batch_size=ppo_prompt_mini_batch_size,
        rollout_n=rollout_n,
        require_batches=require_batches,
        dp=dp,
        required_tasks=required_tasks,
        global_trajectory_minibatch=global_trajectory_minibatch,
        required_trajectories=required_trajectories,
        local_actor_minibatch=local_actor_minibatch,
        alignment_unit=global_trajectory_minibatch,
    )


def validate_mcp_batch_sizing(
    config: Any,
    *,
    require_batches: int | None = None,
    train_prompt_batch_size: int | None = None,
) -> list[str]:
    """Validate the same batch sizing contract used at runtime."""

    sizing = compute_mcp_batch_sizing(config, require_batches=require_batches)
    errors: list[str] = []

    if sizing.dp <= 0:
        errors.append(
            f"{sizing.strategy} batch sizing: could not derive a positive actor DP size."
        )
        return errors

    if sizing.global_trajectory_minibatch % sizing.dp != 0:
        errors.append(
            f"{sizing.strategy} batch sizing: global_trajectory_minibatch="
            f"{sizing.global_trajectory_minibatch} "
            f"(ppo_prompt_mini_batch_size={sizing.ppo_prompt_mini_batch_size} * "
            f"rollout_n={sizing.rollout_n}) must be divisible by actor DP={sizing.dp}."
        )

    if sizing.local_actor_minibatch <= 0:
        errors.append(
            f"{sizing.strategy} batch sizing: local_actor_minibatch must be > 0 "
            f"(global_trajectory_minibatch={sizing.global_trajectory_minibatch}, "
            f"actor DP={sizing.dp})."
        )

    if train_prompt_batch_size is not None:
        train_prompt_batch_size = _int(train_prompt_batch_size, 0)
        train_trajectories = train_prompt_batch_size * sizing.rollout_n
        if train_trajectories <= 0:
            errors.append(
                f"{sizing.strategy} batch sizing: train_prompt_batch_size must be > 0, "
                f"got {train_prompt_batch_size}."
            )
        elif train_trajectories % sizing.alignment_unit != 0:
            errors.append(
                f"{sizing.strategy} batch sizing: train_trajectories={train_trajectories} "
                f"(train_prompt_batch_size={train_prompt_batch_size} * "
                f"rollout_n={sizing.rollout_n}) must be divisible by "
                f"alignment_unit={sizing.alignment_unit} "
                f"(ppo_prompt_mini_batch_size={sizing.ppo_prompt_mini_batch_size} * "
                f"rollout_n={sizing.rollout_n})."
            )

    return errors


def get_max_pad_ratio(config: Any) -> float:
    """Resolve ``mcp_agent.batch_sizing.max_pad_ratio`` with a sane default.

    Returns ``DEFAULT_MAX_PAD_RATIO`` (=0.1) when the field is unset or
    invalid; clamps to ``[0.0, 1.0]`` so a misconfigured ``-1`` or ``42``
    doesn't silently disable the guard or always-skip.
    """
    raw = _select_first(
        config,
        (
            "mcp_agent.batch_sizing.max_pad_ratio",
            "actor_rollout_ref.actor.mcp_max_pad_ratio",
        ),
        DEFAULT_MAX_PAD_RATIO,
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_PAD_RATIO
    if math.isnan(value):
        return DEFAULT_MAX_PAD_RATIO
    return max(0.0, min(1.0, value))


# Backward-compatible name for older fully async imports.
_compute_megatron_dp_size = compute_megatron_dp_size
