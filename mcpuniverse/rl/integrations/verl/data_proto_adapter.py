"""Adapters between VERL DataProto and MCP rollout samples.

``data_proto_to_rollout_samples`` converts veRL input batches into neutral
rollout samples. ``tokenized_rollout_batch_to_data_proto`` converts the
framework-neutral tokenized rollout result back into veRL ``DataProto``.
"""

# Heavy deps (torch / numpy / tensordict / verl) are imported lazily inside the
# functions that build tensors, so importing this module stays cheap and the
# input-side ``data_proto_to_rollout_samples`` converter works without torch.
# pylint: disable=import-outside-toplevel

from dataclasses import dataclass
from typing import Any, Dict, List

from loguru import logger

from mcpuniverse.rl.core.types import RolloutSample, TokenizedRolloutBatch


def _data_proto_non_tensor_rows(data_proto: Any) -> List[Dict[str, Any]]:
    """Convert ``DataProto.non_tensor_batch`` from dict-of-arrays to rows."""
    non_tensor_batch = data_proto.non_tensor_batch

    if not non_tensor_batch:
        return []

    keys = list(non_tensor_batch.keys())
    first_key = keys[0]
    num_entries = len(non_tensor_batch[first_key])

    for key in keys:
        if len(non_tensor_batch[key]) != num_entries:
            raise ValueError(
                f"Inconsistent batch sizes: key '{first_key}' has {num_entries} entries, "
                f"but key '{key}' has {len(non_tensor_batch[key])} entries"
            )

    return [
        {key: non_tensor_batch[key][i] for key in keys}
        for i in range(num_entries)
    ]


def data_proto_to_rollout_samples(data_proto: Any) -> List[RolloutSample]:
    """Convert ``DataProto.non_tensor_batch`` into neutral rollout samples."""
    return [
        RolloutSample.from_mapping(row)
        for row in _data_proto_non_tensor_rows(data_proto)
    ]


def _select_config(config: Any, key: str, default: Any) -> Any:
    """Select a dotted config key from OmegaConf, dicts, or simple objects."""
    if config is None:
        return default

    try:
        from omegaconf import OmegaConf

        return OmegaConf.select(config, key, default=default)
    except Exception:  # pylint: disable=broad-exception-caught
        current = config
        for part in key.split("."):
            if isinstance(current, dict):
                if part not in current:
                    return default
                current = current[part]
            else:
                if not hasattr(current, part):
                    return default
                current = getattr(current, part)
        return current


@dataclass
class _TokenizedFields:
    prompt_ids: List[List[int]]
    response_ids: List[List[int]]
    response_masks: List[List[int]]
    response_logprobs: List[List[float]]
    routed_experts: List[Any]
    rewards: List[float]
    group_ids: List[str]
    trajectories: List[Any]
    metrics: Dict[str, Any]


@dataclass
class _PaddedSequences:
    prompt_tensor: Any
    prompt_attention_mask: Any
    response_tensor: Any
    response_attention_mask: Any


def _extract_tokenized_fields(tokenized_batch: TokenizedRolloutBatch) -> _TokenizedFields:
    if not hasattr(tokenized_batch, "prompt_ids"):
        raise TypeError(
            "tokenized_rollout_batch_to_data_proto expects a TokenizedRolloutBatch"
        )

    return _TokenizedFields(
        prompt_ids=[list(ids) for ids in getattr(tokenized_batch, "prompt_ids", [])],
        response_ids=[list(ids) for ids in getattr(tokenized_batch, "response_ids", [])],
        response_masks=[list(mask) for mask in getattr(tokenized_batch, "response_mask", [])],
        response_logprobs=[list(lp) for lp in getattr(tokenized_batch, "response_logprobs", [])],
        routed_experts=list(getattr(tokenized_batch, "routed_experts", []) or []),
        rewards=list(getattr(tokenized_batch, "rewards", [])),
        group_ids=list(getattr(tokenized_batch, "group_ids", []) or []),
        trajectories=list(getattr(tokenized_batch, "trajectories", []) or []),
        metrics=dict(getattr(tokenized_batch, "metrics", {}) or {}),
    )


