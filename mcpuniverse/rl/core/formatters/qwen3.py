"""
Qwen3 (ChatML format) formatter.

Parses ChatML-style messages:
- <|im_start|>system\\ncontent<|im_end|>
- <|im_start|>user\\ncontent<|im_end|>
- <|im_start|>assistant\\ncontent<|im_end|>

For ReAct training, assistant output is JSON:
    {"thought": "...", "action": {"server": "...", "tool": "...", "arguments": {...}}}
    {"thought": "...", "answer": "final answer"}

Prompt (NOT trained):
- system message
- first user message
- <|im_start|>assistant\\n (tag header only)

Output (partially trained):
- Assistant responses (JSON) - TRAINABLE
- Tool results (user messages starting with "Tool execution result:") - NOT trainable
"""

import json
import re
from typing import Any, Dict, List

from .base import BaseFormatter, FormatterOutput


class Qwen3Formatter(BaseFormatter):
    """Formatter for Qwen3 models using ChatML format."""

    # <|im_start|>role\ncontent<|im_end|>
    MESSAGE_PATTERN = re.compile(
        r'<\|im_start\|>(\w+)\n(.*?)(?:<\|im_end\|>|$)',
        re.DOTALL,
    )

    START_TOKEN = "<|im_start|>"
    END_TOKEN = "<|im_end|>"

    def parse_raw_text(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parse ChatML format raw text into messages."""
        messages = []

        for match in self.MESSAGE_PATTERN.finditer(raw_text):
            role = match.group(1).strip()
            content = match.group(2).strip()

            channel = ""
            is_tool_result = False

            if role == "user" and content.startswith("Tool execution result:"):
                is_tool_result = True
                channel = "tool_result"
            elif role == "assistant":
                try:
                    parsed = json.loads(content)
                    if "action" in parsed:
                        channel = "action"
                    elif "answer" in parsed:
                        channel = "answer"
                    else:
                        channel = "thought"
                except json.JSONDecodeError:
                    channel = "raw"

            messages.append({
                "role": role,
                "channel": channel,
                "content": content,
                "is_tool_result": is_tool_result,
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
        - system, first user message
        - <|im_start|>assistant\\n (tag header only)

        Output (partially trained):
        - First assistant response content - TRAINABLE
        - Subsequent assistant responses (full) - TRAINABLE
        - Tool results (user messages with "Tool execution result:") - NOT trainable
        """
        prompt_parts = []
        output_parts = []
        output_segments = []

        found_first_user = False
        found_first_assistant = False
        in_prompt = True

        for msg in messages:
            role = msg.get("role", "").lower()
            content = msg.get("content", "")
            raw = msg.get("raw", "")
            is_tool_result = msg.get("is_tool_result", False)
            channel = msg.get("channel", "")

            if in_prompt:
                if role == "system":
                    prompt_parts.append(raw)
                elif role == "user" and not is_tool_result:
                    prompt_parts.append(raw)
                    found_first_user = True
                elif role == "assistant" and found_first_user and not found_first_assistant:
                    # First assistant: tag header -> prompt, content -> output
                    prompt_parts.append(f"{self.START_TOKEN}assistant\n")
                    output_content = f"{content}{self.END_TOKEN}\n"
                    output_parts.append(output_content)
                    output_segments.append(self._make_segment(
                        role, channel, content, raw=output_content, trainable=True,
                    ))
                    found_first_assistant = True
                    in_prompt = False
                else:
                    prompt_parts.append(raw)
            else:
                output_parts.append(raw)
                trainable = role == "assistant" and not is_tool_result
                output_segments.append(self._make_segment(
                    role, channel, content, raw, trainable,
                    is_tool_result=is_tool_result,
                ))

        # Fallback: no user message found
        if not found_first_user and initial_instruction:
            prompt_parts = [f"{self.START_TOKEN}user\n{initial_instruction}{self.END_TOKEN}\n"]
            output_parts.clear()
            output_segments.clear()
            for msg in messages:
                is_tool = msg.get("is_tool_result", False)
                r = msg.get("role", "")
                trainable = r.lower() == "assistant" and not is_tool
                output_parts.append(msg.get("raw", ""))
                output_segments.append(self._make_segment(
                    r,
                    msg.get("channel", ""),
                    msg.get("content", ""),
                    msg.get("raw", ""),
                    trainable,
                    is_tool_result=is_tool,
                ))

        return FormatterOutput(
            prompt_text="".join(prompt_parts),
            output_text="".join(output_parts),
            output_segments=output_segments,
            messages=messages,
        )
