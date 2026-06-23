"""Shared DataProto padding helpers for MCP rollout batches."""

from __future__ import annotations

import time
from typing import Iterable

import numpy as np
import torch
from tensordict import TensorDict
from verl import DataProto

from .utils import _LazyLogger

logger = _LazyLogger()


def _to_numpy(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().cpu().contiguous().numpy()


def _left_pad(tensor: torch.Tensor, pad_len: int, pad_val: int = 0) -> torch.Tensor:
    if pad_len <= 0:
        return tensor
    if tensor.device.type == "cpu":
        array = _to_numpy(tensor)
        pad_shape = list(array.shape)
        pad_shape[-1] = pad_len
        padded = np.full(pad_shape, pad_val, dtype=array.dtype)
        return torch.from_numpy(np.concatenate([padded, array], axis=-1))
    pad_shape = list(tensor.shape)
    pad_shape[-1] = pad_len
    return torch.cat(
        [torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device), tensor],
        dim=-1,
    )


def _right_pad(tensor: torch.Tensor, pad_len: int, pad_val: int = 0) -> torch.Tensor:
    if pad_len <= 0:
        return tensor
    if tensor.device.type == "cpu":
        array = _to_numpy(tensor)
        pad_shape = list(array.shape)
        pad_shape[-1] = pad_len
        padded = np.full(pad_shape, pad_val, dtype=array.dtype)
        return torch.from_numpy(np.concatenate([array, padded], axis=-1))
    pad_shape = list(tensor.shape)
    pad_shape[-1] = pad_len
    return torch.cat(
        [tensor, torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device)],
        dim=-1,
    )


def _lr_pad(
    tensor: torch.Tensor,
    left: int,
    right: int,
    pad_val: int = 0,
) -> torch.Tensor:
    if left <= 0 and right <= 0:
        return tensor
    if tensor.device.type == "cpu":
        array = _to_numpy(tensor)
        shape = list(array.shape)
        shape[-1] = array.shape[-1] + max(left, 0) + max(right, 0)
        padded = np.full(shape, pad_val, dtype=array.dtype)
        start = max(left, 0)
        padded[..., start:start + array.shape[-1]] = array
        return torch.from_numpy(padded)

    parts = []
    if left > 0:
        pad_shape = list(tensor.shape)
        pad_shape[-1] = left
        parts.append(torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device))
    parts.append(tensor)
    if right > 0:
        pad_shape = list(tensor.shape)
        pad_shape[-1] = right
        parts.append(torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device))
    return torch.cat(parts, dim=-1) if len(parts) > 1 else tensor


def _lr_pad_seq_dim(
    tensor: torch.Tensor,
    left: int,
    right: int,
    pad_val: int = 0,
) -> torch.Tensor:
    """Left/right pad sequence dimension (dim=1) for 3D/4D tensors.

    Used by routed_experts shaped [B, seq, num_layers, topk], whose sequence
    dimension is not the final axis.
    """
    if left <= 0 and right <= 0:
        return tensor
    parts = []
    if left > 0:
        pad_shape = list(tensor.shape)
        pad_shape[1] = left
        parts.append(torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device))
    parts.append(tensor)
    if right > 0:
        pad_shape = list(tensor.shape)
        pad_shape[1] = right
        parts.append(torch.full(pad_shape, pad_val, dtype=tensor.dtype, device=tensor.device))
    return torch.cat(parts, dim=1) if len(parts) > 1 else tensor