def _validate_tokenized_fields(fields: _TokenizedFields) -> None:
    num_sequences = len(fields.prompt_ids)
    for field_name, field_value in (
        ("response_ids", fields.response_ids),
        ("response_mask", fields.response_masks),
        ("rewards", fields.rewards),
    ):
        if len(field_value) != num_sequences:
            raise ValueError(
                "Inconsistent tokenized batch lengths: "
                f"prompt_ids has {num_sequences} entries, "
                f"but {field_name} has {len(field_value)}"
            )

    for idx, (response, mask) in enumerate(zip(fields.response_ids, fields.response_masks)):
        if len(mask) != len(response):
            raise ValueError(
                f"Inconsistent mask length at index {idx}: "
                f"response_ids has {len(response)} tokens, "
                f"but response_mask has {len(mask)} elements"
            )

    if fields.trajectories and len(fields.trajectories) != num_sequences:
        raise ValueError(
            f"trajectories has {len(fields.trajectories)} entries for "
            f"{num_sequences} tokenized sequences"
        )


def _truncate_to_config_limits(
    fields: _TokenizedFields,
    *,
    max_prompt: int,
    max_response: int,
) -> int:
    truncated_count = 0
    for idx, prompt in enumerate(fields.prompt_ids):
        if len(prompt) > max_prompt:
            overflow = len(prompt) - max_prompt
            fields.prompt_ids[idx] = prompt[-max_prompt:]
            if idx < len(fields.routed_experts) and fields.routed_experts[idx] is not None:
                fields.routed_experts[idx] = fields.routed_experts[idx][overflow:]
            truncated_count += 1
        if len(fields.response_ids[idx]) > max_response:
            fields.response_ids[idx] = fields.response_ids[idx][:max_response]
            fields.response_masks[idx] = fields.response_masks[idx][:max_response]
            if idx < len(fields.response_logprobs):
                fields.response_logprobs[idx] = fields.response_logprobs[idx][:max_response]
            if idx < len(fields.routed_experts) and fields.routed_experts[idx] is not None:
                fields.routed_experts[idx] = fields.routed_experts[idx][
                    : len(fields.prompt_ids[idx]) + max_response
                ]
            truncated_count += 1
    return truncated_count


def _get_pad_token_id(tokenizer: Any) -> int:
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if pad_token_id is not None:
        return int(pad_token_id)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if eos_token_id is not None:
        return int(eos_token_id)
    return 0


def _pad_sequences(tokenizer: Any, sequences: List[List[int]], *, padding_side: str):
    import torch

    max_length = max(len(ids) for ids in sequences)
    pad_token_id = _get_pad_token_id(tokenizer)
    input_ids = torch.full(
        (len(sequences), max_length),
        pad_token_id,
        dtype=torch.long,
    )
    attention_mask = torch.zeros(
        (len(sequences), max_length),
        dtype=torch.long,
    )

    for row, ids in enumerate(sequences):
        seq_len = len(ids)
        if seq_len == 0:
            continue
        values = torch.as_tensor(ids, dtype=torch.long)
        if padding_side == "left":
            input_ids[row, max_length - seq_len:] = values
            attention_mask[row, max_length - seq_len:] = 1
        else:
            input_ids[row, :seq_len] = values
            attention_mask[row, :seq_len] = 1

    return input_ids, attention_mask, max_length


def _pad_prompt_response(fields: _TokenizedFields, tokenizer: Any) -> tuple[_PaddedSequences, int, int]:
    prompt_tensor, prompt_attention_mask, max_prompt_length = _pad_sequences(
        tokenizer, fields.prompt_ids, padding_side="left",
    )
    response_tensor, response_attention_mask, max_response_length = _pad_sequences(
        tokenizer, fields.response_ids, padding_side="right",
    )
    return (
        _PaddedSequences(
            prompt_tensor=prompt_tensor,
            prompt_attention_mask=prompt_attention_mask,
            response_tensor=response_tensor,
            response_attention_mask=response_attention_mask,
        ),
        max_prompt_length,
        max_response_length,
    )


