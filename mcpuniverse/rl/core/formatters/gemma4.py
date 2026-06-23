"""
Gemma 4 formatter.

Gemma 4 native chat template (from chat_template.jinja):

    <bos>
    <|turn>system
    <system_content>
    <|tool>declaration:name{...}<tool|>  (one per tool)
    <turn|>
    <|turn>user
    <user_content>
    <turn|>
    <|turn>model
    <|channel>thought
    <reasoning...>
    <channel|>
    <|tool_call>call:name{k:v,...}<tool_call|>
    <|tool_response>response:name{value:"..."}<tool_response|>
    <final_content...>
    <turn|>
    <|turn>model
    <|channel>thought
    <channel|>                          <- add_generation_prompt stops here

Special tokens (single-id per tokenizer probe):
    <|turn>      -> 105
    <turn|>      -> 106
    <|channel>   -> 100
    <channel|>   -> 101
    <|tool>      -> 46
    <tool|>      -> 47
    <|tool_call> -> 48
    <tool_call|> -> 49
    <|tool_response> -> 50
    <tool_response|> -> 51

Trainability convention (same as GptOssFormatter / Qwen3Formatter):
    - system / tool-declarations / user prompt      -> not trained
    - assistant <|channel>thought ... <channel|>    -> trained (reasoning)
    - assistant <|tool_call>...<tool_call|>         -> trained (action)
    - <|tool_response>...<tool_response|>           -> NOT trained (env output)
    - assistant final content                        -> trained (answer)
"""

import re
from typing import Any, Dict, List

from .base import BaseFormatter, FormatterOutput


# Special token literals (string form; kept single-id by Gemma4 tokenizer)
TURN_OPEN = "<|turn>"
TURN_CLOSE = "<turn|>"
CHANNEL_OPEN = "<|channel>"
CHANNEL_CLOSE = "<channel|>"
TOOL_DECL_OPEN = "<|tool>"
TOOL_DECL_CLOSE = "<tool|>"
TOOL_CALL_OPEN = "<|tool_call>"
TOOL_CALL_CLOSE = "<tool_call|>"
TOOL_RESPONSE_OPEN = "<|tool_response>"
TOOL_RESPONSE_CLOSE = "<tool_response|>"