def _repad_simple(
    data_protos: list[DataProto],
    pad_token_id: int = 0,
) -> list[DataProto]:
    """Fallback: left-pad every 2D+ key to its own global max."""
    all_keys = list(data_protos[0].batch.keys())
    key_lens: dict[str, list[int]] = {}
    max_lens: dict[str, int] = {}
    for key in all_keys:
        if data_protos[0].batch[key].dim() < 2:
            continue
        lens = [dp.batch[key].shape[-1] for dp in data_protos]
        max_len = max(lens)
        if min(lens) < max_len:
            key_lens[key] = lens
            max_lens[key] = max_len

    if not max_lens:
        return data_protos

    logger.info("Re-padding (simple) {} DataProtos, max_lens: {}", len(data_protos), max_lens)

    result = []
    for i, dp in enumerate(data_protos):
        needs_padding = any(lens_list[i] < max_lens[key] for key, lens_list in key_lens.items())
        if not needs_padding:
            result.append(dp)
            continue

        new_tensors = {}
        for key in dp.batch.keys():
            tensor = dp.batch[key]
            if key in max_lens:
                pad_amount = max_lens[key] - tensor.shape[-1]
                if key in ("responses", "response_mask", "rollout_log_probs"):
                    new_tensors[key] = _right_pad(tensor, pad_amount, 0)
                else:
                    pad_value = pad_token_id if key == "input_ids" else 0
                    new_tensors[key] = _left_pad(tensor, pad_amount, pad_value)
            else:
                new_tensors[key] = tensor

        result.append(DataProto(
            batch=TensorDict(new_tensors, batch_size=dp.batch.batch_size),
            non_tensor_batch=dp.non_tensor_batch,
            meta_info=dp.meta_info,
        ))
    return result


def repad_data_protos(
    data_protos: list[DataProto],
    pad_token_id: int = 0,
) -> list[DataProto]:
    """Re-pad rollout DataProtos to uniform prompt/response/full sequence lengths."""
    if len(data_protos) <= 1:
        return data_protos

    has_prompt_response = all(
        dp.batch is not None and "prompts" in dp.batch and "responses" in dp.batch
        for dp in data_protos
    )
    if not has_prompt_response:
        return _repad_simple(data_protos, pad_token_id)

    prompt_dims = [dp.batch["prompts"].shape[-1] for dp in data_protos]
    response_dims = [dp.batch["responses"].shape[-1] for dp in data_protos]
    full_seq_dims = [dp.batch["input_ids"].shape[-1] for dp in data_protos]

    max_prompt = max(prompt_dims)
    max_response = max(response_dims)
    response_from_input = [full - prompt for full, prompt in zip(full_seq_dims, prompt_dims)]
    max_response_from_input = max(response_from_input)
    target_full = max_prompt + max_response_from_input

    if (
        min(prompt_dims) == max_prompt
        and min(response_dims) == max_response
        and min(full_seq_dims) == target_full
    ):
        return data_protos

    logger.info(
        "Re-padding {} DataProtos: prompt={}, response={}, full_seq={}",
        len(data_protos),
        max_prompt,
        max_response,
        target_full,
    )

    result: list[DataProto] = []
    for i, dp in enumerate(data_protos):
        left_pad = max_prompt - prompt_dims[i]
        right_pad = max_response_from_input - response_from_input[i]
        response_pad = max_response - response_dims[i]

        if left_pad == 0 and right_pad == 0 and response_pad == 0:
            result.append(dp)
            continue

        cur_prompt_dim = prompt_dims[i]
        cur_response_dim = response_dims[i]
        cur_full_dim = full_seq_dims[i]

        new_tensors: dict[str, torch.Tensor] = {}
        for key in dp.batch.keys():
            tensor = dp.batch[key]
            if key == "routed_experts":
                new_tensors[key] = _lr_pad_seq_dim(tensor, left_pad, right_pad, 0)
                continue
            if tensor.dim() < 2:
                new_tensors[key] = tensor
                continue

            seq_len = tensor.shape[-1]
            if key == "prompts" or (
                seq_len == cur_prompt_dim
                and seq_len != cur_response_dim
                and seq_len != cur_full_dim
            ):
                new_tensors[key] = _left_pad(tensor, left_pad, pad_token_id)
            elif key in ("responses", "response_mask", "rollout_log_probs") or (
                seq_len == cur_response_dim
                and seq_len != cur_prompt_dim
                and seq_len != cur_full_dim
            ):
                new_tensors[key] = _right_pad(tensor, response_pad)
            elif seq_len == cur_full_dim:
                pad_value = pad_token_id if key == "input_ids" else 0
                new_tensors[key] = _lr_pad(tensor, left_pad, right_pad, pad_value)
            else:
                new_tensors[key] = tensor

        result.append(DataProto(
            batch=TensorDict(new_tensors, batch_size=dp.batch.batch_size),
            non_tensor_batch=dp.non_tensor_batch,
            meta_info=dp.meta_info,
        ))

    return result