def _build_routed_experts_tensor(
    prompt_ids: List[List[int]],
    response_ids: List[List[int]],
    routed_experts: List[Any],
    *,
    max_prompt_length: int,
    max_response_length: int,
):
    """Build padded full-sequence routed_experts for R3.

    Each unpadded entry must be aligned with prompt+response:
    [len(prompt)+len(response), num_layers, topk]. Padding mirrors input_ids:
    prompt part is left-padded, response part is right-padded.
    """
    import torch

    if not routed_experts or any(x is None for x in routed_experts):
        return None
    if len(routed_experts) != len(prompt_ids):
        logger.warning(
            "Skipping routed_experts: {} entries for {} sequences",
            len(routed_experts), len(prompt_ids),
        )
        return None

    route_tensors = []
    num_layers = None
    topk = None
    for idx, raw in enumerate(routed_experts):
        route = torch.as_tensor(raw, dtype=torch.long)
        if route.dim() != 3:
            logger.warning("Skipping routed_experts: entry {} has shape {}", idx, tuple(route.shape))
            return None
        expected = len(prompt_ids[idx]) + len(response_ids[idx])
        if route.shape[0] == expected - 1:
            # SGLang returns routing for next-token forward positions:
            # prompt + response[:-1]. Megatron still runs a forward on the final
            # token, but its logits are not used for response log-probs
            # (actor slices [-response_len-1:-1]). Append a dummy route row at
            # the end to satisfy Megatron's full-sequence tensor contract without
            # affecting any loss-relevant position.
            pad = torch.zeros((1, route.shape[1], route.shape[2]), dtype=route.dtype)
            route = torch.cat([route, pad], dim=0)
        elif route.shape[0] != expected:
            logger.warning(
                "Skipping routed_experts: entry {} has seq_len {}, expected {} "
                "(prompt={}, response={})",
                idx, route.shape[0], expected, len(prompt_ids[idx]), len(response_ids[idx]),
            )
            return None
        if num_layers is None:
            num_layers, topk = int(route.shape[1]), int(route.shape[2])
        elif route.shape[1] != num_layers or route.shape[2] != topk:
            logger.warning(
                "Skipping routed_experts: entry {} layer/topk shape {} != ({}, {})",
                idx, tuple(route.shape[1:]), num_layers, topk,
            )
            return None
        route_tensors.append(route)

    batch_size = len(route_tensors)
    out = torch.zeros(
        (batch_size, max_prompt_length + max_response_length, num_layers, topk),
        dtype=torch.long,
    )
    for row, route in enumerate(route_tensors):
        prompt_len = len(prompt_ids[row])
        response_len = len(response_ids[row])
        if prompt_len:
            prompt_dst_start = max_prompt_length - prompt_len
            out[row, prompt_dst_start:max_prompt_length] = route[:prompt_len]
        if response_len:
            out[row, max_prompt_length:max_prompt_length + response_len] = route[
                prompt_len:prompt_len + response_len
            ]
    return out


def _build_tensor_dict(
    padded: _PaddedSequences,
    response_masks: List[List[int]],
    response_logprobs: List[List[float]] | None = None,
    prompt_ids: List[List[int]] | None = None,
    response_ids: List[List[int]] | None = None,
    routed_experts: List[Any] | None = None,
):
    import torch
    from tensordict import TensorDict

    batch_size = padded.response_tensor.shape[0]
    response_length = padded.response_tensor.shape[1]
    response_mask = torch.zeros(
        (batch_size, response_length),
        dtype=torch.long,
    )
    for row, mask in enumerate(response_masks):
        mask_len = min(len(mask), response_length)
        if mask_len:
            response_mask[row, :mask_len] = torch.as_tensor(
                mask[:mask_len],
                dtype=torch.long,
            )
    response_mask = response_mask * padded.response_attention_mask

    input_ids = torch.cat([padded.prompt_tensor, padded.response_tensor], dim=1)
    attention_mask = torch.cat(
        [padded.prompt_attention_mask, padded.response_attention_mask], dim=1,
    )
    position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask

    td = {
        "prompts": padded.prompt_tensor,
        "responses": padded.response_tensor,
        "response_mask": response_mask,
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "position_ids": position_ids,
    }

    # rollout_log_probs: per-response-token rollout log-probs (right-padded the
    # same way as responses), for TIS / train-inference mismatch correction.
    # Only added when actually captured (TITO); harmless if rollout_correction
    # is off (trainer just logs mismatch metrics).
    if response_logprobs and any(len(lp) for lp in response_logprobs):
        rollout_log_probs = torch.zeros((batch_size, response_length), dtype=torch.float32)
        for row, lp in enumerate(response_logprobs):
            n = min(len(lp), response_length)
            if n:
                rollout_log_probs[row, :n] = torch.as_tensor(lp[:n], dtype=torch.float32)
        td["rollout_log_probs"] = rollout_log_probs

    if prompt_ids is not None and response_ids is not None and routed_experts:
        routed = _build_routed_experts_tensor(
            prompt_ids,
            response_ids,
            routed_experts,
            max_prompt_length=padded.prompt_tensor.shape[1],
            max_response_length=response_length,
        )
        if routed is not None:
            td["routed_experts"] = routed

    return TensorDict(td, batch_size=batch_size)


