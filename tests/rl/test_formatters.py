"""Tests for RL model-specific trajectory formatters."""

from mcpuniverse.rl.core.formatters import get_formatter
from mcpuniverse.rl.core.formatters.base import FormatterOutput


class _CharTokenizer:
    def encode(self, text, add_special_tokens=False):  # pylint: disable=unused-argument
        return list(range(len(text)))


def test_formatter_output_trainable_mask_follows_segment_trainability():
    output = FormatterOutput(
        output_segments=[
            {"raw": "ab", "trainable": True},
            {"raw": "cde", "trainable": False},
            {"raw": "f", "trainable": True},
        ]
    )

    tokens, mask = output.get_trainable_mask(_CharTokenizer())

    assert len(tokens) == 6
    assert mask == [1, 1, 0, 0, 0, 1]


def test_gpt_oss_formatter_trains_assistant_segments_but_masks_tool_results():
    formatter = get_formatter("gpt_oss")
    raw = (
        "<|start|>system<|message|>sys<|end|>"
        "<|start|>user<|message|>question<|end|>"
        "<|start|>assistant<|channel|>analysis<|message|>think<|end|>"
        "<|start|>assistant<|channel|>commentary to=functions.search<|message|>{}<|end|>"
        "<|start|>functions.search to=assistant<|channel|>commentary<|message|>result<|end|>"
        "<|start|>assistant<|channel|>final<|message|>answer<|end|>"
    )

    output = formatter.format_trace(raw)

    assert "question" in output.prompt_text
    assert output.output_segments[0]["content"] == "think"
    assert [segment["trainable"] for segment in output.output_segments] == [
        True,
        True,
        False,
        True,
    ]


def test_qwen3_formatter_masks_tool_result_user_messages():
    formatter = get_formatter("qwen3")
    raw = (
        "<|im_start|>system\nsys<|im_end|>"
        "<|im_start|>user\nquestion<|im_end|>"
        "<|im_start|>assistant\n{\"thought\":\"t\",\"action\":{\"tool\":\"search\"}}<|im_end|>"
        "<|im_start|>user\nTool execution result: result<|im_end|>"
        "<|im_start|>assistant\n{\"answer\":\"answer\"}<|im_end|>"
    )

    output = formatter.format_trace(raw)

    assert "question" in output.prompt_text
    assert [segment["trainable"] for segment in output.output_segments] == [
        True,
        False,
        True,
    ]
    assert output.output_segments[1]["is_tool_result"] is True


def test_gemma4_formatter_masks_tool_response_subsegments():
    formatter = get_formatter("gemma4")
    raw = (
        "<|turn>system\nsys<turn|>"
        "<|turn>user\nquestion<turn|>"
        "<|turn>model\n"
        "<|channel>thought\nthink<channel|>"
        "<|tool_call>call:search{}<tool_call|>"
        "<|tool_response>response:search{value:\"result\"}<tool_response|>"
        "answer<turn|>"
    )

    output = formatter.format_trace(raw)

    assert "question" in output.prompt_text
    assert [(segment["channel"], segment["trainable"]) for segment in output.output_segments] == [
        ("thought", True),
        ("tool_call", True),
        ("tool_response", False),
        ("content", True),
    ]
