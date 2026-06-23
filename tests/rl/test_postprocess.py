"""Tests for framework-neutral rollout postprocessing helpers."""

from types import SimpleNamespace

from mcpuniverse.rl.core.postprocess import (
    collect_tokenized_rollout_results,
    pop_private_rollout_metrics,
    trajectory_result_to_rollout_record,
    tokenize_trajectory_result,
)


class _FakeTokenizableTrajectory:
    """In-memory test double that implements ``TokenizableTrajectory``."""

    def __init__(
        self,
        *,
        result=None,
        tito_tokens=None,
        trace_text="",
        instruction="",
        response_text="",
    ):
        self.result = result
        self._tito_tokens = tito_tokens
        self._trace_text = trace_text
        self._instruction = instruction
        self._response_text = response_text

    def get_tito_tokens(self):
        return self._tito_tokens

    def get_trace_text(self):
        return self._trace_text

    def get_instruction(self):
        return self._instruction

    def get_response_text(self):
        return self._response_text


def test_tokenize_trajectory_result_uses_live_tito_tokens():
    traj = _FakeTokenizableTrajectory(
        result=SimpleNamespace(),
        tito_tokens=([11, 12], [101, 102], [1, 0]),
    )

    prompt_ids, response_ids, response_mask = tokenize_trajectory_result(
        traj,
        tokenizer=None,
        formatter=None,
        rollout_mode="token",
    )

    assert prompt_ids == [11, 12]
    assert response_ids == [101, 102]
    assert response_mask == [1, 0]


def test_tokenize_trajectory_result_falls_back_to_text_when_no_tito():
    class _Formatter:
        def format_trace(self, trace_text, instruction):
            return {"trace": trace_text, "instruction": instruction}

        def tokenize_with_mask(self, formatter_output, tokenizer):
            assert tokenizer is None
            return [1, 2], [3, 4, 5], [True, False, True]

    traj = _FakeTokenizableTrajectory(
        result=SimpleNamespace(),
        tito_tokens=None,
        trace_text="<sys>...<user>do X</user><assistant>ok</assistant>",
        instruction="do X",
    )

    prompt_ids, response_ids, response_mask = tokenize_trajectory_result(
        traj,
        tokenizer=None,
        formatter=_Formatter(),
        rollout_mode="text",
    )

    assert prompt_ids == [1, 2]
    assert response_ids == [3, 4, 5]
    assert response_mask == [1, 0, 1]


def test_tokenize_trajectory_result_bare_fallback_when_no_trace():
    class _Tokenizer:
        def encode(self, text, add_special_tokens=False):
            return [ord(c) for c in text]

    traj = _FakeTokenizableTrajectory(
        result=SimpleNamespace(),
        tito_tokens=None,
        trace_text="",
        instruction="ab",
        response_text="cd",
    )

    prompt_ids, response_ids, response_mask = tokenize_trajectory_result(
        traj,
        tokenizer=_Tokenizer(),
        formatter=None,
        rollout_mode="text",
    )

    assert prompt_ids == [97, 98]
    assert response_ids == [99, 100]
    assert response_mask == [1, 1]


def test_tokenize_trajectory_result_raises_when_no_result():
    traj = _FakeTokenizableTrajectory(result=None)

    try:
        tokenize_trajectory_result(traj, tokenizer=None, formatter=None)
    except ValueError as exc:
        assert "without a result" in str(exc)
    else:
        raise AssertionError("Expected ValueError when result is None")


def test_collect_tokenized_rollout_results_skips_missing_and_groups():
    completed = _FakeTokenizableTrajectory(
        result=SimpleNamespace(
            reward=0.5,
            to_dict=lambda: {"response": "ok"},
        ),
    )
    missing = _FakeTokenizableTrajectory(result=None)
    trajectories = {"task-a": {0: completed, 1: missing}}

    output = collect_tokenized_rollout_results(
        trajectories,
        [{"instruction": "x"}],
        num_trajectories=2,
        tokenize_trajectory_fn=lambda *_args: ([1], [2, 3], [1, 0]),
    )

    assert output.prompt_ids == [[1]]
    assert output.response_ids == [[2, 3]]
    assert output.response_mask == [[1, 0]]
    assert output.rewards == [0.5]
    assert output.group_ids == ["task-a"]
    assert output.trajectories == [
        {"response": "ok", "instance_id": "task-a", "trajectory_id": 0}
    ]
    assert output.metrics["num_trajectories"] == 2
    assert output.metrics["num_collected"] == 1
    assert output.metrics["num_missing"] == 1
    assert output.metrics["missing_results"] == ["task-a-1"]


def test_pop_private_rollout_metrics_hides_private_metrics():
    metrics = {
        "num_collected": 1,
        "missing_results": ["task-b-0"],
    }

    private_metrics = pop_private_rollout_metrics(metrics)

    assert metrics == {"num_collected": 1}
    assert private_metrics == {"missing_results": ["task-b-0"]}


def test_trajectory_result_to_rollout_record_uses_result_boundary():
    result = SimpleNamespace(
        to_rollout_record=lambda *, instance_id, trajectory_id: {
            "response": "ok",
            "instance_id": instance_id,
            "trajectory_id": trajectory_id,
        }
    )

    record = trajectory_result_to_rollout_record(
        result,
        instance_id="task-a",
        trajectory_id=0,
    )

    assert record == {"response": "ok", "instance_id": "task-a", "trajectory_id": 0}
