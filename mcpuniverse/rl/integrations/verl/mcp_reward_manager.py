"""
MCP Reward Manager for VERL integration.

Handles reward computation for MCP agent training.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

import torch

from verl.protocol import DataProto
from verl.workers.reward_manager import register

from .utils import _LazyLogger, run_async_safely

logger = _LazyLogger()


@register("mcp_agent")
class MCPRewardManager:  # pylint: disable=too-few-public-methods
    """
    Reward manager for MCP agent training.

    Supports two modes:
    1. Pre-computed rewards (from MCPLoopManager rollout)
    2. Custom reward computation via reward_fn

    The rewards are stored in batch["rm_scores"] or non_tensor_batch["rewards"].
    """

    def __init__(
        self,
        tokenizer: Any,
        num_examine: int = 0,
        compute_score: Optional[callable] = None,
        reward_fn_key: str = "data_source"
    ):
        self.tokenizer = tokenizer
        self.num_examine = num_examine
        self.compute_score = compute_score
        self.reward_fn_key = reward_fn_key
        self._examined_count = 0

    def __call__(self, data: DataProto, return_dict: bool = False) -> Any:  # pylint: disable=too-many-return-statements
        """
        Compute or retrieve rewards for the batch.

        Priority:
        1. If rm_scores exists in batch, use it directly
        2. If rewards exists in non_tensor_batch, convert to token-level
        3. Use compute_score function if provided

        Returns:
            reward_tensor [B, S] or dict with reward_tensor and extra_info
        """
        # Empty batch guard:
        # Upstream rollout may return 0 trajectories (e.g. the env-pool docker
        # daemon is unreachable, or all MCP server inits failed). In that case
        # ``data.batch`` is None or length 0, and accessing ``.keys()`` /
        # ``["responses"]`` would raise AttributeError / KeyError, masking the
        # real upstream error (e.g. an unreachable MCP server) as a downstream
        # NoneType crash. Return an empty 0x0 reward tensor so the caller gets a
        # structured empty result, and log a warning to keep the upstream
        # failure visible.
        if data is None or data.batch is None or len(data) == 0:
            logger.warning(
                "MCPRewardManager received empty batch (data={}, batch={}, "
                "len={}). Returning empty reward tensor. Check upstream "
                "rollout / env-pool / MCP server health.",
                "None" if data is None else "set",
                "None" if data is None or data.batch is None else "set",
                0 if data is None else len(data),
            )
            empty_tensor = torch.zeros((0, 0), dtype=torch.float32)
            if return_dict:
                return {"reward_tensor": empty_tensor, "reward_extra_info": {}}
            return empty_tensor

        if "rm_scores" in data.batch.keys():
            if return_dict:
                return {"reward_tensor": data.batch["rm_scores"]}
            return data.batch["rm_scores"]

        batch_size = len(data)
        response_length = data.batch["responses"].shape[1]
        reward_tensor = torch.zeros((batch_size, response_length), dtype=torch.float32)
        reward_extra_info = defaultdict(list)

        if "rewards" in data.non_tensor_batch:
            rewards = data.non_tensor_batch["rewards"]
            if hasattr(rewards, "tolist"):
                rewards = rewards.tolist()
            if not isinstance(rewards, list):
                rewards = [rewards]
            if len(rewards) != batch_size:
                raise ValueError(
                    "Reward batch size mismatch: "
                    f"got {len(rewards)} rewards for batch_size={batch_size}"
                )

            reward_values = torch.tensor(
                [float(reward) for reward in rewards],
                dtype=torch.float32,
            )
            if "response_lengths" in data.non_tensor_batch:
                response_lengths = data.non_tensor_batch["response_lengths"]
                if hasattr(response_lengths, "tolist"):
                    response_lengths = response_lengths.tolist()
                if not isinstance(response_lengths, list):
                    response_lengths = [response_lengths]
                if len(response_lengths) != batch_size:
                    raise ValueError(
                        "Response length batch size mismatch: "
                        f"got {len(response_lengths)} response lengths for batch_size={batch_size}"
                    )
                valid_response_lengths = torch.tensor(
                    [
                        min(max(int(response_length_item), 0), response_length)
                        for response_length_item in response_lengths
                    ],
                    dtype=torch.long,
                )
            else:
                prompt_length = data.batch["prompts"].shape[-1]
                valid_response_lengths = (
                    data.batch["attention_mask"][:, prompt_length:prompt_length + response_length]
                    .sum(dim=-1)
                    .to(dtype=torch.long, device="cpu")
                )
            valid_rows = valid_response_lengths > 0
            if bool(valid_rows.any().item()):
                row_idx = torch.arange(batch_size, dtype=torch.long)[valid_rows]
                col_idx = valid_response_lengths[valid_rows] - 1
                reward_tensor[row_idx, col_idx] = reward_values[valid_rows]

            reward_extra_info["reward"].extend(reward_values.tolist())

            if self._examined_count < self.num_examine and batch_size > 0:
                logger.debug(
                    "RewardManager sample {}: reward={}, "
                    "valid_response_tokens={} (precomputed reward, decode skipped)",
                    0,
                    float(reward_values[0]),
                    int(valid_response_lengths[0]),
                )
                self._examined_count += 1

            if return_dict:
                return {
                    "reward_tensor": reward_tensor,
                    "reward_extra_info": dict(reward_extra_info),
                }
            return reward_tensor

        for i in range(batch_size):
            data_item = data[i]

            prompt_ids = data_item.batch["prompts"]
            prompt_length = prompt_ids.shape[-1]

            valid_prompt_length = data_item.batch["attention_mask"][:prompt_length].sum()
            response_ids = data_item.batch["responses"]
            valid_response_length = data_item.batch["attention_mask"][prompt_length:].sum()

            # Get reward from non_tensor_batch or compute_score
            reward = 0.0
            if "rewards" in data_item.non_tensor_batch:
                reward = float(data_item.non_tensor_batch["rewards"])
            elif self.compute_score is not None:
                valid_prompt_ids = prompt_ids[-valid_prompt_length:]
                valid_response_ids = response_ids[:valid_response_length]

                prompt_str = self.tokenizer.decode(valid_prompt_ids, skip_special_tokens=True)
                response_str = self.tokenizer.decode(valid_response_ids, skip_special_tokens=True)

                reward = self.compute_score(prompt_str, response_str, data_item.non_tensor_batch)

            # Place reward at last valid response token
            if valid_response_length > 0:
                reward_tensor[i, valid_response_length - 1] = reward

            reward_extra_info["reward"].append(reward)

            # Debug printing
            if self._examined_count < self.num_examine:
                valid_prompt_ids = prompt_ids[-valid_prompt_length:]
                valid_response_ids = response_ids[:valid_response_length]

                prompt_str = self.tokenizer.decode(valid_prompt_ids, skip_special_tokens=True)
                response_str = self.tokenizer.decode(valid_response_ids, skip_special_tokens=True)

                logger.debug(
                    "RewardManager sample {}: reward={}, prompt={}..., response={}...",
                    i, reward, prompt_str[:200], response_str[:200],
                )

                self._examined_count += 1

        if return_dict:
            return {
                "reward_tensor": reward_tensor,
                "reward_extra_info": dict(reward_extra_info),
            }
        return reward_tensor


class MCPEvaluatorRewardManager(MCPRewardManager):  # pylint: disable=too-few-public-methods
    """
    Reward manager that uses MCP-Universe evaluators.

    This variant runs evaluators during reward computation,
    useful when rewards weren't computed during rollout.
    """

    def __init__(
        self,
        tokenizer: Any,
        evaluators: Optional[List[Any]] = None,
        num_examine: int = 0,
    ):
        super().__init__(tokenizer, num_examine)
        self.evaluators = evaluators or []

    async def _evaluate_async(self, response: str, _data: Dict[str, Any]) -> float:
        """Run evaluators asynchronously."""
        if not self.evaluators:
            return 0.0

        reward = 1.0
        for evaluator in self.evaluators:
            try:
                result = await evaluator.evaluate(response)
                if not result.passed:
                    reward = 0.0
                    break
            except (RuntimeError, ValueError, TypeError) as e:
                logger.error("Evaluator error: {}", e)
                reward = 0.0
                break

        return reward

    def __call__(self, data: DataProto, return_dict: bool = False) -> Any:
        """
        Compute rewards using evaluators.

        Uses run_async_safely to handle both standalone and Ray actor contexts
        (where an event loop may already be running).
        """
        # Check for pre-computed rewards first
        if "rm_scores" in data.batch.keys():
            if return_dict:
                return {"reward_tensor": data.batch["rm_scores"]}
            return data.batch["rm_scores"]

        if "rewards" in data.non_tensor_batch:
            return super().__call__(data, return_dict)

        # Run evaluators
        batch_size = len(data)
        response_length = data.batch["responses"].shape[1]
        reward_tensor = torch.zeros((batch_size, response_length), dtype=torch.float32)
        reward_extra_info = defaultdict(list)

        for i in range(batch_size):
            data_item = data[i]

            prompt_length = data_item.batch["prompts"].shape[-1]
            response_ids = data_item.batch["responses"]
            valid_response_length = data_item.batch["attention_mask"][prompt_length:].sum()
            valid_response_ids = response_ids[:valid_response_length]

            response_str = self.tokenizer.decode(valid_response_ids, skip_special_tokens=True)

            # Use run_async_safely instead of asyncio.run() to avoid
            # "event loop already running" errors inside Ray actors
            if self.evaluators:
                reward = run_async_safely(self._evaluate_async(
                    response_str,
                    dict(data_item.non_tensor_batch)
                ))
            else:
                reward = 0.0

            if valid_response_length > 0:
                reward_tensor[i, valid_response_length - 1] = reward

            reward_extra_info["reward"].append(reward)

        if return_dict:
            return {
                "reward_tensor": reward_tensor,
                "reward_extra_info": dict(reward_extra_info),
            }
        return reward_tensor
