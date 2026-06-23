"""Tests for VERL DataProto adapter helpers."""

import pytest
from omegaconf import OmegaConf

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("tensordict")
pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.data_proto_adapter import (
    data_proto_to_rollout_samples,
    tokenized_rollout_batch_to_data_proto,
)
from mcpuniverse.rl.core.types import RolloutSample, TokenizedRolloutBatch


class _FakeTokenizer:
    """Small tokenizer stub for the veRL postprocess hot path."""

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
        raise AssertionError("adapter should use manual tensor padding, not tokenizer.pad")


class _FakeDataProto:
    """Minimal stand-in for verl.DataProto."""

    def __init__(self, non_tensor_batch):
        self.non_tensor_batch = non_tensor_batch


def test_data_proto_to_rollout_samples_basic():
    data_proto = _FakeDataProto({
        "instance_id": ["a", "b"],
        "instruction": ["do X", "do Y"],
    })

    samples = data_proto_to_rollout_samples(data_proto)

    assert [sample.instance_id for sample in samples] == ["a", "b"]
    assert [sample.instruction for sample in samples] == ["do X", "do Y"]


def test_data_proto_to_rollout_samples_preserves_known_and_extra_fields():
    data_proto = _FakeDataProto({
        "instance_id": ["a"],
        "instruction": ["do X"],
        "question": ["fallback"],
        "mcp_servers": [[{"name": "yf"}]],
        "evaluators": [[{"type": "exact"}]],
        "dockerfile_path": ["/tmp/Dockerfile"],
        "custom_key": [42],
    })

    samples = data_proto_to_rollout_samples(data_proto)

    assert len(samples) == 1
    sample = samples[0]
    assert isinstance(sample, RolloutSample)
    assert sample.instance_id == "a"
    assert sample.instruction == "do X"
    assert sample.question == "fallback"
    assert sample.mcp_servers == [{"name": "yf"}]
    assert sample.evaluators == [{"type": "exact"}]
    assert sample.metadata == {
        "dockerfile_path": "/tmp/Dockerfile",
        "custom_key": 42,
    }
    assert sample.to_dict() == {
        "instance_id": "a",
        "instruction": "do X",
        "question": "fallback",
        "output_format": None,
        "mcp_servers": [{"name": "yf"}],
        "evaluators": [{"type": "exact"}],
        "env_pool": {},
        "dockerfile_path": "/tmp/Dockerfile",
        "custom_key": 42,
    }


def test_data_proto_to_rollout_samples_uses_question_as_instruction_fallback():
    data_proto = _FakeDataProto({
        "instance_id": ["a"],
        "question": ["answer me"],
    })

    samples = data_proto_to_rollout_samples(data_proto)

    assert samples[0].instruction == "answer me"


def test_data_proto_to_rollout_samples_empty():
    data_proto = _FakeDataProto({})

    assert data_proto_to_rollout_samples(data_proto) == []


def test_data_proto_to_rollout_samples_inconsistent_lengths():
    data_proto = _FakeDataProto({
        "instance_id": ["a", "b"],
        "instruction": ["do X"],
    })

    with pytest.raises(ValueError, match="Inconsistent batch sizes"):
        data_proto_to_rollout_samples(data_proto)


def test_tokenized_rollout_batch_to_data_proto_builds_verl_batch():
    tokenized = TokenizedRolloutBatch(
        prompt_ids=[[11, 12], [21]],
        response_ids=[[101], [201, 202]],
        response_mask=[[1], [1, 0]],
        rewards=[1.0, 0.0],
        group_ids=["a", "b"],
        trajectories=[{"instance_id": "a"}, {"instance_id": "b"}],
        metrics={"num_collected": 2},
    )

    data_proto = tokenized_rollout_batch_to_data_proto(
        tokenized,
        config=OmegaConf.create({
            "data": {"max_prompt_length": 16, "max_response_length": 16},
        }),
        tokenizer=_FakeTokenizer(),
    )

    assert data_proto.batch["prompts"].tolist() == [[11, 12], [0, 21]]
    assert data_proto.batch["responses"].tolist() == [[101, 0], [201, 202]]
    assert data_proto.batch["response_mask"].tolist() == [[1, 0], [1, 0]]
    assert data_proto.non_tensor_batch["uid"].tolist() == ["a", "b"]
    assert data_proto.non_tensor_batch["response_lengths"].tolist() == [1, 2]
    assert data_proto.meta_info["rollout_metrics"] == {"num_collected": 2}


def test_tokenized_rollout_batch_to_data_proto_builds_uids_without_metadata():
    tokenized = TokenizedRolloutBatch(
        prompt_ids=[[11], [21], [31]],
        response_ids=[[101], [201], [301]],
        response_mask=[[1], [1], [1]],
        rewards=[1.0, 0.0, 1.0],
    )

    data_proto = tokenized_rollout_batch_to_data_proto(
        tokenized,
        tokenizer=_FakeTokenizer(),
        num_trajectories=2,
    )

    assert data_proto.non_tensor_batch["uid"].tolist() == [
        "instance_0",
        "instance_0",
        "instance_1",
    ]


def test_tokenized_rollout_batch_to_data_proto_builds_uids_from_trajectories():
    tokenized = TokenizedRolloutBatch(
        prompt_ids=[[11], [21]],
        response_ids=[[101], [201]],
        response_mask=[[1], [1]],
        rewards=[1.0, 0.0],
        trajectories=[
            {"instance_id": "task-a", "trajectory_id": 0},
            {"instance_id": "task-b", "trajectory_id": 0},
        ],
    )

    data_proto = tokenized_rollout_batch_to_data_proto(
        tokenized,
        tokenizer=_FakeTokenizer(),
    )

    assert data_proto.non_tensor_batch["uid"].tolist() == ["task-a", "task-b"]


def test_tokenized_rollout_batch_to_data_proto_response_lengths_follow_truncation():
    tokenized = TokenizedRolloutBatch(
        prompt_ids=[[11, 12, 13]],
        response_ids=[[101, 102, 103]],
        response_mask=[[1, 1, 0]],
        rewards=[1.0],
        group_ids=["task-a"],
    )

    data_proto = tokenized_rollout_batch_to_data_proto(
        tokenized,
        config=OmegaConf.create({
            "data": {"max_prompt_length": 2, "max_response_length": 2},
        }),
        tokenizer=_FakeTokenizer(),
    )

    assert data_proto.batch["prompts"].tolist() == [[12, 13]]
    assert data_proto.batch["responses"].tolist() == [[101, 102]]
    assert data_proto.batch["response_mask"].tolist() == [[1, 1]]
    assert data_proto.non_tensor_batch["response_lengths"].tolist() == [2]


def test_tokenized_rollout_batch_to_data_proto_rejects_non_tokenized_batch():
    with pytest.raises(TypeError, match="TokenizedRolloutBatch"):
        tokenized_rollout_batch_to_data_proto(
            object(),
            tokenizer=_FakeTokenizer(),
        )
