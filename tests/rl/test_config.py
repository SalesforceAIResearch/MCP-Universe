"""Tests for config.py — RolloutConfig.from_dict parsing."""

import pytest
from mcpuniverse.rl.config import RolloutConfig


class TestFromDict:
    def test_trace_log_dir_parsed(self):
        cfg = RolloutConfig.from_dict({"trace_log_dir": "/tmp/traces"})
        assert cfg.trace_log_dir == "/tmp/traces"

    def test_trace_log_dir_default_none(self):
        cfg = RolloutConfig.from_dict({})
        assert cfg.trace_log_dir is None

    def test_basic_fields(self):
        cfg = RolloutConfig.from_dict({
            "llm_type": "openai",
            "rollout_mode": "token",
            "formatter_type": "qwen",
        })
        assert cfg.llm_type == "openai"
        assert cfg.rollout_mode == "token"
        assert cfg.formatter_type == "qwen"

    def test_mcp_servers_string_shorthand(self):
        cfg = RolloutConfig.from_dict({
            "mcp_servers": ["weather", "calculator"],
        })
        assert len(cfg.mcp_servers) == 2
        assert cfg.mcp_servers[0].name == "weather"
        assert cfg.mcp_servers[1].name == "calculator"

    def test_llm_config_string_shorthand(self):
        cfg = RolloutConfig.from_dict({"llm_config": "my-model"})
        assert cfg.llm_config == {"model_name": "my-model"}

    def test_env_pool_auto_enabled_for_docker_pool(self):
        cfg = RolloutConfig.from_dict({"mcp_transport": "docker_pool"})
        assert cfg.env_pool.enabled is True

    def test_env_pool_not_auto_enabled_for_stdio(self):
        cfg = RolloutConfig.from_dict({"mcp_transport": "stdio"})
        assert cfg.env_pool.enabled is False
