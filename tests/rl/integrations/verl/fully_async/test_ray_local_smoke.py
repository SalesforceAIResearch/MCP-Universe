"""Opt-in local Ray runtime smoke tests for fully async runtime pieces."""

import os

import pytest
from omegaconf import OmegaConf


@pytest.mark.integration
@pytest.mark.ray
def test_message_queue_actor_runs_in_local_ray_runtime_when_enabled():
    if os.getenv("MCP_RUN_RAY_TESTS") != "1":
        pytest.skip("set MCP_RUN_RAY_TESTS=1 to run Ray smoke tests")

    ray = pytest.importorskip("ray")
    from verl.experimental.fully_async_policy.message_queue import (
        MessageQueue,
        MessageQueueClient,
    )

    queue = None
    ray.shutdown()
    # MessageQueue is an async actor; current Ray rejects async actors under
    # local_mode=True, so this uses a real single-node local Ray runtime.
    # Force address="local" so the test always starts its own isolated cluster
    # instead of attaching to an ambient one (RAY_ADDRESS / a running cluster),
    # which would reject the num_cpus argument below.
    ray.init(
        address="local",
        ignore_reinit_error=True,
        include_dashboard=False,
        log_to_driver=False,
        num_cpus=2,
    )
    try:
        queue = MessageQueue.remote(
            OmegaConf.create({"async_training": {"staleness_threshold": 2}}),
            max_queue_size=2,
        )
        client = MessageQueueClient(queue)

        assert client.put_sample_sync({"sample": 1}, param_version=0) is True
        assert client.put_sample_sync({"sample": 2}, param_version=0) is True
        assert client.put_sample_sync({"sample": 3}, param_version=0) is False

        sample, remaining = client.get_sample_sync()
        assert sample == {"sample": 2}
        assert remaining == 1

        client.update_param_version_sync(5)
        stats = client.get_statistics_sync()
        assert stats["queue_size"] == 1
        assert stats["total_produced"] == 3
        assert stats["total_consumed"] == 1
        assert stats["dropped_samples"] == 1
        assert stats["current_param_version"] == 5
        assert stats["staleness_threshold"] == 2
        assert stats["max_queue_size"] == 2

        ray.get(queue.shutdown.remote())
        assert client.get_sample_sync() == ({"sample": 3}, 0)
        assert client.get_sample_sync() is None
    finally:
        if queue is not None:
            try:
                ray.get(queue.shutdown.remote(), timeout=5)
            except Exception:
                pass
        ray.shutdown()
