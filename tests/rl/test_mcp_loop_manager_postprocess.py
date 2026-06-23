"""Tests for MCPLoopManager rollout postprocessing."""

from types import SimpleNamespace

import numpy as np
import pytest
from omegaconf import OmegaConf

pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.data_proto_padding import concat_padded_dataprotos
from mcpuniverse.rl.integrations.verl.mcp_loop_manager import MCPLoopManager
from mcpuniverse.rl.core.postprocess import collect_tokenized_rollout_results
from mcpuniverse.rl.core.types import TokenizedRolloutBatch

class _FakeTokenizer:
    pad_token_id = 0

    def __init__(self):
        self.padding_side = "right"

    def pad(
        self,
        features,
        *,
        padding,
        max_length,
        return_tensors,
        return_attention_mask,
    ):
        assert padding == "max_length"
        assert return_tensors == "pt"
        assert return_attention_mask is True

        import torch

        input_ids = []
        attention_mask = []
        for feature in features:
            ids = list(feature["input_ids"])[:max_length]
            pad_len = max_length - len(ids)
            if self.padding_side == "left":
                padded = [self.pad_token_id] * pad_len + ids
                mask = [0] * pad_len + [1] * len(ids)
            else:
                padded = ids + [self.pad_token_id] * pad_len
                mask = [1] * len(ids) + [0] * pad_len
            input_ids.append(padded)
            attention_mask.append(mask)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        }


def _manager(max_prompt=16, max_response=16, num_trajectories=2):
    manager = MCPLoopManager.__new__(MCPLoopManager)
    manager._closed = True
    manager.config = OmegaConf.create({
        "data": {
            "max_prompt_length": max_prompt,
            "max_response_length": max_response,
        },
    })
    manager.tokenizer = _FakeTokenizer()
    manager.num_trajectories = num_trajectories
    return manager


def test_postprocess_builds_padding_masks_positions_and_uids():
    output = TokenizedRolloutBatch(
        prompt_ids=[[11, 12], [21]],
        response_ids=[[101, 102, 103], [201, 202]],
        response_mask=[[1, 0, 1], [1, 1]],
        rewards=[1.0, 0.0],
        metrics={"num_collected": 2},
        trajectories=[{"instance_id": "a"}, {"instance_id": "b"}],
    )

    dp = _manager()._postprocess(output)

    assert dp.batch["prompts"].tolist() == [[11, 12], [0, 21]]
    assert dp.batch["responses"].tolist() == [[101, 102, 103], [201, 202, 0]]
    assert dp.batch["response_mask"].tolist() == [[1, 0, 1], [1, 1, 0]]
    assert dp.batch["attention_mask"].tolist() == [[1, 1, 1, 1, 1], [0, 1, 1, 1, 0]]
    assert dp.batch["position_ids"].tolist() == [[0, 1, 2, 3, 4], [0, 0, 1, 2, 0]]
    assert dp.non_tensor_batch["rewards"].tolist() == [1.0, 0.0]
    assert dp.non_tensor_batch["uid"].tolist() == ["a", "b"]
    assert len(dp.non_tensor_batch["trajectories"]) == 2


def test_postprocess_truncates_response_and_loss_mask_together():
    output = TokenizedRolloutBatch(
        prompt_ids=[[1, 2, 3]],
        response_ids=[[4, 5, 6]],
        response_mask=[[1, 0, 1]],
        rewards=[0.5],
        trajectories=[{"instance_id": "a"}],
    )

    dp = _manager(max_prompt=2, max_response=2, num_trajectories=1)._postprocess(output)

    assert dp.batch["prompts"].tolist() == [[2, 3]]
    assert dp.batch["responses"].tolist() == [[4, 5]]
    assert dp.batch["response_mask"].tolist() == [[1, 0]]


def test_postprocess_rejects_inconsistent_rollout_output():
    output = TokenizedRolloutBatch(
        prompt_ids=[[1]],
        response_ids=[[2, 3]],
        response_mask=[[1]],
        rewards=[0.0],
        trajectories=[{"instance_id": "a"}],
    )

    with pytest.raises(ValueError, match="Inconsistent mask length"):
        _manager(num_trajectories=1)._postprocess(output)


