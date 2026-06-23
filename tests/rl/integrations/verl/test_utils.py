"""Tests for utils.py — pure utility functions (no Ray/GPU required)."""

import asyncio
import pickle

import pytest

# utils imports ray + verl at module load (optional extras not present in
# minimal CI), so skip the whole module gracefully when they are unavailable.
pytest.importorskip("ray")
pytest.importorskip("verl")

from mcpuniverse.rl.integrations.verl.utils import (
    _LazyLogger,
    compute_validation_reward_metrics,
    safe_get,
    retry_delay,
    run_async_safely,
)


class TestSafeGet:
    def test_dict(self):
        assert safe_get({"a": 1}, "a") == 1

    def test_dict_missing(self):
        assert safe_get({"a": 1}, "b", 42) == 42

    def test_dict_none_value(self):
        assert safe_get({"a": None}, "a", "default") == "default"

    def test_object_attr(self):
        class Cfg:
            x = 10
        assert safe_get(Cfg(), "x") == 10

    def test_object_missing(self):
        class Cfg:
            pass
        assert safe_get(Cfg(), "x", -1) == -1

    def test_none_cfg(self):
        assert safe_get(None, "x", "fallback") == "fallback"


class TestRetryDelay:
    def test_first_attempt(self):
        d = retry_delay(0, base_delay=2.0, max_delay=30.0)
        assert 2.0 <= d <= 3.0  # 2.0 * 1.5^0 + jitter(0,1)

    def test_increasing(self):
        d0 = retry_delay(0, base_delay=2.0, max_delay=100.0, backoff_factor=2.0)
        d3 = retry_delay(3, base_delay=2.0, max_delay=100.0, backoff_factor=2.0)
        # d3 base = 2.0 * 2.0^3 = 16.0; d0 base = 2.0
        assert d3 > d0 - 1  # accounting for jitter

    def test_capped(self):
        d = retry_delay(100, base_delay=2.0, max_delay=5.0)
        assert d <= 5.0


class TestLazyLogger:
    def test_logging_methods(self):
        log = _LazyLogger()
        # Should not raise — delegates to loguru
        log.info("test message")

    def test_pickle_roundtrip(self):
        log = _LazyLogger()
        restored = pickle.loads(pickle.dumps(log))
        assert isinstance(restored, _LazyLogger)
        restored.debug("after pickle")


class TestValidationRewardMetrics:
    def test_uses_requested_denominator_when_rollouts_are_missing(self):
        metrics = compute_validation_reward_metrics(
            [1.0, 1.0, 0.0],
            num_requested=5,
        )

        assert metrics["val/num_samples"] == 5
        assert metrics["val/num_collected"] == 3
        assert metrics["val/num_missing"] == 2
        assert metrics["val/success_rate"] == 2 / 5
        assert metrics["val/mean_reward"] == 2 / 5
        assert metrics["val/success_rate_collected"] == 2 / 3
        assert metrics["val/mean_reward_collected"] == 2 / 3

    def test_all_missing_validation_scores_zero_without_fake_rows(self):
        metrics = compute_validation_reward_metrics([], num_requested=4)

        assert metrics["val/num_samples"] == 4
        assert metrics["val/num_collected"] == 0
        assert metrics["val/num_missing"] == 4
        assert metrics["val/success_rate"] == 0
        assert metrics["val/mean_reward"] == 0


class TestRunAsyncSafely:
    def test_simple_coroutine(self):
        async def add(a, b):
            return a + b
        assert run_async_safely(add(2, 3)) == 5

    def test_inside_event_loop(self):
        """run_async_safely should work even when called from within a running loop."""
        result = None

        async def outer():
            nonlocal result
            async def inner():
                return 42
            result = run_async_safely(inner())

        asyncio.run(outer())
        assert result == 42
