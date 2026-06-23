"""Tests for mcp_dataset.py — MCPDataset, create_mcp_dataset, mcp_collate_fn."""

import json
import os
import tempfile

import pytest

# mcp_dataset imports torch, and importing it pulls in the verl integration
# package __init__ (which needs verl too). Both are optional extras not present
# in minimal CI, so skip this module gracefully when they are unavailable.
pytest.importorskip("torch")
pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.mcp_dataset import (
    MCPDataset,
    create_mcp_dataset,
    mcp_collate_fn,
)


@pytest.fixture
def sample_data_file(tmp_path):
    data = [
        {
            "instance_id": "test_001",
            "instruction": "Query the database",
            "output_format": {"type": "json"},
            "mcp_servers": [{"name": "postgres"}],
            "evaluators": [{"type": "exact_match"}],
            "category": "database",
        },
        {
            "instance_id": "test_002",
            "instruction": "Browse the web",
            "mcp_servers": [{"name": "playwright"}],
            "evaluators": [],
        },
    ]
    path = tmp_path / "train.json"
    path.write_text(json.dumps(data))
    return str(path)


class TestMCPDataset:
    def test_len(self, sample_data_file):
        ds = MCPDataset(sample_data_file)
        assert len(ds) == 2

    def test_getitem_core_fields(self, sample_data_file):
        ds = MCPDataset(sample_data_file)
        item = ds[0]
        assert item["instance_id"] == "test_001"
        assert "Query the database" in item["instruction"]
        assert item["mcp_servers"] == [{"name": "postgres"}]
        assert item["category"] == "database"

    def test_getitem_output_format_appended(self, sample_data_file):
        ds = MCPDataset(sample_data_file)
        item = ds[0]
        assert "Output format:" in item["instruction"]
        assert '"type": "json"' in item["instruction"]

    def test_getitem_missing_fields_default(self, sample_data_file):
        ds = MCPDataset(sample_data_file)
        item = ds[1]
        assert item["category"] == "unknown"
        assert item["output_format"] is None

    def test_getitem_auto_instance_id(self, tmp_path):
        data = [{"instruction": "hello"}]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(data))
        ds = MCPDataset(str(path))
        item = ds[0]
        assert item["instance_id"] == "sample_0"

    def test_passthrough_extra_keys(self, tmp_path):
        data = [{"instruction": "x", "dockerfile_path": "/tmp/Dockerfile", "custom_key": 42}]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(data))
        ds = MCPDataset(str(path))
        item = ds[0]
        assert item["dockerfile_path"] == "/tmp/Dockerfile"
        assert item["custom_key"] == 42


class TestCreateMCPDataset:
    def test_basic(self, sample_data_file):
        config = {"max_length": 2048}
        ds = create_mcp_dataset(sample_data_file, config)
        assert isinstance(ds, MCPDataset)
        assert ds.max_length == 2048

    def test_default_max_length(self, sample_data_file):
        class _Cfg:
            pass
        ds = create_mcp_dataset(sample_data_file, _Cfg())
        assert ds.max_length == 4096


class TestMCPCollateFn:
    def test_collate(self):
        batch = [
            {"instance_id": "a", "instruction": "do X", "extra": 1},
            {"instance_id": "b", "instruction": "do Y"},
        ]
        result = mcp_collate_fn(batch)
        ntb = result["non_tensor_batch"]
        assert ntb["instance_id"] == ["a", "b"]
        assert ntb["instruction"] == ["do X", "do Y"]
        assert ntb["extra"] == [1, None]  # missing key -> None