def test_postprocess_rejects_partial_trajectory_metadata():
    output = TokenizedRolloutBatch(
        prompt_ids=[[1], [2]],
        response_ids=[[3], [4]],
        response_mask=[[1], [1]],
        rewards=[0.0, 1.0],
        trajectories=[{"instance_id": "a"}],
    )

    with pytest.raises(ValueError, match="trajectories has 1 entries"):
        _manager()._postprocess(output)


def test_per_instance_concat_matches_single_dataproto_postprocess():
    def make_single_output():
        return TokenizedRolloutBatch(
            prompt_ids=[[1, 2], [3], [4, 5, 6]],
            response_ids=[[10], [11, 12], [13, 14, 15, 16]],
            response_mask=[[1], [1, 0], [1, 0, 1, 0]],
            rewards=[1.0, 0.0, 0.5],
            metrics={"num_collected": 3},
            trajectories=[
                {"instance_id": "a", "trajectory_id": 0},
                {"instance_id": "a", "trajectory_id": 1},
                {"instance_id": "b", "trajectory_id": 0},
            ],
        )

    def make_instance_outputs():
        return [
            TokenizedRolloutBatch(
                prompt_ids=[[1, 2], [3]],
                response_ids=[[10], [11, 12]],
                response_mask=[[1], [1, 0]],
                rewards=[1.0, 0.0],
                metrics={"num_collected": 2},
                trajectories=[
                    {"instance_id": "a", "trajectory_id": 0},
                    {"instance_id": "a", "trajectory_id": 1},
                ],
            ),
            TokenizedRolloutBatch(
                prompt_ids=[[4, 5, 6]],
                response_ids=[[13, 14, 15, 16]],
                response_mask=[[1, 0, 1, 0]],
                rewards=[0.5],
                metrics={"num_collected": 1},
                trajectories=[
                    {"instance_id": "b", "trajectory_id": 0},
                ],
            ),
        ]

    manager = _manager()
    single = manager._postprocess(make_single_output())
    per_instance = [manager._postprocess(output) for output in make_instance_outputs()]
    merged = concat_padded_dataprotos(
        per_instance,
        pad_token_id=0,
        context="test rollout",
    )

    for key in (
        "prompts",
        "responses",
        "response_mask",
        "input_ids",
        "attention_mask",
        "position_ids",
    ):
        assert merged.batch[key].tolist() == single.batch[key].tolist()

    assert merged.non_tensor_batch["uid"].tolist() == single.non_tensor_batch["uid"].tolist()
    assert merged.non_tensor_batch["rewards"].tolist() == single.non_tensor_batch["rewards"].tolist()
    assert "global_token_num" not in merged.meta_info
    assert merged.meta_info["rollout_metrics"] == {"num_collected": 2}


def test_tokenize_result_prefers_live_tito_llm_tokens():
    manager = _manager(num_trajectories=1)
    manager.rollout_mode = "token"

    result = SimpleNamespace(
        trace=SimpleNamespace(full_text=""),
        response="unused",
    )
    traj = SimpleNamespace(
        result=result,
        data={"instruction": "unused"},
        get_tito_tokens=lambda: ([11, 12], [101, 102], [1, 0]),
        get_trace_text=lambda: "",
        get_instruction=lambda: "unused",
        get_response_text=lambda: "unused",
    )

    prompt_tokens, response_tokens, loss_mask = manager._tokenize_result(
        traj, "instance", 0,
    )

    assert prompt_tokens == [11, 12]
    assert response_tokens == [101, 102]
    assert loss_mask == [1, 0]


def test_tokenize_result_preserves_live_tito_array_buffers():
    manager = _manager(num_trajectories=1)
    manager.rollout_mode = "token"
    prompt_buffer = np.array([11, 12], dtype=np.int64)
    response_buffer = np.array([101, 102], dtype=np.int64)

    traj = SimpleNamespace(
        result=SimpleNamespace(trace=SimpleNamespace(full_text=""), response="unused"),
        data={"instruction": "unused"},
        get_tito_tokens=lambda: (prompt_buffer, response_buffer, [1, 0]),
        get_trace_text=lambda: "",
        get_instruction=lambda: "unused",
        get_response_text=lambda: "unused",
    )

    prompt_tokens, response_tokens, loss_mask = manager._tokenize_result(
        traj, "instance", 0,
    )

    assert prompt_tokens is prompt_buffer
    assert response_tokens is response_buffer
    assert loss_mask == [1, 0]


