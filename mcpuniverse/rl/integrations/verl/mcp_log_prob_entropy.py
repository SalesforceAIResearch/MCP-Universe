"""Memory-aware actor log-prob helpers for MCP veRL integration."""

from __future__ import annotations

# These are verl worker compute_log_prob variants: they read verl worker
# internals (``_is_actor`` / ``_is_offload_param``), which are the de-facto
# worker interface, and import Megatron utils lazily so the FSDP path never
# pays the Megatron import cost.
# pylint: disable=protected-access,import-outside-toplevel

import logging
from contextlib import nullcontext
from typing import Any

from verl import DataProto
from verl.utils.fsdp_utils import fsdp_version, load_fsdp_model_to_gpu, offload_fsdp_model_to_cpu
from verl.utils.memory_utils import aggressive_empty_cache
from verl.utils.profiler import log_gpu_memory_usage

try:
    from omegaconf import OmegaConf
except ImportError:  # pragma: no cover
    OmegaConf = None

logger = logging.getLogger(__name__)


def _select(config: Any, key: str, default: Any = None) -> Any:
    if OmegaConf is not None:
        try:
            value = OmegaConf.select(config, key, default=default)
            return default if value is None else value
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    if hasattr(config, "get"):
        return config.get(key, default)
    return getattr(config, key, default)


def should_skip_entropy_for_log_prob(actor_config: Any) -> bool:
    """Return True when old-log-prob entropy can be skipped without loss change."""

    calculate_entropy = _select(actor_config, "calculate_entropy", False)
    if bool(calculate_entropy):
        return False

    entropy_coeff = _select(actor_config, "entropy_coeff", None)
    if entropy_coeff is None:
        return False
    try:
        return float(entropy_coeff) == 0.0
    except (TypeError, ValueError):
        return False


def pop_entropy_metric_if_present(
    *,
    old_log_prob: DataProto,
    batch: DataProto,
    actor_config: Any,
    metrics: dict,
    agg_loss,
) -> None:
    """Record actor entropy when present, otherwise mark it as intentionally skipped."""

    if "entropys" not in old_log_prob.batch:
        if not should_skip_entropy_for_log_prob(actor_config):
            raise KeyError(
                "old_log_prob is missing 'entropys', but entropy skipping is not enabled "
                "(requires actor.entropy_coeff == 0 and actor.calculate_entropy != true)."
            )
        metrics["actor/entropy_skipped"] = 1.0
        return

    entropys = old_log_prob.batch["entropys"]
    response_masks = batch.batch["response_mask"]
    kwargs = {
        "loss_mat": entropys,
        "loss_mask": response_masks,
        "loss_agg_mode": actor_config.loss_agg_mode,
    }
    loss_scale_factor = _select(actor_config, "loss_scale_factor", None)
    if loss_scale_factor is not None:
        kwargs["loss_scale_factor"] = loss_scale_factor
    entropy_agg = agg_loss(**kwargs)
    metrics["actor/entropy"] = entropy_agg.detach().item()
    old_log_prob.batch.pop("entropys")


def fsdp_compute_log_prob_without_entropy(worker: Any, data: DataProto) -> DataProto:
    """FSDP worker compute_log_prob variant that returns old/ref logprobs only."""

    assert worker._is_actor
    if worker._is_offload_param:
        load_fsdp_model_to_gpu(worker.actor_module_fsdp)

    is_lora = data.meta_info.pop("is_lora", False)
    adapter_ctx = worker.actor.actor_module.disable_adapter() if is_lora else nullcontext()
    config_source = worker.config.ref if is_lora else worker.config.rollout
    data.meta_info["micro_batch_size"] = config_source.log_prob_micro_batch_size_per_gpu
    data.meta_info["max_token_len"] = config_source.log_prob_max_token_len_per_gpu
    data.meta_info["use_dynamic_bsz"] = config_source.log_prob_use_dynamic_bsz
    data.meta_info["temperature"] = worker.config.rollout.temperature
    data.meta_info.setdefault("pad_token_id", worker.tokenizer.pad_token_id)

    with worker.ulysses_sharding_manager:
        with adapter_ctx:
            outputs = worker.actor.compute_log_prob(data=data, calculate_entropy=False)
        tensors = {"ref_log_prob": outputs["log_probs"]} if is_lora else {"old_log_probs": outputs["log_probs"]}
        if "sum_pi_squared" in outputs:
            tensors["sum_pi_squared"] = outputs["sum_pi_squared"]
        output = DataProto.from_dict(
            tensors=tensors,
            meta_info={"temperature": worker.config.rollout.temperature},
        )

    output = output.to("cpu")
    if worker.world_size > 1 and fsdp_version(worker.actor.actor_module) == 1:
        worker.actor.actor_module._handle.reshard(True)

    if worker._is_offload_param:
        offload_fsdp_model_to_cpu(worker.actor_module_fsdp)
        log_gpu_memory_usage("After offload actor model during compute_log_prob", logger=logger)

    return output


def megatron_compute_log_prob_without_entropy(worker: Any, data: DataProto) -> DataProto:
    """Megatron worker compute_log_prob variant that returns old/ref logprobs only."""

    from verl.utils.megatron.router_replay_patch import RouterReplay, RouterReplayAction
    from verl.utils.megatron_utils import load_megatron_model_to_gpu, offload_megatron_model_to_cpu

    assert worker._is_actor
    if worker._is_offload_param:
        load_megatron_model_to_gpu(worker.actor_module, load_grad=False)
        log_gpu_memory_usage("After load actor params and grad during compute_log_prob", logger=logger)

    is_lora = data.meta_info.pop("is_lora", False)
    adapter_ctx = worker.peft_cls.disable_adapter(worker.actor_module) if is_lora else nullcontext()
    config_source = worker.config.ref if is_lora else worker.config.rollout
    data.meta_info["micro_batch_size"] = config_source.log_prob_micro_batch_size_per_gpu
    data.meta_info["max_token_len"] = config_source.log_prob_max_token_len_per_gpu
    data.meta_info["use_dynamic_bsz"] = config_source.log_prob_use_dynamic_bsz
    data.meta_info["temperature"] = worker.config.rollout.temperature

    if worker.enable_routing_replay and worker.config.actor.router_replay.mode == "R2":
        RouterReplay.set_global_router_replay_action(RouterReplayAction.RECORD)
    if worker.enable_routing_replay and worker.config.actor.router_replay.mode == "R3":
        RouterReplay.set_global_router_replay_action(RouterReplayAction.REPLAY_FORWARD)

    with adapter_ctx:
        output, _entropys, layers_topk_idx = worker.actor.compute_log_prob(data=data, calculate_entropy=False)

    tensors = {"ref_log_prob": output} if is_lora else {"old_log_probs": output}
    result = DataProto.from_dict(
        tensors=tensors,
        meta_info={"temperature": worker.config.rollout.temperature},
    )
    if worker.config.actor.router_replay.mode == "R2":
        result.batch["routed_experts"] = layers_topk_idx

    if worker.config.actor.router_replay.mode in ["R2", "R3"]:
        RouterReplay.clear_global_indices()
        RouterReplay.clear_global_router_replay_action()

    result = result.to("cpu")
    if worker._is_offload_param:
        offload_megatron_model_to_cpu(worker.actor_module)
        log_gpu_memory_usage("After offload actor params and grad during compute_log_prob", logger=logger)
    aggressive_empty_cache(force_sync=True)
    return result
