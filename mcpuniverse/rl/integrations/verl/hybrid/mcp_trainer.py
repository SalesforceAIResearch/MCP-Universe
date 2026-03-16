"""
MCP PPO Trainer for VERL integration.

Extends VERL's RayPPOTrainer with MCP agent loop support.
Similar to SkyRL's SkyAgentPPOTrainer but uses MCP-Universe.

Note: This trainer only supports hybrid mode (shared GPUs for actor and rollout).
For fully async mode, use MCPFullyAsyncTrainer.
"""
# pylint: disable=import-outside-toplevel,attribute-defined-outside-init,broad-exception-caught

import itertools
from collections import defaultdict

import numpy as np
import torch
from omegaconf import OmegaConf
from tqdm import tqdm
from loguru import logger

from verl import DataProto
from verl.trainer.ppo.ray_trainer import RayPPOTrainer, Role, compute_advantage
from verl.trainer.ppo.core_algos import agg_loss
from verl.trainer.ppo.metric_utils import (
    compute_data_metrics,
    compute_throughout_metrics,
    compute_timing_metrics,
    process_validation_metrics,
)
from verl.protocol import pad_dataproto_to_divisor, unpad_dataproto
from verl.single_controller.ray import RayClassWithInitArgs
from verl.single_controller.ray.base import create_colocated_worker_cls
from verl.utils.checkpoint.checkpoint_manager import should_save_ckpt_esi
from verl.utils.debug import marked_timer
from verl.utils.metric import reduce_metrics
from verl.utils.tracking import Tracking

from ..utils import extract_reward
from ..mcp_loop_manager import MCPLoopManager


def compute_response_mask(batch: DataProto) -> torch.Tensor:
    """Compute response mask from attention mask."""
    attention_mask = batch.batch["attention_mask"]
    prompt_length = batch.batch["prompts"].shape[1]
    response_length = batch.batch["responses"].shape[1]
    response_mask = attention_mask[:, prompt_length:prompt_length + response_length]
    return response_mask


