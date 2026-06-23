"""
Base formatter for model-specific prompt/response splitting.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class FormatterOutput:
    """
    Output from formatter's split operation.

    Contains:
    - prompt_text: System + initial user message (not trained)
    - output_text: Everything after (assistant, tool calls, tool results)
    - output_segments: List of segments with role and content for mask building
    """
    prompt_text: str = ""
    output_text: str = ""

    # Each segment: {"role": str, "content": str, "raw": str, "trainable": bool, ...}
    output_segments: List[Dict[str, Any]] = field(default_factory=list)

    # Raw messages for debugging
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def get_trainable_mask(self, tokenizer: Any) -> tuple:
        """
        Tokenize output segments and build a per-token loss mask.

        Uses 'raw' field (includes format tags) for tokenization so that
        tags are also trained for assistant messages.

        Returns:
            (output_token_ids, loss_mask) - both List[int].
        """
        output_tokens = []
        loss_mask = []

        for seg in self.output_segments:
            text = seg.get("raw", "") or seg.get("content", "")
            if not text:
                continue

            tokens = tokenizer.encode(text, add_special_tokens=False)
            output_tokens.extend(tokens)
            loss_mask.extend([int(seg.get("trainable", False))] * len(tokens))

        return output_tokens, loss_mask


class BaseFormatter(ABC):
    """
    Base class for model-specific formatters.

    Subclasses implement:
    - parse_raw_text(): Parse raw trace text into structured messages
    - split_prompt_output(): Split into prompt (not trained) and output (trained)
    """

    @abstractmethod
    def parse_raw_text(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parse raw trace text into structured messages."""

    @abstractmethod
    def split_prompt_output(
        self,
        messages: List[Dict[str, Any]],
        initial_instruction: str = "",
    ) -> FormatterOutput:
        """Split messages into prompt and output."""

    def format_trace(
        self,
        raw_text: str,
        initial_instruction: str = "",
    ) -> FormatterOutput:
        """Full pipeline: parse raw text then split into prompt/output."""
        messages = self.parse_raw_text(raw_text)
        return self.split_prompt_output(messages, initial_instruction)

    def tokenize_with_mask(
        self,
        formatter_output: FormatterOutput,
        tokenizer: Any,
    ) -> tuple:
        """
        Tokenize prompt and output, returning a per-token loss mask.

        Returns:
            (prompt_tokens, output_tokens, loss_mask)
        """
        prompt_tokens = []
        if formatter_output.prompt_text:
            prompt_tokens = tokenizer.encode(
                formatter_output.prompt_text,
                add_special_tokens=True,
            )

        output_tokens, loss_mask = formatter_output.get_trainable_mask(tokenizer)
        return prompt_tokens, output_tokens, loss_mask

    @staticmethod
    def _make_segment(
        role: str,
        channel: str,
        content: str,
        raw: str,
        trainable: bool,
        **extra,
    ) -> Dict[str, Any]:
        """Build a segment dict with consistent keys."""
        seg = {
            "role": role,
            "channel": channel,
            "content": content,
            "raw": raw,
            "trainable": trainable,
        }
        seg.update(extra)
        return seg
