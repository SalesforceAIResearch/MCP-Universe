"""
Data classes and batch assembly for MCP Fully Async Training.

Provides MCPRolloutSample (wrapping a single instance's rollout output) and
assemble_mcp_training_batch (concatenating multiple samples into one training
batch with re-padding and async meta_info).
"""

# pylint: disable=broad-exception-caught,unused-argument

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import torch

from verl import DataProto
from verl.trainer.ppo.ray_trainer import compute_response_mask

from ..data_proto_padding import repad_data_protos
from ..utils import _LazyLogger

logger = _LazyLogger()

MCP_BATCH_END_SENTINEL = b"__mcp_batch_end__"


@dataclass
class MCPRolloutSample:
    """A single instance's rollout output ready for queue transmission.

    Each sample wraps the DataProto produced by fully async per-instance
    postprocess for one task instance (with its ``num_trajectories``
    trajectories).

    Attributes:
        data: DataProto from MCPLoopManager._postprocess() containing
            prompts, responses, attention_mask, position_ids, response_mask,
            uid, rewards, etc. Shape is [num_trajectories, seq_len].
        param_version: The rollouter's parameter version when this sample
            was generated.
        instance_id: Original instance identifier for GRPO grouping.
        sample_id: Unique sample identifier (e.g. "sample_{epoch}_{step}").
        epoch: The epoch in which this sample was generated.
        processing_time: Wall-clock time for generating this sample (seconds).
        instance_data: Original input data dict for retry on cancellation.
        rollout_status: Snapshot of rollouter statistics at sample time.
    """

    data: DataProto
    # param_version tracks staleness: gap between this version and the trainer's
    # current version is the off-policy degree for importance sampling.
    param_version: int = 0
    instance_id: str = ""
    sample_id: str = ""
    epoch: int = 0
    # processing_time helps identify long-tail instances (e.g. complex multi-turn tool calls).
    processing_time: float = 0.0
    # instance_data retains the original input for retry if rollout is cancelled.
    instance_data: Optional[dict] = None
    rollout_status: dict = field(default_factory=dict)


def _truncate_overlength_protos(
    data_protos: list[DataProto],
    max_seq_len: int,
) -> list[DataProto]:
    """Drop trajectories whose full sequence length exceeds max_seq_len.

    Rather than silently truncating token content (which would corrupt
    attention_mask / position_ids alignment), we drop the entire trajectory.
    This is safe because PPO batches contain many trajectories and losing
    a few outliers is preferable to OOM or assertion failures.
    """
    kept: list[DataProto] = []
    dropped = 0
    for dp in data_protos:
        seq_len = dp.batch["input_ids"].shape[-1]
        if seq_len > max_seq_len:
            dropped += dp.batch["input_ids"].shape[0]  # number of trajectories
            logger.warning(
                "Dropping {} trajectories with seq_len={} > max_seq_len={}",
                dp.batch["input_ids"].shape[0], seq_len, max_seq_len,
            )
            continue
        kept.append(dp)
    if dropped:
        logger.warning("Total dropped trajectories due to overlength: {}", dropped)
    return kept


def _enforce_token_budget(
    data_protos: list[DataProto],
    max_total_tokens: int,
) -> list[DataProto]:
    """Drop the longest DataProtos until total token count fits the budget.

    After re-padding, all DataProtos share the same seq_len (the global max).
    A single outlier trajectory can inflate every other trajectory's memory
    via padding.  This function drops DataProtos from longest to shortest
    (by their *original* trajectory count x padded seq_len) until the total
    token count is within budget.

    This prevents OOM caused by re-padding amplification: e.g. 1 trajectory
    at 35K tokens padding 63 trajectories from 200 to 35K each.
    """
    if max_total_tokens <= 0 or not data_protos:
        return data_protos

    def _token_count(dp: DataProto) -> int:
        return dp.batch["input_ids"].shape[0] * dp.batch["input_ids"].shape[-1]

    total = sum(_token_count(dp) for dp in data_protos)
    if total <= max_total_tokens:
        return data_protos

    # Sort by per-proto seq_len descending (drop longest padded protos first).
    indexed = sorted(enumerate(data_protos), key=lambda x: x[1].batch["input_ids"].shape[-1], reverse=True)

    drop_indices: set[int] = set()
    for idx, dp in indexed:
        if total <= max_total_tokens:
            break
        total -= _token_count(dp)
        drop_indices.add(idx)

    if drop_indices:
        dropped_traj = sum(data_protos[i].batch["input_ids"].shape[0] for i in drop_indices)
        logger.warning(
            "Token budget enforcement: dropped {} DataProtos ({} trajectories) "
            "to fit budget {}. Remaining total tokens: {}",
            len(drop_indices), dropped_traj, max_total_tokens, total,
        )

    return [dp for i, dp in enumerate(data_protos) if i not in drop_indices]


