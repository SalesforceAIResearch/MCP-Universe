"""Tests for fully_async/mcp_async_data.py — padding helpers and MCPRolloutSample."""

import pytest

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# Skip the whole module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("tensordict")
pytest.importorskip("verl")

import torch

from mcpuniverse.rl.integrations.verl.fully_async.mcp_async_data import (
    MCPRolloutSample,
)
from mcpuniverse.rl.integrations.verl.data_proto_padding import (
    _left_pad,
    _right_pad,
    _lr_pad,
)


class TestLeftPad:
    def test_basic(self):
        t = torch.tensor([[1, 2, 3]])
        result = _left_pad(t, 2, pad_val=0)
        assert result.shape == (1, 5)
        assert result.tolist() == [[0, 0, 1, 2, 3]]

    def test_zero_pad(self):
        t = torch.tensor([[1, 2]])
        result = _left_pad(t, 0)
        assert torch.equal(result, t)

    def test_custom_pad_val(self):
        t = torch.tensor([[5, 6]])
        result = _left_pad(t, 1, pad_val=99)
        assert result.tolist() == [[99, 5, 6]]

    def test_batch(self):
        t = torch.tensor([[1, 2], [3, 4]])
        result = _left_pad(t, 3, pad_val=0)
        assert result.shape == (2, 5)
        assert result[0].tolist() == [0, 0, 0, 1, 2]


class TestRightPad:
    def test_basic(self):
        t = torch.tensor([[1, 2, 3]])
        result = _right_pad(t, 2)
        assert result.shape == (1, 5)
        assert result.tolist() == [[1, 2, 3, 0, 0]]

    def test_zero_pad(self):
        t = torch.tensor([[1]])
        result = _right_pad(t, 0)
        assert torch.equal(result, t)


class TestLRPad:
    def test_both(self):
        t = torch.tensor([[10, 20]])
        result = _lr_pad(t, left=1, right=2, pad_val=0)
        assert result.tolist() == [[0, 10, 20, 0, 0]]

    def test_left_only(self):
        t = torch.tensor([[1]])
        result = _lr_pad(t, left=2, right=0)
        assert result.tolist() == [[0, 0, 1]]

    def test_right_only(self):
        t = torch.tensor([[1]])
        result = _lr_pad(t, left=0, right=2)
        assert result.tolist() == [[1, 0, 0]]

    def test_no_pad(self):
        t = torch.tensor([[1, 2]])
        result = _lr_pad(t, left=0, right=0)
        assert torch.equal(result, t)


class TestMCPRolloutSample:
    def test_defaults(self):
        sample = MCPRolloutSample(data=None)
        assert sample.param_version == 0
        assert sample.instance_id == ""
        assert sample.processing_time == 0.0
        assert sample.rollout_status == {}