def test_collect_tokenized_rollout_results_skips_missing_results_without_placeholder_rows():
    manager = _manager(num_trajectories=2)

    completed = SimpleNamespace(result=SimpleNamespace(reward=0.75))
    missing = SimpleNamespace(result=None)
    trajectories = {"task-a": {0: completed, 1: missing}}

    output = collect_tokenized_rollout_results(
        trajectories,
        batch=[{"instruction": "x"}],
        num_trajectories=2,
        tokenize_trajectory_fn=lambda *_args: ([11], [21, 22], [1, 1]),
    )
    output = manager._finalize_tokenized_rollout(output, [{"instruction": "x"}], 2)

    assert [list(ids) for ids in output.prompt_ids] == [[11]]
    assert [list(ids) for ids in output.response_ids] == [[21, 22]]
    assert [list(mask) for mask in output.response_mask] == [[1, 1]]
    assert output.rewards == [0.75]
    assert output.trajectories == [{"instance_id": "task-a", "trajectory_id": 0}]
    assert output.metrics["num_trajectories"] == 2
    assert output.metrics["num_collected"] == 1
    assert output.metrics["num_missing"] == 1
    assert "missing_results" not in output.metrics


def test_postprocess_per_instance_splits_tokenized_batch():
    """``_postprocess_per_instance`` groups trajectories by ``group_ids`` /
    ``instance_id`` and runs the standard ``_postprocess`` once per group.

    Used by the fully-async rollouter to get per-instance DataProtos for
    queue granularity and dynamic padding.
    """
    manager = _manager(num_trajectories=2)
    manager.val_num_trajectories = 1
    captured = []

    def fake_postprocess(batch):
        captured.append(batch)
        return SimpleNamespace(meta_info={"rollout_metrics": batch.metrics})

    manager._postprocess = fake_postprocess

    output = TokenizedRolloutBatch(
        prompt_ids=[[1], [2], [3]],
        response_ids=[[10], [11], [12]],
        response_mask=[[1], [1], [0]],
        rewards=[1.0, 0.0, 0.5],
        group_ids=["a", "a", "b"],
        trajectories=[
            {"instance_id": "a", "trajectory_id": 0},
            {"instance_id": "a", "trajectory_id": 1},
            {"instance_id": "b", "trajectory_id": 0},
        ],
    )

    result = manager._postprocess_per_instance(output)

    assert len(result) == 2
    assert [batch.prompt_ids for batch in captured] == [[[1], [2]], [[3]]]
    assert [batch.response_mask for batch in captured] == [[[1], [1]], [[0]]]
    assert [batch.group_ids for batch in captured] == [["a", "a"], ["b"]]
    assert captured[0].metrics["num_collected"] == 2
    assert captured[1].metrics["num_collected"] == 1


def test_postprocess_per_instance_uses_val_num_trajectories_when_val_mode():
    """In val mode the fallback grouping uses ``val_num_trajectories``."""
    manager = _manager(num_trajectories=4)
    manager.val_num_trajectories = 1
    captured = []
    manager._postprocess = lambda batch: captured.append(batch) or batch

    # No group_ids -> falls back to instance_id from trajectories, which is also
    # absent -> uses generated f"instance_{idx // num_trajectories}". With
    # val_num_trajectories=1 each row gets its own instance.
    output = TokenizedRolloutBatch(
        prompt_ids=[[1], [2]],
        response_ids=[[10], [11]],
        response_mask=[[1], [1]],
        rewards=[1.0, 0.0],
        group_ids=[],
        trajectories=[],
    )

    result = manager._postprocess_per_instance(output, val_mode=True)

    assert len(result) == 2
    assert len(captured) == 2