def assemble_mcp_training_batch(  # pylint: disable=too-many-branches
    samples: list[MCPRolloutSample],
    tokenizer: Any,
    config: Any,
) -> DataProto:
    """Concatenate multiple MCPRolloutSample objects into one training batch.

    Each sample is a small DataProto (1 instance x num_trajectories).
    This function:
      1. Concatenates all sample DataProtos via DataProto.concat()
      2. Recomputes response_mask if missing
      3. Adds async meta_info (param versions, processing time stats,
         staleness tracking)

    Args:
        samples: List of MCPRolloutSample objects.
        tokenizer: Tokenizer instance (for potential re-padding).
        config: Training configuration.

    Returns:
        A single DataProto suitable for the PPO training pipeline.
    """
    start_time = time.time()

    if not samples:
        raise ValueError("Empty samples list provided for batch assembly")

    logger.info("Assembling batch from {} MCPRolloutSample objects", len(samples))

    # Filter out samples where rollout failed (e.g. TITO timeout, MCP tool error).
    valid_samples = [s for s in samples if s.data is not None and s.data.batch is not None]
    if not valid_samples:
        raise ValueError("No valid samples with tensor data for batch assembly")

    if len(valid_samples) < len(samples):
        logger.warning(
            "{} samples had no tensor data, using {}/{}",
            len(samples) - len(valid_samples), len(valid_samples), len(samples),
        )

    data_protos = [s.data for s in valid_samples]

    # Overlength drop DISABLED: rollout side (vLLM max_model_len) already caps
    # trajectory length. Megatron handles variable-length sequences via packing
    # (use_remove_padding + flash attn THD + CP). Pre-dropping here is lossy
    # and wrong -- it throws away 80%+ of legitimate long multi-turn G4 traj.
    # Keeping the call commented for reference.
    # max_token_len = getattr(config.actor_rollout_ref.actor, "ppo_max_token_len_per_gpu", None)
    # megatron_cfg = getattr(config.actor_rollout_ref.actor, "megatron", None)
    # cp_size = getattr(megatron_cfg, "context_parallel_size", 1) if megatron_cfg is not None else 1
    # if max_token_len is not None:
    #     effective_max = int(max_token_len) * int(cp_size)
    #     data_protos = _truncate_overlength_protos(data_protos, effective_max)

    # Re-pad: different generate_sequences() calls use dynamic padding, so
    # DataProtos may have different seq_len and cannot be torch.cat'd directly.
    pad_id = getattr(tokenizer, "pad_token_id", 0) or 0
    data_protos = repad_data_protos(data_protos, pad_token_id=pad_id)

    # Note: token budget enforcement was removed - Megatron with TP>=2 + SP
    # and use_dynamic_bsz=true can handle long sequences (100K+) without
    # dropping.  Re-padding inflation is acceptable because dynamic batching
    # packs sequences by total token count, not by count x max_seq_len.

    global_token_num: list[int] = []
    for dp in data_protos:
        values = dp.meta_info.get("global_token_num")
        if values is not None:
            global_token_num.extend(int(value) for value in values)

    # Strip conflicting meta_info keys before concat: DataProto.concat() asserts
    # that all non-"metrics" keys are identical, but per-sample rollout_metrics
    # and timing values naturally differ in async mode.
    if len(data_protos) > 1:
        reference = {}
        conflicting: set[str] = set()
        for dp in data_protos:
            for k, v in dp.meta_info.items():
                if k == "metrics":
                    continue  # concat handles "metrics" specially
                if k not in reference:
                    reference[k] = v
                else:
                    try:
                        if reference[k] != v:
                            conflicting.add(k)
                    except Exception:
                        # Values that are not comparable (e.g. tensors) are treated as conflicting.
                        conflicting.add(k)
        if conflicting:
            logger.info("Stripping conflicting meta_info keys before concat: {}", conflicting)
            for dp in data_protos:
                for k in conflicting:
                    dp.meta_info.pop(k, None)

    # Reconcile tensor (batch) keys before concat. DataProto.concat() -> torch.cat
    # over TensorDicts requires IDENTICAL batch keys on every proto (strict
    # _check_keys). Optional keys -- notably `routed_experts` for R3 routing replay
    # -- can be present on some trajectories and absent on others: SGLang
    # occasionally fails to return routing for a turn, so _build_routed_experts_tensor
    # drops that whole instance's key (any(x is None) -> return None). Mixed presence
    # crashed the run mid-training (KeyError in tensordict._check_keys after 10 good
    # steps). Intersect to the common key set: a key missing from any proto is dropped
    # from all. This is safe -- the Megatron R3 replay (REPLAY_FORWARD) falls back to
    # natural routing when `routed_experts` is absent (router_replay_patch.py), so the
    # worst case is ONE step trained without routing replay, never a crash. Batch size
    # is preserved (no trajectories dropped), and it self-heals next step.
    if len(data_protos) > 1:
        key_sets = [set(dp.batch.keys()) for dp in data_protos if dp.batch is not None]
        if key_sets:
            common_keys = set.intersection(*key_sets)
            extra_keys = set.union(*key_sets) - common_keys
            if extra_keys:
                missing_count = {
                    k: sum(1 for ks in key_sets if k not in ks) for k in extra_keys
                }
                logger.warning(
                    "Inconsistent batch tensor keys across trajectories; dropping {} "
                    "before concat (missing on N/{} protos: {}). R3 replay falls back "
                    "to natural routing for any dropped 'routed_experts' this step.",
                    sorted(extra_keys), len(key_sets), missing_count,
                )
                for dp in data_protos:
                    if dp.batch is None:
                        continue
                    for k in extra_keys:
                        if k in dp.batch.keys():
                            dp.batch.pop(k, None)

    final_batch = DataProto.concat(data_protos)

    if final_batch.batch is not None and "response_mask" not in final_batch.batch.keys():
        final_batch.batch["response_mask"] = compute_response_mask(final_batch)

    if (
        final_batch.batch is not None
        and global_token_num
        and len(global_token_num) == int(final_batch.batch.batch_size[0])
    ):
        final_batch.meta_info["global_token_num"] = global_token_num
    elif final_batch.batch is not None and "attention_mask" in final_batch.batch:
        final_batch.meta_info["global_token_num"] = (
            torch.sum(final_batch.batch["attention_mask"], dim=-1).tolist()
        )

    # Staleness tracking: record param_version per sample and per trajectory for the
    # trainer to monitor off-policy degree after async rollout.
    param_versions = [s.param_version for s in valid_samples]
    processing_times = [s.processing_time for s in valid_samples]

    # Prefer per-trajectory versions from non_tensor_batch when available;
    # one instance produces num_trajectories rows, each tagged with a version.
    trajectory_param_versions = param_versions  # fallback
    if "param_version" in final_batch.non_tensor_batch:
        trajectory_param_versions = list(final_batch.non_tensor_batch["param_version"])

    # tp50/tp95/tp99 help detect long-tail instances (complex multi-turn tool calls).
    processing_time_stats = {}
    if processing_times:
        processing_time_stats = {
            "fully_async/processing_time/avg": np.mean(processing_times),
            "fully_async/processing_time/max": np.max(processing_times),
            "fully_async/processing_time/min": np.min(processing_times),
            "fully_async/processing_time/tp50": np.percentile(processing_times, 50),
            "fully_async/processing_time/tp95": np.percentile(processing_times, 95),
            "fully_async/processing_time/tp99": np.percentile(processing_times, 99),
        }

    rollout_status = {}
    if valid_samples[0].rollout_status:
        rollout_status = {
            f"fully_async/{key}": value
            for key, value in valid_samples[0].rollout_status.items()
        }

    # param_version_diversity: number of distinct versions in this batch;
    # higher values indicate more spread-out staleness.
    final_batch.meta_info.update({
        "rollout_param_versions": param_versions,
        "param_version_diversity": len(set(param_versions)) if param_versions else 0,
        "trajectory_param_versions": trajectory_param_versions,
        **processing_time_stats,
        **rollout_status,
    })

    elapsed = time.time() - start_time
    logger.info("Batch assembly completed in {:.2f}s, batch_size={}", elapsed, len(final_batch))

    return final_batch
