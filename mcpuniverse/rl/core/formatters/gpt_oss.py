"""
GPT-OSS (Harmony format) formatter.

Parses Harmony-style messages with channels:
- <|start|>system<|message|>...
- <|start|>developer<|message|>...
- <|start|>user<|message|>...
- <|start|>assistant<|channel|>analysis<|message|>CONTENT...
- <|start|>assistant<|channel|>commentary to=functions.xxx<|message|>...
- <|start|>functions.xxx to=assistant<|channel|>commentary<|message|>...
- <|start|>assistant<|channel|>final<|message|>...

Prompt (NOT trained):
- system, developer, user
- Tag header of FIRST assistant analysis only
  (i.e. just <|start|>assistant<|channel|>analysis<|message|>)

Output (partially trained, using 'raw' field which includes tags):
- FIRST assistant analysis content (tag is in prompt) - TRAINABLE
- assistant commentary (tag + content) - TRAINABLE
- functions.xxx tool result (tag + content) - NOT trainable
- subsequent assistant analysis (tag + content) - TRAINABLE
- assistant final (tag + content) - TRAINABLE

All assistant tags (channel names, etc.) are trained; only functions.xxx
segments are fully masked.
"""

import re
from typing import Any, Dict, List

from .base import BaseFormatter, FormatterOutput


class GptOssFormatter(BaseFormatter):
    """Formatter for GPT-OSS models using Harmony format."""

    # <|start|>role<|channel|>channel_info<|message|>content<|end|>
    # or <|start|>role<|message|>content<|end|>
    MESSAGE_PATTERN = re.compile(
        r'<\|start\|>([^<]+?)(?:<\|channel\|>([^<]*?))?<\|message\|>(.*?)(?:<\|end\|>|<\|start\|>|$)',
        re.DOTALL,
    )

    START_TOKEN = "<|start|>"
    END_TOKEN = "<|end|>"
    CHANNEL_TOKEN = "<|channel|>"
    MESSAGE_TOKEN = "<|message|>"

    def parse_raw_text(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parse Harmony format raw text into messages."""
        messages = []

        for match in self.MESSAGE_PATTERN.finditer(raw_text):
            role_part = match.group(1).strip()
            channel_part = match.group(2)
            content = match.group(3).strip()

            role = role_part.split()[0] if role_part else ""
            to_target = None
            if " to=" in role_part:
                to_match = re.search(r'to=(\S+)', role_part)
                if to_match:
                    to_target = to_match.group(1)

            channel = ""
            if channel_part:
                channel_clean = channel_part.split("<|constrain|>")[0].strip()
                if " to=" in channel_clean:
                    channel = channel_clean.split(" to=")[0].strip()
                else:
                    channel = channel_clean

            messages.append({
                "role": role,
                "channel": channel,
                "content": content,
                "to": to_target,
                "raw": match.group(0),
            })

        return messages

    def split_prompt_output(
        self,
        messages: List[Dict[str, Any]],
        initial_instruction: str = "",
    ) -> FormatterOutput:
        """
        Split messages into prompt and output.

        Prompt (NOT trained):
        - system, developer, first user
        - Tag header of FIRST assistant analysis (without content)

        Output (partially trained):
        - First assistant analysis content - TRAINABLE
        - assistant commentary (tool calls) - TRAINABLE
        - functions.xxx (tool results) - NOT trainable
        - subsequent assistant analysis - TRAINABLE
        - assistant final - TRAINABLE
        """
        prompt_parts = []
        output_parts = []
        output_segments = []

        found_first_user = False
        found_first_analysis = False
        in_prompt = True

        for msg in messages:
            role = msg.get("role", "").lower()
            channel = msg.get("channel", "").lower()
            content = msg.get("content", "")
            raw = msg.get("raw", "")

            if in_prompt:
                if role in ("system", "developer", "user"):
                    prompt_parts.append(raw)
                    if role == "user":
                        found_first_user = True
                elif role == "assistant" and channel == "analysis" and found_first_user and not found_first_analysis:
                    # First analysis: tag header -> prompt, content -> output
                    prompt_parts.append("<|start|>assistant<|channel|>analysis<|message|>")
                    output_parts.append(content)
                    output_segments.append(self._make_segment(
                        role, channel, content, raw=content, trainable=True,
                    ))
                    found_first_analysis = True
                    in_prompt = False
                elif role == "assistant" and found_first_user:
                    # Non-analysis assistant after user (e.g. direct final)
                    in_prompt = False
                    output_parts.append(raw)
                    output_segments.append(self._make_segment(
                        role, channel, content, raw, self._is_trainable(role),
                    ))
                else:
                    prompt_parts.append(raw)
            else:
                output_parts.append(raw)
                output_segments.append(self._make_segment(
                    role, channel, content, raw, self._is_trainable(role),
                ))

        # Fallback: no user message found
        if not found_first_user and initial_instruction:
            prompt_parts = [f"<|start|>user<|message|>{initial_instruction}<|end|>"]
            output_parts.clear()
            output_segments.clear()
            for msg in messages:
                output_parts.append(msg.get("raw", ""))
                output_segments.append(self._make_segment(
                    msg.get("role", ""),
                    msg.get("channel", ""),
                    msg.get("content", ""),
                    msg.get("raw", ""),
                    self._is_trainable(msg.get("role", "")),
                ))

        return FormatterOutput(
            prompt_text="".join(prompt_parts),
            output_text="".join(output_parts),
            output_segments=output_segments,
            messages=messages,
        )

    @staticmethod
    def _is_trainable(role: str) -> bool:
        """Assistant segments are trainable; functions.xxx and others are not."""
        return role.lower() == "assistant"