class Gemma4Formatter(BaseFormatter):
    """Formatter for Gemma 4 IT models using the native Google chat template."""

    # A full turn: <|turn>role<content><turn|>
    TURN_PATTERN = re.compile(
        re.escape(TURN_OPEN) + r"(\w+)\n?(.*?)(?=" + re.escape(TURN_CLOSE)
        + r"|\Z)",
        re.DOTALL,
    )
    # Inside a model turn, separate sub-segments by marker boundaries.
    CHANNEL_PATTERN = re.compile(
        re.escape(CHANNEL_OPEN) + r"(\w+)\n?(.*?)" + re.escape(CHANNEL_CLOSE),
        re.DOTALL,
    )
    TOOL_CALL_PATTERN = re.compile(
        re.escape(TOOL_CALL_OPEN) + r"(.*?)" + re.escape(TOOL_CALL_CLOSE),
        re.DOTALL,
    )
    TOOL_RESPONSE_PATTERN = re.compile(
        re.escape(TOOL_RESPONSE_OPEN) + r"(.*?)" + re.escape(TOOL_RESPONSE_CLOSE),
        re.DOTALL,
    )

    def parse_raw_text(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parse Gemma4 raw trace text into per-turn messages.

        Each resulting message carries:
            role     : system | user | model
            content  : inner-turn text stripped of surrounding markers
            raw      : the full string including markers (for re-tokenization)
            sub_segments: ordered list of (kind, content, raw) sub-pieces
                         kind in {"thought", "tool_call", "tool_response", "content"}
        """
        messages: List[Dict[str, Any]] = []
        for match in self.TURN_PATTERN.finditer(raw_text):
            role = match.group(1).strip().lower()
            body = match.group(2)
            # Reconstruct the raw turn incl. <turn|> if present in source
            raw_end_pos = match.end()
            raw_with_close = raw_text[match.start():]
            if raw_with_close.startswith(TURN_OPEN):
                # Include the <turn|> closing marker if present right after body
                close_idx = raw_text.find(TURN_CLOSE, match.start())
                if close_idx != -1 and close_idx < raw_end_pos + len(TURN_CLOSE):
                    raw = raw_text[match.start():close_idx + len(TURN_CLOSE)]
                else:
                    raw = raw_text[match.start():raw_end_pos]
            else:
                raw = raw_text[match.start():raw_end_pos]

            sub_segments = self._parse_model_turn(body) if role == "model" else []

            messages.append({
                "role": role,
                "content": body,
                "raw": raw,
                "sub_segments": sub_segments,
            })
        return messages

    def _parse_model_turn(self, body: str) -> List[Dict[str, str]]:
        """Slice a model turn into (thought / tool_call / tool_response / content)."""
        segments: List[Dict[str, str]] = []
        cursor = 0
        # Walk markers in document order.
        # Build a sorted list of all marker matches.
        anchors = []
        for m in self.CHANNEL_PATTERN.finditer(body):
            anchors.append((m.start(), m.end(), "thought", m.group(2), m.group(0)))
        for m in self.TOOL_CALL_PATTERN.finditer(body):
            anchors.append((m.start(), m.end(), "tool_call", m.group(1), m.group(0)))
        for m in self.TOOL_RESPONSE_PATTERN.finditer(body):
            anchors.append((m.start(), m.end(), "tool_response", m.group(1), m.group(0)))
        anchors.sort(key=lambda x: x[0])

        for start, end, kind, content, raw in anchors:
            if start > cursor:
                gap = body[cursor:start]
                if gap.strip():
                    segments.append({"kind": "content", "content": gap, "raw": gap})
            segments.append({"kind": kind, "content": content, "raw": raw})
            cursor = end
        # Trailing text after the last marker (usually the final answer)
        if cursor < len(body):
            tail = body[cursor:]
            if tail.strip():
                segments.append({"kind": "content", "content": tail, "raw": tail})
        return segments

    def split_prompt_output(
        self,
        messages: List[Dict[str, Any]],
        initial_instruction: str = "",
    ) -> FormatterOutput:
        """Split into prompt (up to and including the first model-turn header)
        and output (model content + subsequent turns)."""
        prompt_parts: List[str] = []
        output_parts: List[str] = []
        output_segments: List[Dict[str, Any]] = []

        found_first_user = False
        found_first_model = False
        in_prompt = True

        for msg in messages:
            role = msg["role"]
            raw = msg["raw"]

            if in_prompt:
                if role in ("system", "user"):
                    prompt_parts.append(raw)
                    if role == "user":
                        found_first_user = True
                elif role == "model" and found_first_user and not found_first_model:
                    # First model turn: the `<|turn>model\n<|channel>thought\n<channel|>`
                    # header stays in the prompt; everything inside the turn is output.
                    header = TURN_OPEN + "model\n" + CHANNEL_OPEN + "thought\n" + CHANNEL_CLOSE
                    prompt_parts.append(header)
                    # Output is everything in the turn *after* the header, plus <turn|>.
                    # Strip the leading thought-channel marker we just accounted for.
                    body = msg["content"]
                    # Best-effort: remove the first <|channel>thought\n...<channel|> if it is
                    # present; the remainder (including any tool_call / answer) is trainable.
                    m = self.CHANNEL_PATTERN.search(body)
                    if m and m.start() == 0:
                        remainder_body = body[m.end():]
                        thought_raw = m.group(0)
                        # Build output from thought_raw + remainder + <turn|>
                        output_raw = thought_raw + remainder_body + TURN_CLOSE
                    else:
                        output_raw = body + TURN_CLOSE

                    output_parts.append(output_raw)

                    # Segment-level mask: iterate sub_segments, mark env-output as not-trained.
                    self._emit_model_segments(msg, output_segments)
                    found_first_model = True
                    in_prompt = False
                else:
                    # Unexpected leading turn (eg tool role) - just add to prompt.
                    prompt_parts.append(raw)
            else:
                output_parts.append(raw)
                self._emit_model_segments(msg, output_segments)

        # Fallback: no user message found but we have an instruction.
        if not found_first_user and initial_instruction:
            synth_user = TURN_OPEN + "user\n" + initial_instruction + TURN_CLOSE + "\n"
            prompt_parts = [synth_user]
            output_parts.clear()
            output_segments.clear()
            for msg in messages:
                output_parts.append(msg["raw"])
                self._emit_model_segments(msg, output_segments)

        return FormatterOutput(
            prompt_text="".join(prompt_parts),
            output_text="".join(output_parts),
            output_segments=output_segments,
            messages=messages,
        )

    def _emit_model_segments(
        self,
        msg: Dict[str, Any],
        output_segments: List[Dict[str, Any]],
    ) -> None:
        """Append per-sub-segment dicts with correct trainability flags."""
        role = msg["role"]
        if role != "model":
            # Non-model turns (user / system / tool) are not trainable output.
            output_segments.append(self._make_segment(
                role=role,
                channel="",
                content=msg["content"],
                raw=msg["raw"],
                trainable=False,
            ))
            return

        for sub in msg.get("sub_segments", []):
            kind = sub["kind"]
            # Tool responses come from the environment, not the policy -> not trained.
            trainable = kind != "tool_response"
            output_segments.append(self._make_segment(
                role="model",
                channel=kind,
                content=sub["content"],
                raw=sub["raw"],
                trainable=trainable,
                sub_kind=kind,
            ))
