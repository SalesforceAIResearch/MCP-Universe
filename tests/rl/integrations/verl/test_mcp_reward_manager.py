"""Tests for MCP reward managers."""

import numpy as np

import pytest

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("tensordict")
pytest.importorskip("verl")

import torch
from tensordict import TensorDict
from verl import DataProto

from mcpuniverse.rl.integrations.verl.mcp_reward_manager import MCPRewardManager


class _Tokenizer:
    def decode(self, ids, skip_special_tokens=True):  # pylint: disable=unused-argument
        if hasattr(ids, "tolist"):
            ids = ids.tolist()
        return ",".join(str(int(i)) for i in ids)


class _CountingTokenizer(_Tokenizer):
    def __init__(self):
        self.decode_calls = 0

    def decode(self, ids, skip_special_tokens=True):
        self.decode_calls += 1
        return super().decode(ids, skip_special_tokens=skip_special_tokens)


def _data_proto(*, rewards=None, rm_scores=None, response_lengths=None) -> DataProto:
    batch = {
        "prompts": torch.tensor([[1, 2], [0, 3]], dtype=torch.long),
        "responses": torch.tensor([[10, 11, 0], [12, 0, 0]], dtype=torch.long),
        "attention_mask": torch.tensor(
            [
                [1, 1, 1, 1, 0],  # two valid response tokens
                [0, 1, 1, 0, 0],  # one valid response token
            ],
            dtype=torch.long,
        ),
    }
    if rm_scores is not None:
        batch["rm_scores"] = rm_scores
    non_tensor_batch = {}
    if rewards is not None:
        non_tensor_batch["rewards"] = np.array(rewards, dtype=float)
    if response_lengths is not None:
        non_tensor_batch["response_lengths"] = np.array(response_lengths, dtype=np.int64)
    return DataProto(
        batch=TensorDict(batch, batch_size=2),
        non_tensor_batch=non_tensor_batch,
        meta_info={},
    )


def test_reward_manager_places_precomputed_rewards_on_last_valid_response_token():
    manager = MCPRewardManager(_Tokenizer())

    result = manager(_data_proto(rewards=[0.75, -0.25]), return_dict=True)

    assert result["reward_tensor"].tolist() == [
        [0.0, 0.75, 0.0],
        [-0.25, 0.0, 0.0],
    ]
    assert result["reward_extra_info"] == {"reward": [0.75, -0.25]}


def test_reward_manager_precomputed_rewards_skip_decode_when_examining():
    tokenizer = _CountingTokenizer()
    manager = MCPRewardManager(tokenizer, num_examine=1)

    manager(_data_proto(rewards=[0.75, -0.25]), return_dict=True)

    assert tokenizer.decode_calls == 0


def test_reward_manager_uses_response_lengths_without_scanning_attention_mask():
    manager = MCPRewardManager(_Tokenizer())

    result = manager(
        _data_proto(rewards=[0.75, -0.25], response_lengths=[3, 2]),
        return_dict=True,
    )

    assert result["reward_tensor"].tolist() == [
        [0.0, 0.0, 0.75],
        [0.0, -0.25, 0.0],
    ]


def test_reward_manager_returns_existing_rm_scores_without_recomputing():
    rm_scores = torch.tensor([[0.0, 1.0, 0.0], [0.5, 0.0, 0.0]])
    manager = MCPRewardManager(_Tokenizer())

    result = manager(_data_proto(rm_scores=rm_scores), return_dict=True)

    assert result == {"reward_tensor": rm_scores}


def test_reward_manager_returns_empty_reward_when_batch_is_none():
    # Regression: upstream rollout returning 0 trajectories (e.g. env-pool
    # docker daemon unreachable / all MCP servers failed to init) used to
    # crash here with ``AttributeError: 'NoneType' object has no attribute
    # 'keys'`` and surface as a confusing downstream error instead of the
    # real env-pool failure. Guard returns an empty reward tensor so caller
    # can detect the empty batch and log a meaningful warning.
    manager = MCPRewardManager(_Tokenizer())

    empty_proto = DataProto(batch=None, non_tensor_batch={}, meta_info={})
    result = manager(empty_proto, return_dict=True)

    assert result["reward_tensor"].numel() == 0
    assert result["reward_extra_info"] == {}


def test_reward_manager_returns_empty_reward_when_data_is_none():
    manager = MCPRewardManager(_Tokenizer())

    # Bare-tensor return path (return_dict=False)
    reward_tensor = manager(None, return_dict=False)
    assert isinstance(reward_tensor, torch.Tensor)
    assert reward_tensor.numel() == 0


def test_reward_manager_compute_score_decodes_valid_prompt_and_response_tokens():
    calls = []

    def compute_score(prompt, response, non_tensor):
        calls.append((prompt, response, dict(non_tensor)))
        return 1.0 if response == "10,11" else 0.0

    manager = MCPRewardManager(_Tokenizer(), compute_score=compute_score)

    reward_tensor = manager(_data_proto())

    assert reward_tensor.tolist() == [
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0],
    ]
    assert calls[0] == ("1,2", "10,11", {})
    assert calls[1] == ("3", "12", {})