class MCPPPOTrainer(RayPPOTrainer):
    """
    Distributed PPO trainer with MCP agent support (Hybrid Mode).

    Extends VERL's RayPPOTrainer to use MCPLoopManager for
    agent-based rollout with MCP tool use.

    Key differences from RayPPOTrainer:
    1. Uses MCPLoopManager instead of standard rollout
    2. Supports MCP server configuration
    3. Handles multi-turn agent trajectories

    Note: This trainer only supports hybrid mode (shared GPUs).
    For fully async mode, use MCPFullyAsyncTrainer.

    Usage:
        ```python
        from mcpuniverse.rl.integrations.verl import MCPPPOTrainer

        trainer = MCPPPOTrainer(
            config=config,
            tokenizer=tokenizer,
            reward_fn=reward_fn,
            ...
        )
        trainer.init_workers()
        trainer.fit()
        ```
    """

    def __init__(
        self,
        config,
        tokenizer,
        processor,
        role_worker_mapping,
        resource_pool_manager,
        ray_worker_group_cls,
        reward_fn=None,
        val_reward_fn=None,
        train_dataset=None,
        val_dataset=None,
        collate_fn=None,
        train_sampler=None,
        device_name: str = "cuda",
    ):
        """
        Initialize MCP PPO trainer (Hybrid Mode).

        Args:
            config: Training configuration
            tokenizer: Tokenizer
            processor: Processor (for multimodal)
            role_worker_mapping: Mapping from roles to worker classes
            resource_pool_manager: Resource pool manager
            ray_worker_group_cls: Ray worker group class
            reward_fn: Reward function for training
            val_reward_fn: Reward function for validation
            train_dataset: Training dataset
            val_dataset: Validation dataset
            collate_fn: Collate function
            train_sampler: Training sampler
            device_name: Device for training ("cuda" or "npu")
        """
        logger.info("Initializing MCPPPOTrainer in HYBRID MODE")
        super().__init__(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            collate_fn=collate_fn,
            train_sampler=train_sampler,
            device_name=device_name,
        )

        # reward_fn / val_reward_fn are no longer accepted by RayPPOTrainer.__init__
        # in newer VERL versions, so we store them ourselves.
        self.reward_fn = reward_fn
        self.val_reward_fn = val_reward_fn
        self.async_rollout_manager = None

        # MCP config
        mcp_cfg = self.config.get("mcp_agent", {})
        # Use actor_rollout_ref.rollout.n as primary source for num_trajectories
        rollout_n = self.config.actor_rollout_ref.rollout.get("n", 1)
        self.num_trajectories = rollout_n if rollout_n > 1 else mcp_cfg.get("num_trajectories", 1)

        logger.info(f"MCPPPOTrainer initialized with {self.num_trajectories} trajectories (rollout.n={rollout_n})")

    def init_workers(self):
        """
        Initialize distributed training workers with MCP support (Hybrid Mode).

        Creates:
        1. Actor/Rollout workers (combined in ActorRolloutRefWorker)
        2. Critic workers
        3. Reference policy workers (if using KL)
        4. Reward model workers (if enabled)
        5. MCPLoopManager for agent rollout
        """
        self.resource_pool_manager.create_resource_pool()
        self.resource_pool_to_cls = {
            pool: {} for pool in self.resource_pool_manager.resource_pool_dict.values()
        }

        logger.info("=== Initializing workers in HYBRID MODE (shared GPUs) ===")

        # Actor/Rollout worker
        if self.hybrid_engine:
            actor_rollout_resource_pool = self.resource_pool_manager.get_resource_pool(Role.ActorRollout)
            resource_pool = actor_rollout_resource_pool
            actor_rollout_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[Role.ActorRollout],
                config=self.config.actor_rollout_ref,
                role="actor_rollout",
            )
            self.resource_pool_to_cls[resource_pool]["actor_rollout"] = actor_rollout_cls
        else:
            raise NotImplementedError("Non-hybrid engine not supported. Use MCPFullyAsyncTrainer for fully async mode.")

        # Critic worker
        if self.use_critic:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.Critic)
            critic_cls = RayClassWithInitArgs(
                cls=self.role_worker_mapping[Role.Critic],
                config=self.config.critic
            )
            self.resource_pool_to_cls[resource_pool]["critic"] = critic_cls

        # Reference policy worker
        if self.use_reference_policy:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.RefPolicy)
            ref_policy_cls = RayClassWithInitArgs(
                self.role_worker_mapping[Role.RefPolicy],
                config=self.config.actor_rollout_ref,
                role="ref",
            )
            self.resource_pool_to_cls[resource_pool]["ref"] = ref_policy_cls

        # Reward model worker
        if self.use_rm:
            resource_pool = self.resource_pool_manager.get_resource_pool(Role.RewardModel)
            rm_cls = RayClassWithInitArgs(
                self.role_worker_mapping[Role.RewardModel],
                config=self.config.reward_model
            )
            self.resource_pool_to_cls[resource_pool]["rm"] = rm_cls

        # Create worker groups
        all_wg = {}
        wg_kwargs = {"device_name": self.device_name}

        if OmegaConf.select(self.config.trainer, "ray_wait_register_center_timeout") is not None:
            wg_kwargs["ray_wait_register_center_timeout"] = \
                self.config.trainer.ray_wait_register_center_timeout

        for resource_pool, class_dict in self.resource_pool_to_cls.items():
            worker_dict_cls = create_colocated_worker_cls(class_dict=class_dict)
            wg_dict = self.ray_worker_group_cls(
                resource_pool=resource_pool,
                ray_cls_with_init=worker_dict_cls,
                **wg_kwargs,
            )
            spawn_wg = wg_dict.spawn(prefix_set=class_dict.keys())
            all_wg.update(spawn_wg)

        if self.use_critic:
            self.critic_wg = all_wg["critic"]
            self.critic_wg.init_model()

        if self.use_reference_policy and not self.ref_in_actor:
            self.ref_policy_wg = all_wg["ref"]
            self.ref_policy_wg.init_model()

        if self.use_rm:
            self.rm_wg = all_wg["rm"]
            self.rm_wg.init_model()

        # Initialize actor/rollout last for better inference engine memory estimation
        self.actor_rollout_wg = all_wg["actor_rollout"]
        self.actor_rollout_wg.init_model()

        # Initialize MCP Loop Manager for async rollout
        self.async_rollout_mode = self.config.actor_rollout_ref.rollout.mode == "async"
        if self.async_rollout_mode:
            self.async_rollout_manager = MCPLoopManager(
                config=self.config,
                worker_group=self.actor_rollout_wg,
                rollout_resource_pool=actor_rollout_resource_pool,
            )
            logger.info("MCPLoopManager initialized for async rollout")

        # Create CheckpointEngineManager for weight sync (FSDP <-> inference engine)
        from verl.checkpoint_engine.base import CheckpointEngineManager  # pylint: disable=no-name-in-module
        ckpt_backend = self.config.actor_rollout_ref.rollout.get("checkpoint_engine", {}).get("backend", "naive")
        self.checkpoint_manager = CheckpointEngineManager(
            backend=ckpt_backend,
            trainer=self.actor_rollout_wg,
            replicas=self.async_rollout_manager.rollout_replicas if self.async_rollout_mode else [],
        )
        # Sleep replicas initially so checkpoint loading works
        self.checkpoint_manager.sleep_replicas()

    def _set_val_temperature(self):
        """Set validation temperature, return (original_temp, val_temp) for restore."""
        has_llm_config = (
            self.async_rollout_mode
            and hasattr(self.config, 'mcp_agent')
            and hasattr(self.config.mcp_agent, 'llm_config')
        )
        if not has_llm_config:
            return None, None

        original_temp = self.config.mcp_agent.llm_config.get('temperature', None)
        has_val_temp = (
            hasattr(self.config.mcp_agent, 'val_llm_config')
            and hasattr(self.config.mcp_agent.val_llm_config, 'temperature')
        )
        val_temp = (
            self.config.mcp_agent.val_llm_config.get('temperature', None)
            if has_val_temp else original_temp
        )

        if val_temp is not None and val_temp != original_temp:
            self.config.mcp_agent.llm_config.temperature = val_temp
            mgr = self.async_rollout_manager
            if hasattr(mgr, 'mcp_config') and hasattr(mgr.mcp_config, 'llm_config'):
                mgr.mcp_config.llm_config.temperature = val_temp
            logger.info(
                f"Validation: Set llm_config.temperature to "
                f"{val_temp} (training: {original_temp})"
            )
        else:
            logger.info(
                f"Validation: Using same temperature as training ({original_temp})"
            )
        return original_temp, val_temp

    def _restore_temperature(self, original_temp, val_temp):
        """Restore training temperature after validation."""
        should_restore = (
            original_temp is not None
            and val_temp is not None
            and val_temp != original_temp
        )
        has_llm_config = (
            self.async_rollout_mode
            and hasattr(self.config, 'mcp_agent')
            and hasattr(self.config.mcp_agent, 'llm_config')
        )
        if should_restore and has_llm_config:
            self.config.mcp_agent.llm_config.temperature = original_temp
            mgr = self.async_rollout_manager
            if hasattr(mgr, 'mcp_config') and hasattr(mgr.mcp_config, 'llm_config'):
                mgr.mcp_config.llm_config.temperature = original_temp
            logger.info(
                f"Validation complete: Restored llm_config.temperature "
                f"to {original_temp} (from validation: {val_temp})"
            )

    def _validate_batch(self, test_data, val_num_trajectories):
        """Process a single validation batch. Returns (inputs, outputs, scores, turns, data_sources)."""
        if "non_tensor_batch" in test_data:
            non_tensor_batch = test_data["non_tensor_batch"]
        else:
            non_tensor_batch = test_data

        if "instruction" in non_tensor_batch:
            input_texts = non_tensor_batch["instruction"]
            if not isinstance(input_texts, list):
                input_texts = [input_texts]
        else:
            input_texts = [""] * len(next(iter(non_tensor_batch.values())))

        input_texts_expanded = sum(
            [[t] * val_num_trajectories for t in input_texts], [],
        )

        test_gen_batch = DataProto(
            batch=None,
            non_tensor_batch={
                k: np.array(v, dtype=object) if isinstance(v, list) else v
                for k, v in non_tensor_batch.items()
            },
            meta_info={
                "eos_token_id": self.tokenizer.eos_token_id,
                "pad_token_id": self.tokenizer.pad_token_id,
                "recompute_log_prob": False,
                "do_sample": self.config.actor_rollout_ref.rollout.val_kwargs.do_sample,
                "validate": True,
                "val_mode": True,
            },
        )

        size_divisor = (
            self.actor_rollout_wg.world_size
            if not self.async_rollout_mode
            else self.config.actor_rollout_ref.rollout.get("agent", {}).get("num_workers", 1)
        )
        test_gen_batch_padded, pad_size = pad_dataproto_to_divisor(
            test_gen_batch, size_divisor,
        )

        self.checkpoint_manager.update_weights()
        if not self.async_rollout_mode:
            test_output = self.actor_rollout_wg.generate_sequences(test_gen_batch_padded)
            test_output = unpad_dataproto(
                test_output, pad_size=pad_size * val_num_trajectories,
            )
        else:
            test_output = self.async_rollout_manager.generate_sequences(test_gen_batch)
        self.checkpoint_manager.sleep_replicas()
        logger.info("Validation generation complete")

        if test_output.batch is not None and "responses" in test_output.batch:
            output_texts = [
                self.tokenizer.decode(ids, skip_special_tokens=True)
                for ids in test_output.batch["responses"]
            ]
        else:
            output_texts = [""] * len(input_texts_expanded)

        # Expand non_tensor_batch for val_num_trajectories
        test_batch = test_output
        for key, val in test_gen_batch.non_tensor_batch.items():
            if key not in test_batch.non_tensor_batch:
                if hasattr(val, 'tolist'):
                    val = val.tolist()
                if isinstance(val, (list, np.ndarray)):
                    expanded = []
                    for v in val:
                        expanded.extend([v] * val_num_trajectories)
                    test_batch.non_tensor_batch[key] = np.array(expanded, dtype=object)
                else:
                    test_batch.non_tensor_batch[key] = val
        test_batch.meta_info["validate"] = True

        result = self.val_reward_fn(test_batch, return_dict=True)
        scores = result["reward_tensor"].sum(-1).cpu().tolist()

        turns = None
        if "__num_turns__" in test_batch.non_tensor_batch:
            turns = test_batch.non_tensor_batch["__num_turns__"]

        data_sources = None
        if "data_source" in test_gen_batch.non_tensor_batch:
            data_sources = test_gen_batch.non_tensor_batch["data_source"].copy()

        return input_texts_expanded, output_texts, scores, turns, data_sources

    def _compute_val_metrics(self, sample_scores, sample_turns, data_source_lst,
                             sample_inputs, reward_extra_infos_dict):
        """Compute validation metrics dict."""
        metric_dict = {}

        if sample_scores:
            scores_arr = np.array(sample_scores)
            success_rate = float((scores_arr > 0).mean())
            mean_reward = float(scores_arr.mean())
            metric_dict["val/success_rate"] = success_rate
            metric_dict["val/mean_reward"] = mean_reward
            metric_dict["val/num_samples"] = len(scores_arr)
            logger.info(
                f"[Validation] success_rate={success_rate:.2%}, "
                f"mean_reward={mean_reward:.4f}, "
                f"num_samples={len(scores_arr)}"
            )

        data_sources = (
            np.concatenate(data_source_lst, axis=0)
            if data_source_lst else np.array([])
        )
        if data_sources.size > 0:
            data_src2var2metric2val = process_validation_metrics(
                data_sources, sample_inputs, reward_extra_infos_dict,
            )
            for data_source, var2metric2val in data_src2var2metric2val.items():
                for var_name, metric2val in var2metric2val.items():
                    for metric_name, metric_val in metric2val.items():
                        pfx = f"val/{data_source}/{var_name}/{metric_name}"
                        metric_dict[pfx] = metric_val

        if sample_turns:
            turns_arr = np.concatenate(sample_turns)
            metric_dict["val/num_turns/min"] = turns_arr.min()
            metric_dict["val/num_turns/max"] = turns_arr.max()
            metric_dict["val/num_turns/mean"] = turns_arr.mean()

        if metric_dict:
            logger.info("-" * 70)
            logger.info("[Validation Metrics]")
            for k, v in sorted(metric_dict.items()):
                logger.info(
                    f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}"
                )
            logger.info("=" * 70)

        return metric_dict

    def _validate(self, epoch: int = None):  # pylint: disable=arguments-renamed
        """Run validation on the validation dataset.

        Args:
            epoch: Current epoch number (optional, for logging)
        """
        if epoch is not None:
            logger.info(f"[Epoch {epoch}] Starting validation...")

        original_temp, val_temp = self._set_val_temperature()

        val_num_trajectories = (
            self.async_rollout_manager.val_num_trajectories
            if self.async_rollout_mode else 1
        )

        sample_inputs = []
        sample_outputs = []
        sample_scores = []
        sample_turns = []
        data_source_lst = []
        reward_extra_infos_dict: dict[str, list] = defaultdict(list)

        for test_data in self.val_dataloader:
            inputs, outputs, scores, turns, data_sources = self._validate_batch(
                test_data, val_num_trajectories,
            )
            sample_inputs.extend(inputs)
            sample_outputs.extend(outputs)
            sample_scores.extend(scores)
            reward_extra_infos_dict["reward"].extend(scores)
            if turns is not None:
                sample_turns.append(turns)
            if data_sources is not None:
                data_source_lst.append(data_sources)

        self._maybe_log_val_generations(
            inputs=sample_inputs, outputs=sample_outputs, scores=sample_scores,
        )
        self._print_validation_results(sample_inputs, sample_outputs, sample_scores)

        metric_dict = self._compute_val_metrics(
            sample_scores, sample_turns, data_source_lst,
            sample_inputs, reward_extra_infos_dict,
        )

        self._restore_temperature(original_temp, val_temp)
        return metric_dict

    def _print_validation_results(self, sample_inputs, sample_outputs, sample_scores):
        """Print detailed validation results."""
        logger.info("=" * 70)
        logger.info("VALIDATION RESULTS")
        logger.info("=" * 70)

        # Reward statistics
        if sample_scores:
            scores_arr = np.array(sample_scores)
            logger.info("[Reward Statistics]")
            logger.info(f"  Total samples: {len(scores_arr)}")
            logger.info(f"  Mean reward:   {scores_arr.mean():.4f}")
            logger.info(f"  Std reward:    {scores_arr.std():.4f}")
            logger.info(f"  Min reward:    {scores_arr.min():.4f}")
            logger.info(f"  Max reward:    {scores_arr.max():.4f}")
            logger.info(f"  Success rate:  {(scores_arr > 0).mean():.2%}")
        else:
            logger.info("[Reward Statistics]")
            logger.info("  No samples collected!")

        # Per-sample results
        logger.info("-" * 70)
        logger.info("[Per-Sample Results]")
        if sample_scores:
            for i, (inp, out, score) in enumerate(zip(sample_inputs, sample_outputs, sample_scores)):
                status = "✅" if score > 0 else "❌"
                inp_preview = inp[:80] + "..." if len(inp) > 80 else inp
                out_preview = out[:80] + "..." if len(out) > 80 else out
                logger.info(f"  [{i+1}] {status} reward={score:.4f}")
                logger.info(f"      Input:  {inp_preview}")
                logger.info(f"      Output: {out_preview}")
        else:
            logger.info("  No results to display")

        logger.info("=" * 70)

    def _val_before_train(self, tracking_logger):
        """Run initial validation before training and log results."""
        if not (self.val_reward_fn is not None
                and self.config.trainer.get("val_before_train", True)):
            return False

        logger.info("=" * 70)
        logger.info("[val_before_train] Running initial validation...")
        logger.info("=" * 70)

        val_metrics = self._validate(epoch=0)
        if val_metrics:
            init_metrics = {f"init_{k}": v for k, v in val_metrics.items()}
            init_metrics["training/epoch"] = 0

            logger.info("[val_before_train] Initial validation metrics:")
            for k, v in sorted(val_metrics.items()):
                logger.info(
                    f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}"
                )

            tracking_logger.log(data=init_metrics, step=self.global_steps)
            tracking_logger.log(data=val_metrics, step=self.global_steps)

            success_rate = val_metrics.get("val/success_rate", 0)
            mean_reward = val_metrics.get("val/mean_reward", 0)
            logger.info(
                f"[val_before_train] Complete: success_rate={success_rate:.2%}, "
                f"mean_reward={mean_reward:.4f}"
            )
        else:
            logger.warning("[val_before_train] No validation metrics returned!")

        return self.config.trainer.get("val_only", False)

    def _generate_batch(self, gen_batch, metrics, timing_raw):
        """Generate trajectories and compute rewards/advantages. Returns batch."""
        with marked_timer("gen", timing_raw, color="red"):
            self.checkpoint_manager.update_weights()
            if not self.async_rollout_mode:
                batch = self.actor_rollout_wg.generate_sequences(gen_batch)
            else:
                batch = self.async_rollout_manager.generate_sequences(gen_batch)
            self.checkpoint_manager.sleep_replicas()

            timing_raw.update(batch.meta_info.get("timing", {}))
            if "rollout_metrics" in batch.meta_info:
                rollout_metrics = reduce_metrics(batch.meta_info["rollout_metrics"])
                metrics.update(rollout_metrics)
                logger.info(f"Rollout metrics: {rollout_metrics}")

        batch_size = len(batch.batch) if batch.batch is not None else 0
        logger.info(f"Batch size after rollout: {batch_size}")

        if "response_mask" not in batch.batch.keys():
            batch.batch["response_mask"] = compute_response_mask(batch)

        if self.config.trainer.balance_batch:
            self._balance_batch(batch, metrics=metrics)

        batch.meta_info["global_token_num"] = torch.sum(
            batch.batch["attention_mask"], dim=-1,
        ).tolist()
        return batch

    def _compute_training_signals(self, batch, metrics, timing_raw):
        """Compute rewards, log probs, values, and advantages."""
        with marked_timer("reward", timing_raw, color="yellow"):
            if self.use_rm:
                reward_tensor = self.rm_wg.compute_rm_score(batch)
                batch = batch.union(reward_tensor)
            if "rm_scores" not in batch.batch:
                batch.batch["rm_scores"] = self.reward_fn(batch)
            reward_tensor, reward_extra_info = extract_reward(batch)

        with marked_timer("old_log_prob", timing_raw, color="blue"):
            old_log_prob = self.actor_rollout_wg.compute_log_prob(batch)
            entropys = old_log_prob.batch["entropys"]
            response_masks = batch.batch["response_mask"]
            entropy_agg = agg_loss(
                loss_mat=entropys,
                loss_mask=response_masks,
                loss_agg_mode=self.config.actor_rollout_ref.actor.loss_agg_mode,
            )
            metrics["actor/entropy"] = entropy_agg.detach().item()
            old_log_prob.batch.pop("entropys")
            batch = batch.union(old_log_prob)

        if self.use_reference_policy:
            with marked_timer("ref", timing_raw, color="olive"):
                if not self.ref_in_actor:
                    ref_log_prob = self.ref_policy_wg.compute_ref_log_prob(batch)
                else:
                    ref_log_prob = self.actor_rollout_wg.compute_ref_log_prob(batch)
                batch = batch.union(ref_log_prob)

        if self.use_critic:
            with marked_timer("values", timing_raw, color="cyan"):
                values = self.critic_wg.compute_values(batch)
                batch = batch.union(values)

        with marked_timer("adv", timing_raw, color="brown"):
            batch.batch["token_level_scores"] = reward_tensor
            if reward_extra_info:
                batch.non_tensor_batch.update({
                    k: np.array(v) for k, v in reward_extra_info.items()
                })
            if self.config.algorithm.use_kl_in_reward:
                batch, kl_metrics = self._apply_kl_penalty(batch)
                metrics.update(kl_metrics)
            else:
                batch.batch["token_level_rewards"] = batch.batch["token_level_scores"]

            adv_estimator = self.config.algorithm.adv_estimator.upper()
            n = self.config.actor_rollout_ref.rollout.get("n", 1)
            num_repeat = n if adv_estimator in ["GRPO", "RLOO"] else 1
            batch = compute_advantage(
                batch,
                adv_estimator=self.config.algorithm.adv_estimator,
                gamma=self.config.algorithm.gamma,
                lam=self.config.algorithm.lam,
                num_repeat=num_repeat,
                config=self.config.algorithm,
            )

        return batch

    def _update_models(self, batch, metrics, timing_raw):
        """Update critic and actor models."""
        if self.use_critic:
            with marked_timer("update_critic", timing_raw, color="pink"):
                critic_output = self.critic_wg.update_critic(batch)
            metrics.update(reduce_metrics(critic_output.meta_info["metrics"]))

        if self.config.trainer.critic_warmup <= self.global_steps:
            with marked_timer("update_actor", timing_raw, color="red"):
                batch.meta_info["multi_turn"] = (
                    self.config.actor_rollout_ref.rollout
                    .get("multi_turn", {}).get("enable", False)
                )
                actor_output = self.actor_rollout_wg.update_actor(batch)
            metrics.update(reduce_metrics(actor_output.meta_info["metrics"]))

    def _maybe_validate_and_save(self, _batch, metrics, timing_raw, is_last_step):
        """Run validation and save checkpoint if conditions are met."""
        if (
            self.val_reward_fn is not None
            and self.config.trainer.test_freq > 0
            and (is_last_step or self.global_steps % self.config.trainer.test_freq == 0)
        ):
            with marked_timer("testing", timing_raw, color="green"):
                val_metrics = self._validate()
            metrics.update(val_metrics)

        if (
            self.config.trainer.save_freq > 0
            and (
                is_last_step
                or self.global_steps % self.config.trainer.save_freq == 0
                or should_save_ckpt_esi(
                    max_steps_duration=self.max_steps_duration,
                    redundant_time=self.config.trainer.esi_redundant_time,
                )
            )
        ):
            with marked_timer("save_checkpoint", timing_raw, color="green"):
                self._save_checkpoint()

    def fit(self):
        """Main training loop for MCP PPO."""
        tracking_logger = Tracking(
            project_name=self.config.trainer.project_name,
            experiment_name=self.config.trainer.experiment_name,
            default_backend=self.config.trainer.logger,
            config=OmegaConf.to_container(self.config, resolve=True),
        )

        self.global_steps = 0
        self._load_checkpoint()

        if self._val_before_train(tracking_logger):
            return

        progress_bar = tqdm(
            total=self.total_training_steps,
            initial=self.global_steps,
            desc="MCP PPO Training",
        )

        self.global_steps += 1
        self.max_steps_duration = 0

        for epoch in range(self.config.trainer.total_epochs):
            train_dataloader_iter = iter(self.train_dataloader)

            for batch_dict in train_dataloader_iter:
                metrics = {}
                timing_raw = {}

                # Try to peek at next batch for gateway pre-warming
                try:
                    next_batch_dict = next(train_dataloader_iter)
                    train_dataloader_iter = itertools.chain(
                        [next_batch_dict], train_dataloader_iter,
                    )
                except StopIteration:
                    pass

                non_tensor_batch = (
                    batch_dict["non_tensor_batch"]
                    if "non_tensor_batch" in batch_dict
                    else batch_dict
                )

                gen_batch = DataProto(
                    batch=None,
                    non_tensor_batch={
                        k: np.array(v, dtype=object) if isinstance(v, list) else v
                        for k, v in non_tensor_batch.items()
                    },
                    meta_info={
                        "eos_token_id": self.tokenizer.eos_token_id,
                        "pad_token_id": self.tokenizer.pad_token_id,
                        "global_steps": self.global_steps,
                    },
                )

                if self.global_steps == 1:
                    instructions = non_tensor_batch.get("instruction", [])
                    if instructions:
                        logger.info(f"Sample prompts: {instructions[:2]}")

                is_last_step = self.global_steps >= self.total_training_steps

                with marked_timer("step", timing_raw):
                    batch = self._generate_batch(gen_batch, metrics, timing_raw)
                    batch = self._compute_training_signals(batch, metrics, timing_raw)
                    self._update_models(batch, metrics, timing_raw)
                    self._maybe_validate_and_save(batch, metrics, timing_raw, is_last_step)

                steps_duration = timing_raw.get("step", 0)
                self.max_steps_duration = max(self.max_steps_duration, steps_duration)

                metrics.update({
                    "training/global_step": self.global_steps,
                    "training/epoch": epoch,
                })
                metrics.update(compute_data_metrics(batch=batch, use_critic=self.use_critic))
                metrics.update(compute_timing_metrics(batch=batch, timing_raw=timing_raw))

                n_gpus = self.resource_pool_manager.get_n_gpus()
                metrics.update(compute_throughout_metrics(
                    batch=batch, timing_raw=timing_raw, n_gpus=n_gpus,
                ))

                tracking_logger.log(data=metrics, step=self.global_steps)

                progress_bar.update(1)
                self.global_steps += 1

                if is_last_step:
                    progress_bar.close()
                    return

            # End of Epoch Validation
            if self.val_reward_fn is not None:
                logger.info("=" * 70)
                logger.info(
                    f"[Epoch {epoch + 1}/{self.config.trainer.total_epochs}] "
                    "Running end-of-epoch validation..."
                )
                logger.info("=" * 70)

                with marked_timer("epoch_validation", {}):
                    epoch_val_metrics = self._validate(epoch=epoch + 1)

                if epoch_val_metrics:
                    epoch_metrics = {
                        f"epoch_{k}": v for k, v in epoch_val_metrics.items()
                    }
                    epoch_metrics["training/epoch"] = epoch + 1
                    tracking_logger.log(data=epoch_metrics, step=self.global_steps)

                    success_rate = epoch_val_metrics.get("val/success_rate", 0)
                    mean_reward = epoch_val_metrics.get("val/mean_reward", 0)
                    logger.info(
                        f"[Epoch {epoch + 1}] Validation complete: "
                        f"success_rate={success_rate:.2%}, "
                        f"mean_reward={mean_reward:.4f}"
                    )

    def _apply_kl_penalty(self, batch: DataProto) -> tuple:
        """Apply KL penalty to rewards."""
        from verl.trainer.ppo.core_algos import kl_penalty  # pylint: disable=import-outside-toplevel

        old_log_probs = batch.batch["old_log_probs"]
        ref_log_probs = batch.batch["ref_log_probs"]
        response_mask = batch.batch["response_mask"]

        kl = old_log_probs - ref_log_probs
        kl_reward = kl_penalty(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
            kl,
            kl_ctrl=self.kl_ctrl_in_reward,
            kl_penalty=self.config.algorithm.kl_penalty,
        )

        batch.batch["token_level_rewards"] = batch.batch["token_level_scores"] - kl_reward

        kl_masked = kl * response_mask
        kl_mean = kl_masked.sum() / response_mask.sum()

        return batch, {"kl/mean": kl_mean.item()}
