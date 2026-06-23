"""Tests for MCP veRL old-log-prob entropy helpers."""

from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

torch = pytest.importorskip("torch")
pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.mcp_log_prob_entropy import (
    pop_entropy_metric_if_present,
    should_skip_entropy_for_log_prob,
)


def test_should_skip_entropy_requires_zero_coeff_without_forced_entropy():
    assert should_skip_entropy_for_log_prob(OmegaConf.create({"entropy_coeff": 0.0}))
    assert should_skip_entropy_for_log_prob(OmegaConf.create({"entropy_coeff": "0"}))

    assert not should_skip_entropy_for_log_prob(OmegaConf.create({"entropy_coeff": 0.001}))
    assert not should_skip_entropy_for_log_prob(OmegaConf.create({}))
    assert not should_skip_entropy_for_log_prob(
        OmegaConf.create({"entropy_coeff": 0.0, "calculate_entropy": True})
    )


def test_pop_entropy_metric_marks_intentional_skip_when_absent():
    old_log_prob = SimpleNamespace(batch={"old_log_probs": torch.zeros(2, 3)})
    batch = SimpleNamespace(batch={"response_mask": torch.ones(2, 3)})
    metrics = {}

    pop_entropy_metric_if_present(
        old_log_prob=old_log_prob,
        batch=batch,
        actor_config=OmegaConf.create({"entropy_coeff": 0.0, "loss_agg_mode": "token-mean"}),
        metrics=metrics,
        agg_loss=lambda **_: torch.tensor(999.0),
    )

    assert metrics == {"actor/entropy_skipped": 1.0}
    assert "entropys" not in old_log_prob.batch


def test_pop_entropy_metric_rejects_missing_entropy_when_not_skipped():
    old_log_prob = SimpleNamespace(batch={"old_log_probs": torch.zeros(2, 3)})
    batch = SimpleNamespace(batch={"response_mask": torch.ones(2, 3)})

    with pytest.raises(KeyError, match="entropy skipping is not enabled"):
        pop_entropy_metric_if_present(
            old_log_prob=old_log_prob,
            batch=batch,
            actor_config=OmegaConf.create({"entropy_coeff": 0.001, "loss_agg_mode": "token-mean"}),
            metrics={},
            agg_loss=lambda **_: torch.tensor(999.0),
        )


def test_pop_entropy_metric_records_and_removes_present_entropy():
    old_log_prob = SimpleNamespace(
        batch={
            "old_log_probs": torch.zeros(2, 3),
            "entropys": torch.tensor([[1.0, 2.0, 0.0], [3.0, 0.0, 0.0]]),
        }
    )
    batch = SimpleNamespace(
        batch={"response_mask": torch.tensor([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]])}
    )
    actor_config = OmegaConf.create({"loss_agg_mode": "token-mean", "loss_scale_factor": 2.0})
    metrics = {}

    def agg_loss(**kwargs):
        assert kwargs["loss_agg_mode"] == "token-mean"
        assert kwargs["loss_scale_factor"] == 2.0
        return (kwargs["loss_mat"] * kwargs["loss_mask"]).sum() / kwargs["loss_mask"].sum()

    pop_entropy_metric_if_present(
        old_log_prob=old_log_prob,
        batch=batch,
        actor_config=actor_config,
        metrics=metrics,
        agg_loss=agg_loss,
    )

    assert metrics == {"actor/entropy": 2.0}
    assert "entropys" not in old_log_prob.batch
