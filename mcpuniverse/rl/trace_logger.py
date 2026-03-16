"""
Trajectory Trace Logger for MCP-Universe RL training.

Logs trajectory trace data to JSONL files as each trajectory completes.

One training run = one timestamped folder. Files auto-rotate every 10k traces.

    trace_log_dir/
      traces_20260302_143025/
        traces_000000.jsonl   (lines 0–9999)
        traces_000001.jsonl   (lines 10000–19999)
        ...

Each JSONL line contains:
- Identity: instance_id, trajectory_id, trace_id
- Text: full_trace_text, prompt_text, output_text, response, output_segments
- Metrics: reward, num_steps, num_tool_calls, running_time
- Meta: finish_reason, error, rollout_mode

Token IDs and trace_records are intentionally excluded.

Usage:
    trace_logger = TrajectoryTraceLogger("/path/to/trace_logs")
    # Pass to Trajectory via create_trajectory(..., trace_logger=trace_logger)
    # Logging happens automatically after evaluate_trajectory()
"""
# pylint: disable=broad-exception-caught

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger


TRACES_PER_FILE = 10_000


class TrajectoryTraceLogger:
    """JSONL-based trajectory trace logger.

    Creates a timestamped subfolder under ``trace_log_dir`` for this
    training run.  Inside, JSONL files are auto-rotated every
    ``TRACES_PER_FILE`` (10 000) entries.

    Thread-safe: concurrent ``log()`` calls from parallel trajectories
    are serialised via a lock.

    Args:
        trace_log_dir: Base directory for trace logs.
    """

    def __init__(self, trace_log_dir: str):
        run_name = datetime.now().strftime("traces_%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(trace_log_dir, run_name)
        os.makedirs(self.run_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._total_logged = 0
        self._file_index = 0
        self._lines_in_current_file = 0
        self._current_file = None

        self._open_file()
        logger.info(f"[TraceLogger] Initialized, run dir: {self.run_dir}")

    def _open_file(self) -> None:
        """Open the next JSONL file."""
        if self._current_file is not None:
            self._current_file.close()
        filepath = os.path.join(
            self.run_dir, f"traces_{self._file_index:06d}.jsonl"
        )
        self._current_file = open(filepath, "a", encoding="utf-8")  # pylint: disable=consider-using-with
        self._lines_in_current_file = 0

    def _maybe_rotate(self) -> None:
        """Rotate to a new file if the current one has reached the limit."""
        if self._lines_in_current_file >= TRACES_PER_FILE:
            self._file_index += 1
            self._open_file()

    def log(self, result: "TrajectoryResult", extra_meta: Optional[Dict[str, Any]] = None) -> None:
        """Log a single TrajectoryResult to the current JSONL file.

        Args:
            result: Completed TrajectoryResult (after evaluation).
            extra_meta: Optional extra metadata (e.g., param_version).
        """
        record = {
            "timestamp": time.time(),
            # Identity
            "instance_id": result.instance_id,
            "trajectory_id": result.trajectory_id,
            "trace_id": result.trace_id,
            # Metrics
            "reward": result.reward,
            "finish_reason": result.finish_reason,
            "error": result.error,
            "num_steps": result.num_steps,
            "num_tool_calls": result.num_tool_calls,
            "running_time": result.running_time,
            "rollout_mode": result.rollout_mode,
            # Text data
            "full_trace_text": result.trace.full_text,
            "prompt_text": result.trace.prompt_text,
            "output_text": result.trace.output_text,
            "response": result.response,
            "output_segments": result.trace.output_segments,
        }

        if extra_meta:
            record["meta"] = extra_meta

        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"

        with self._lock:
            try:
                self._maybe_rotate()
                self._current_file.write(line)
                self._current_file.flush()
                self._lines_in_current_file += 1
                self._total_logged += 1
            except Exception as e:
                logger.error(f"[TraceLogger] Failed to write trace: {e}")

    def close(self) -> None:
        """Close the current file."""
        with self._lock:
            if self._current_file is not None:
                self._current_file.close()
                self._current_file = None
        logger.info(f"[TraceLogger] Closed. Total logged: {self._total_logged}")

    def __enter__(self) -> "TrajectoryTraceLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def total_logged(self) -> int:
        """Total number of trajectories logged."""
        return self._total_logged
