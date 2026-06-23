"""Tests for trace_logger.py — TrajectoryTraceLogger."""

import json
import os
from unittest.mock import MagicMock

import pytest
from mcpuniverse.rl.core.trace_logger import TrajectoryTraceLogger, TRACES_PER_FILE


@pytest.fixture
def logger_dir(tmp_path):
    return str(tmp_path / "traces")


class TestTrajectoryTraceLogger:
    def test_creates_run_dir(self, logger_dir):
        tl = TrajectoryTraceLogger(logger_dir)
        assert os.path.isdir(tl.run_dir)
        tl.close()

    def test_log_writes_jsonl(self, logger_dir):
        tl = TrajectoryTraceLogger(logger_dir)
        result = MagicMock()
        result.instance_id = "inst_001"
        result.trajectory_id = 0
        result.trace_id = "t1"
        result.reward = 1.0
        result.finish_reason = "stop"
        result.error = None
        result.num_steps = 3
        result.num_tool_calls = 2
        result.running_time = 1.5
        result.rollout_mode = "text"
        result.verifier_pass_rate = 0.5
        result.verifier_passed = 1
        result.verifier_total = 2
        result.response = "hello"
        result.trace = MagicMock()
        result.trace.full_text = "full"
        result.trace.prompt_text = "prompt"
        result.trace.output_text = "output"
        result.trace.output_segments = []

        tl.log(result)
        assert tl.total_logged == 1
        tl.close()

        # Read back
        files = os.listdir(tl.run_dir)
        assert len(files) == 1
        with open(os.path.join(tl.run_dir, files[0])) as f:
            record = json.loads(f.readline())
        assert record["instance_id"] == "inst_001"
        assert record["reward"] == 1.0
        assert record["verifier_pass_rate"] == 0.5
        assert record["verifier_passed"] == 1
        assert record["verifier_total"] == 2

    def test_close_idempotent(self, logger_dir):
        tl = TrajectoryTraceLogger(logger_dir)
        tl.close()
        tl.close()  # should not raise

    def test_context_manager(self, logger_dir):
        with TrajectoryTraceLogger(logger_dir) as tl:
            assert tl._current_file is not None
        assert tl._current_file is None

    def test_del_closes(self, logger_dir):
        tl = TrajectoryTraceLogger(logger_dir)
        f = tl._current_file
        del tl
        assert f.closed
