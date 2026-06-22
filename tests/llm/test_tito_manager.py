"""Unit tests for the TITO token-trajectory bookkeeping (``manager.py``).

These pin the two pieces that directly shape the training signal:

* the **loss mask** -- only model-generated/trainable tokens count; the prompt
  and tool-result tokens are excluded; and
* the per-token **rollout log-prob alignment** -- kept 1:1 with ``token_ids``
  (0.0 for tokens the model did not generate), with a length-mismatch safety
  fallback so a bad rollout payload can never silently misalign.

A bug in either silently corrupts the GRPO/TIS target without ever raising,
so these are worth locking down.
"""

from mcpuniverse.llm.tito import TokenTrajectory, TokenTrajectoryManager


class _FakeTokenizer:
    """Deterministic: one token id per whitespace-delimited word."""

    def encode(self, text, add_special_tokens=False):  # pylint: disable=unused-argument
        return [1000 + i for i in range(len(text.split()))]


def _mgr() -> TokenTrajectoryManager:
    return TokenTrajectoryManager(tokenizer=_FakeTokenizer())


def test_set_initial_prompt_is_nontrainable_with_zero_logprobs():
    mgr = _mgr()
    mgr.set_initial_prompt("a b c")  # 3 words -> 3 tokens

    assert mgr.total_length == 3
    assert mgr.prompt_length == 3
    assert mgr.response_length == 0

    traj = mgr.get_trajectory()
    assert traj.prompt_length == 3
    assert traj.logprobs == [0.0, 0.0, 0.0]          # prompt not generated
    assert traj.get_loss_mask() == []                # no response yet
    assert [s.segment_type for s in traj.segments] == ["prompt"]
    assert traj.segments[0].trainable is False


def test_append_response_aligns_logprobs_and_loss_mask():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")                      # 2 prompt tokens
    mgr.append_response_tokens(
        [200, 201, 202], trainable=True, logprobs=[-1.0, -2.0, -3.0],
    )

    assert mgr.total_length == 5
    assert mgr.response_length == 3

    traj = mgr.get_trajectory()
    # logprobs aligned 1:1 with token_ids (prompt zeros + real response).
    assert traj.logprobs == [0.0, 0.0, -1.0, -2.0, -3.0]
    assert traj.get_response_logprobs() == [-1.0, -2.0, -3.0]
    assert traj.get_loss_mask() == [True, True, True]


def test_tool_result_is_nontrainable_and_zero_logprob():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")                          # prompt: 2
    mgr.append_response_tokens([200, 201], logprobs=[-1.0, -2.0])  # resp: 2 (train)
    mgr.append_tool_result("x y z")                        # tool: 3 (not train)

    traj = mgr.get_trajectory()
    # response portion = resp(2) + tool(3)
    assert traj.get_loss_mask() == [True, True, False, False, False]
    assert traj.get_response_logprobs() == [-1.0, -2.0, 0.0, 0.0, 0.0]


def test_multi_turn_loss_mask_marks_only_trainable_response_segments():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")                          # prompt[0,2)
    mgr.append_response_tokens([200, 201], logprobs=[-1.0, -2.0])  # resp[2,4)
    mgr.append_tool_result("x y z")                        # tool[4,7)
    mgr.append_response_tokens([300], logprobs=[-9.0])     # resp[7,8)

    traj = mgr.get_trajectory()
    assert traj.get_loss_mask() == [True, True, False, False, False, True]
    assert traj.get_response_logprobs() == [-1.0, -2.0, 0.0, 0.0, 0.0, -9.0]


def test_logprobs_length_mismatch_falls_back_to_zeros():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")
    # 3 tokens but only 1 logprob -> must NOT misalign; fall back to zeros.
    mgr.append_response_tokens([200, 201, 202], logprobs=[-1.0])
    assert mgr.get_trajectory().get_response_logprobs() == [0.0, 0.0, 0.0]


def test_append_response_without_logprobs_fills_zeros_but_stays_trainable():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")
    mgr.append_response_tokens([200, 201])                 # no logprobs supplied
    traj = mgr.get_trajectory()
    assert traj.get_response_logprobs() == [0.0, 0.0]
    assert traj.get_loss_mask() == [True, True]


def test_trajectory_response_logprobs_empty_list_defaults_to_zeros():
    # Directly construct: an empty logprobs list must yield zeros sized to the
    # response (the ``if not self.logprobs`` branch in TokenTrajectory).
    traj = TokenTrajectory(token_ids=[1, 2, 3, 4], prompt_length=2, logprobs=[])
    assert traj.get_response_logprobs() == [0.0, 0.0]
    assert traj.get_prompt_ids() == [1, 2]
    assert traj.get_response_ids() == [3, 4]


def test_routed_experts_roundtrip():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")
    sentinel = object()
    mgr.set_routed_experts(sentinel)
    traj = mgr.get_trajectory()
    assert traj.routed_experts is sentinel
    assert traj.get_routed_experts() is sentinel


def test_reset_clears_all_state():
    mgr = _mgr()
    mgr.set_initial_prompt("a b")
    mgr.append_response_tokens([200], logprobs=[-1.0])
    mgr.set_routed_experts(object())
    mgr.reset()

    assert mgr.total_length == 0
    assert mgr.prompt_length == 0
    assert mgr.response_length == 0
    assert mgr.get_token_ids() == []
    traj = mgr.get_trajectory()
    assert traj.logprobs == []
    assert traj.routed_experts is None


def test_get_token_ids_returns_copy():
    mgr = _mgr()
    mgr.set_initial_prompt("a b c")
    ids = mgr.get_token_ids()
    ids.append(999)                                   # mutate the returned list
    assert mgr.get_token_ids() == [1000, 1001, 1002]  # internal state unchanged
