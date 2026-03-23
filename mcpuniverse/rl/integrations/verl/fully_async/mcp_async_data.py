"""
Data classes and batch assembly for MCP Fully Async Training.

Provides MCPRolloutSample (wrapping a single instance's rollout output)
and assemble_mcp_training_batch (concatenating multiple samples into one
training batch with re-padding and async meta_info).
"""

# pylint: disable=broad-exception-caught,unused-argument

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import torch
from tensordict import TensorDict

from verl import DataProto
from verl.trainer.ppo.ray_trainer import compute_response_mask

from ..utils import _LazyLogger

logger = _LazyLogger()


@dataclass
class MCPRolloutSample:
    """A single instance's rollout output ready for queue transmission.

    Each sample wraps the DataProto produced by MCPLoopManager for one
    instance (with its ``num_trajectories`` trajectories).

    Attributes:
        data: DataProto from MCPLoopManager._postprocess() containing
            prompts, responses, attention_mask, position_ids, response_mask,
            uid, rewards, etc.  Shape is [num_trajectories, seq_len].
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


def _repad_data_protos(
    data_protos: list[DataProto],
    pad_token_id: int = 0,
) -> list[DataProto]:
    """Re-pad DataProtos to uniform sequence length for concatenation.

    Different ``generate_sequences()`` calls use dynamic padding, so each
    DataProto may have a different seq_len.  Three groups of tensors exist:

    * **Prompt-group** (``prompts``): left-padded to ``max_prompt_len``.
    * **Response-group** (``responses``, ``response_mask``, and any key
      whose last dim equals the current response length): *right*-padded
      to ``max_response_len``.
    * **Full-seq-group** (``input_ids``, ``attention_mask``,
      ``position_ids``, and any key whose last dim equals the current
      full-seq length): left-padded by ``max_prompt_len - cur_prompt_len``
      and right-padded by ``max_response_from_input - cur_response_from_input``
      so that the prompt/response split point (``prompts.shape[-1]``) stays
      aligned with ``attention_mask``.

    This ensures ``no_padding_2_padding()`` in the downstream training
    pipeline correctly splits ``attention_mask`` at ``prompts.shape[-1]``
    to recover per-token prompt/response lengths.
    """
    if len(data_protos) <= 1:
        return data_protos

    has_pr = all(
        "prompts" in dp.batch and "responses" in dp.batch
        for dp in data_protos
    )
    if not has_pr:
        # Fallback: simple left-pad every key to its own max.
        return _repad_simple(data_protos, pad_token_id)

    prompt_dims = [dp.batch["prompts"].shape[-1] for dp in data_protos]
    response_dims = [dp.batch["responses"].shape[-1] for dp in data_protos]
    full_seq_dims = [dp.batch["input_ids"].shape[-1] for dp in data_protos]

    max_prompt = max(prompt_dims)
    max_response = max(response_dims)
    # resp_from_input: response columns within input_ids (= full_seq_len - prompt_len).
    # May differ from responses.shape[-1] because responses is stored independently.
    resp_from_input = [f - p for f, p in zip(full_seq_dims, prompt_dims)]
    max_resp_from_input = max(resp_from_input)
    # target_full aligns the split point to max_prompt across all full-seq tensors.
    target_full = max_prompt + max_resp_from_input

    if (min(prompt_dims) == max_prompt
            and min(response_dims) == max_response
            and min(full_seq_dims) == target_full):
        return data_protos

    logger.info(
        "Re-padding {} DataProtos: prompt→{}, response→{}, full_seq→{}",
        len(data_protos), max_prompt, max_response, target_full,
    )

    result: list[DataProto] = []
    for i, dp in enumerate(data_protos):
        left_pad = max_prompt - prompt_dims[i]
        right_pad = max_resp_from_input - resp_from_input[i]
        resp_pad = max_response - response_dims[i]

        if left_pad == 0 and right_pad == 0 and resp_pad == 0:
            result.append(dp)
            continue

        cur_prompt_dim = prompt_dims[i]
        cur_resp_dim = response_dims[i]
        cur_full_dim = full_seq_dims[i]

        new_tensors: dict[str, torch.Tensor] = {}
        for key in dp.batch.keys():
            tensor = dp.batch[key]
            if tensor.dim() < 2:
                new_tensors[key] = tensor
                continue

            seq_len = tensor.shape[-1]

            # Key name takes priority; dimension matching is the fallback for unknown keys.
            if key == "prompts" or (seq_len == cur_prompt_dim
                                     and seq_len != cur_resp_dim
                                     and seq_len != cur_full_dim):
                new_tensors[key] = _left_pad(tensor, left_pad, pad_token_id)

            elif key in ("responses", "response_mask") or (
                    seq_len == cur_resp_dim
                    and seq_len != cur_prompt_dim
                    and seq_len != cur_full_dim):
                new_tensors[key] = _right_pad(tensor, resp_pad)

            elif seq_len == cur_full_dim:
                # input_ids uses pad_token_id; attention_mask / position_ids use 0.
                pv = pad_token_id if key == "input_ids" else 0
                new_tensors[key] = _lr_pad(tensor, left_pad, right_pad, pv)

            else:
                # Unknown dim: keep as-is; a dim mismatch during concat will give a clear error.
                new_tensors[key] = tensor

        result.append(DataProto(
            batch=TensorDict(new_tensors, batch_size=dp.batch.batch_size),
            non_tensor_batch=dp.non_tensor_batch,
            meta_info=dp.meta_info,
        ))

    return result


def _left_pad(tensor: torch.Tensor, pad_len: int, pad_val: int = 0) -> torch.Tensor:
    if pad_len <= 0:
        return tensor
    ps = list(tensor.shape)
    ps[-1] = pad_len
    return torch.cat([torch.full(ps, pad_val, dtype=tensor.dtype, device=tensor.device),
                      tensor], dim=-1)


def _right_pad(tensor: torch.Tensor, pad_len: int, pad_val: int = 0) -> torch.Tensor:
    if pad_len <= 0:
        return tensor
    ps = list(tensor.shape)
    ps[-1] = pad_len
    return torch.cat([tensor,
                      torch.full(ps, pad_val, dtype=tensor.dtype, device=tensor.device)], dim=-1)


def _lr_pad(tensor: torch.Tensor, left: int, right: int, pad_val: int = 0) -> torch.Tensor:
    parts = []
    if left > 0:
        ps = list(tensor.shape)
        ps[-1] = left
        parts.append(torch.full(ps, pad_val, dtype=tensor.dtype, device=tensor.device))
    parts.append(tensor)
    if right > 0:
        ps = list(tensor.shape)
        ps[-1] = right
        parts.append(torch.full(ps, pad_val, dtype=tensor.dtype, device=tensor.device))
    return torch.cat(parts, dim=-1) if len(parts) > 1 else tensor


def _repad_simple(
    data_protos: list[DataProto],
    pad_token_id: int = 0,
) -> list[DataProto]:
    """Fallback: left-pad every 2D+ key to its own global max (no alignment)."""
    all_keys = list(data_protos[0].batch.keys())
    key_lens: dict[str, list[int]] = {}
    max_lens: dict[str, int] = {}
    for key in all_keys:
        if data_protos[0].batch[key].dim() < 2:
            continue
        lens = [dp.batch[key].shape[-1] for dp in data_protos]
        mx = max(lens)
        if min(lens) < mx:
            key_lens[key] = lens
            max_lens[key] = mx

    if not max_lens:
        return data_protos

    logger.info("Re-padding (simple) {} DataProtos, max_lens: {}", len(data_protos), max_lens)

    result = []
    for i, dp in enumerate(data_protos):
        needs = any(lens_list[i] < max_lens[k] for k, lens_list in key_lens.items())
        if not needs:
            result.append(dp)
            continue
        new_tensors = {}
        for key in dp.batch.keys():
            tensor = dp.batch[key]
            if key in max_lens:
                pad_amount = max_lens[key] - tensor.shape[-1]
                # responses / response_mask are right-padded; everything else left-padded.
                if key in ("responses", "response_mask"):
                    new_tensors[key] = _right_pad(tensor, pad_amount, 0)
                else:
                    pv = pad_token_id if key == "input_ids" else 0
                    new_tensors[key] = _left_pad(tensor, pad_amount, pv)
            else:
                new_tensors[key] = tensor
        result.append(DataProto(
            batch=TensorDict(new_tensors, batch_size=dp.batch.batch_size),
            non_tensor_batch=dp.non_tensor_batch,
            meta_info=dp.meta_info,
        ))
    return result


def assemble_mcp_training_batch(
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

    # Re-pad: different generate_sequences() calls use dynamic padding, so
    # DataProtos may have different seq_len and cannot be torch.cat'd directly.
    pad_id = getattr(tokenizer, "pad_token_id", 0) or 0
    data_protos = _repad_data_protos(data_protos, pad_token_id=pad_id)

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

    final_batch = DataProto.concat(data_protos)

    if final_batch.batch is not None and "response_mask" not in final_batch.batch.keys():
        final_batch.batch["response_mask"] = compute_response_mask(final_batch)

    if final_batch.batch is not None and "attention_mask" in final_batch.batch:
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