def _build_uids(fields: _TokenizedFields, *, num_trajectories: int) -> List[str]:
    num_sequences = len(fields.rewards)
    if len(fields.group_ids) == len(fields.rewards):
        return [str(uid) for uid in fields.group_ids]

    stride = max(int(num_trajectories or 1), 1)
    uids = []
    for idx in range(num_sequences):
        traj = fields.trajectories[idx] if idx < len(fields.trajectories) else None
        if isinstance(traj, dict):
            instance_id = traj.get("instance_id", f"instance_{idx // stride}")
            uids.append(str(instance_id))
        else:
            uids.append(f"instance_{idx // stride}")
    return uids


def _build_non_tensor_batch(fields: _TokenizedFields, *, num_trajectories: int) -> Dict[str, Any]:
    import numpy as np

    non_tensor_batch = {"rewards": np.array(fields.rewards)}
    non_tensor_batch["response_lengths"] = np.array(
        [len(response_ids) for response_ids in fields.response_ids],
        dtype=np.int64,
    )
    non_tensor_batch["uid"] = np.array(
        _build_uids(fields, num_trajectories=num_trajectories),
        dtype=object,
    )
    if fields.trajectories:
        non_tensor_batch["trajectories"] = np.array(fields.trajectories, dtype=object)
    return non_tensor_batch


def _empty_data_proto(metrics: Dict[str, Any]):
    import numpy as np
    from verl.protocol import DataProto

    return DataProto(
        batch=None,
        non_tensor_batch={
            "rewards": np.array([]),
            "response_lengths": np.array([], dtype=np.int64),
            "uid": np.array([], dtype=object),
        },
        meta_info={"rollout_metrics": metrics, "timing": {}},
    )


def tokenized_rollout_batch_to_data_proto(
    tokenized_batch: TokenizedRolloutBatch,
    *,
    config: Any = None,
    tokenizer: Any,
    num_trajectories: int = 1,
):
    """Convert a neutral tokenized rollout batch into veRL ``DataProto``.

    This mirrors legacy ``MCPLoopManager._postprocess()`` tensor shape and owns
    only veRL-specific dynamic padding plus ``TensorDict``/``DataProto``
    construction.
    """
    from verl.protocol import DataProto

    fields = _extract_tokenized_fields(tokenized_batch)
    _validate_tokenized_fields(fields)

    if not fields.prompt_ids or not fields.response_ids:
        return _empty_data_proto(fields.metrics)

    cfg_max_prompt = int(_select_config(config, "data.max_prompt_length", 65536))
    cfg_max_response = int(_select_config(config, "data.max_response_length", 65536))

    truncated_count = _truncate_to_config_limits(
        fields,
        max_prompt=cfg_max_prompt,
        max_response=cfg_max_response,
    )
    if truncated_count > 0:
        logger.warning(
            "Truncated {} sequences to fit configured limits "
            "(max_prompt={}, max_response={})",
            truncated_count,
            cfg_max_prompt,
            cfg_max_response,
        )

    padded, max_prompt_length, max_response_length = _pad_prompt_response(fields, tokenizer)
    logger.info(
        "[Dynamic Padding] prompt_len={}, response_len={}, total_seq_len={}",
        max_prompt_length,
        max_response_length,
        max_prompt_length + max_response_length,
    )

    return DataProto(
        batch=_build_tensor_dict(
            padded,
            fields.response_masks,
            fields.response_logprobs,
            prompt_ids=fields.prompt_ids,
            response_ids=fields.response_ids,
            routed_experts=fields.routed_experts,
        ),
        non_tensor_batch=_build_non_tensor_batch(
            fields,
            num_trajectories=num_trajectories,
        ),
        meta_info={"rollout_metrics": fields.metrics, "timing": {}},
    )


__all__ = [
    "data_proto_to_rollout_samples",
    "tokenized_rollout_batch_to_data_proto",
]
