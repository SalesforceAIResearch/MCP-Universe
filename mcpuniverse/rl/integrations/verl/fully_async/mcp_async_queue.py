"""Queue consumption helpers for fully async MCP training."""

import time
from dataclasses import dataclass
from typing import Any, List

import ray
from loguru import logger

from .mcp_async_data import MCP_BATCH_END_SENTINEL, MCPRolloutSample


@dataclass
class QueueCollection:
    """Rollout samples collected for one trainer batch."""

    samples: List[MCPRolloutSample]
    total_trajectories: int
    queue_len: int
    total_wait_time: float


def collect_rollout_samples_from_queue(
    message_queue_client: Any,
    *,
    required_tasks: int,
    required_trajectories: int,
    partial_rollout: bool,
    task_alignment_unit: int,
) -> QueueCollection:
    """Collect task items from a message queue without assembling tensors."""
    logger.info(
        "Requesting {} task items from queue (nominal {} trajectories)",
        required_tasks, required_trajectories,
    )

    consumer_start = time.time()
    rollout_samples = []
    total_trajectories = 0
    queue_len = 0

    while len(rollout_samples) < required_tasks:
        result = message_queue_client.get_sample_sync()

        if result is None:
            logger.info(
                "Queue closed (None). Collected {}/{} task items "
                "({}/{} nominal trajectories)",
                len(rollout_samples), required_tasks,
                total_trajectories, required_trajectories,
            )
            break

        sample_bytes, queue_len = result

        if sample_bytes is None:
            logger.info(
                "Termination signal received. Collected {}/{} task items "
                "({}/{} nominal trajectories)",
                len(rollout_samples), required_tasks,
                total_trajectories, required_trajectories,
            )
            break

        if sample_bytes == MCP_BATCH_END_SENTINEL:
            if not partial_rollout:
                logger.info(
                    "Batch-end sentinel received with {}/{} task items "
                    "({}/{} nominal trajectories); "
                    "partial_rollout=false, continuing collection.",
                    len(rollout_samples), required_tasks,
                    total_trajectories, required_trajectories,
                )
                continue
            if rollout_samples and len(rollout_samples) % task_alignment_unit == 0:
                logger.info(
                    "Aligned partial batch-end sentinel received with {}/{} "
                    "task items ({} trajectories); accepting partial batch.",
                    len(rollout_samples), required_tasks, total_trajectories,
                )
                break
            logger.info(
                "Batch-end sentinel received with {}/{} task items "
                "({}/{} nominal trajectories), but task_alignment_unit={} "
                "is not satisfied; continuing collection.",
                len(rollout_samples), required_tasks,
                total_trajectories, required_trajectories,
                task_alignment_unit,
            )
            continue

        rollout_sample = ray.cloudpickle.loads(sample_bytes)
        rollout_samples.append(rollout_sample)

        sample_traj_count = (
            len(rollout_sample.data)
            if rollout_sample.data is not None and rollout_sample.data.batch is not None
            else 0
        )
        total_trajectories += sample_traj_count

        if len(rollout_samples) % 10 == 0:
            logger.info(
                "Collected {}/{} task items ({} actual / {} nominal "
                "trajectories). mq_len: {}",
                len(rollout_samples), required_tasks,
                total_trajectories, required_trajectories, queue_len,
            )

    consumer_end = time.time()
    return QueueCollection(
        samples=rollout_samples,
        total_trajectories=total_trajectories,
        queue_len=queue_len,
        total_wait_time=consumer_end - consumer_start,
    )