def _concat_tensor_batches(data_protos: list[DataProto]) -> TensorDict:
    keys = list(data_protos[0].batch.keys())
    tensors: dict[str, torch.Tensor] = {}
    total_rows = sum(int(dp.batch.batch_size[0]) for dp in data_protos)

    for key in keys:
        parts = [dp.batch[key] for dp in data_protos]
        if all(part.device.type == "cpu" for part in parts):
            tensors[key] = torch.from_numpy(np.concatenate([_to_numpy(part) for part in parts], axis=0))
        else:
            tensors[key] = torch.cat(parts, dim=0)

    return TensorDict(tensors, batch_size=[total_rows])


def _concat_non_tensor_batches(data_protos: list[DataProto]) -> dict:
    keys: list[str] = []
    for dp in data_protos:
        for key in dp.non_tensor_batch.keys():
            if key not in keys:
                keys.append(key)

    result = {}
    for key in keys:
        values = [dp.non_tensor_batch[key] for dp in data_protos if key in dp.non_tensor_batch]
        if not values:
            continue
        arrays = [value if isinstance(value, np.ndarray) else np.array(value, dtype=object) for value in values]
        result[key] = np.concatenate(arrays, axis=0)
    return result


def _strip_conflicting_meta_info(data_protos: list[DataProto]) -> None:
    if len(data_protos) <= 1:
        return

    reference = {}
    conflicting: set[str] = set()
    for dp in data_protos:
        for key, value in dp.meta_info.items():
            if key == "metrics":
                continue
            if key not in reference:
                reference[key] = value
                continue
            try:
                if reference[key] != value:
                    conflicting.add(key)
            except Exception:  # pylint: disable=broad-exception-caught
                conflicting.add(key)

    if conflicting:
        logger.info("Stripping conflicting meta_info keys before concat: {}", conflicting)
        for dp in data_protos:
            for key in conflicting:
                dp.meta_info.pop(key, None)


def concat_padded_dataprotos(
    data_protos: Iterable[DataProto],
    *,
    pad_token_id: int = 0,
    context: str = "MCP rollout",
) -> DataProto:
    """Re-pad and concatenate per-instance rollout DataProtos."""
    start = time.monotonic()
    valid = [dp for dp in data_protos if dp is not None and dp.batch is not None]
    if not valid:
        raise ValueError(f"{context} produced no valid DataProto batches to concatenate")

    rollout_metrics = None
    rollout_replicas_slept = False
    global_token_num: list[int] = []
    for dp in valid:
        if rollout_metrics is None and "rollout_metrics" in dp.meta_info:
            rollout_metrics = dp.meta_info.get("rollout_metrics")
        rollout_replicas_slept = rollout_replicas_slept or bool(
            dp.meta_info.get("rollout_replicas_slept", False)
        )
        values = dp.meta_info.get("global_token_num")
        if values is not None:
            global_token_num.extend(int(value) for value in values)

    padded = repad_data_protos(valid, pad_token_id=pad_token_id)
    _strip_conflicting_meta_info(padded)
    final_batch = DataProto(
        batch=_concat_tensor_batches(padded),
        non_tensor_batch=_concat_non_tensor_batches(padded),
        meta_info={},
    )

    if rollout_metrics is not None:
        final_batch.meta_info["rollout_metrics"] = rollout_metrics
    if rollout_replicas_slept:
        final_batch.meta_info["rollout_replicas_slept"] = True
    if (
        global_token_num
        and final_batch.batch is not None
        and len(global_token_num) == int(final_batch.batch.batch_size[0])
    ):
        final_batch.meta_info["global_token_num"] = global_token_num

    logger.info(
        "{} DataProto concat completed in {:.2f}s, parts={}, batch_size={}",
        context,
        time.monotonic() - start,
        len(valid),
        len(final_batch),
    )
    return final_batch
