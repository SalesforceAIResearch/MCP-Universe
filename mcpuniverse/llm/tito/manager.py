"""
Token Trajectory Manager for TITO (Token In Token Out) rollout.

Maintains the complete token sequence during an agent rollout without
retokenization.  Only tool results (external text) require tokenization;
LLM responses are appended as raw token IDs from vLLM.

Typical flow:
  1. set_initial_prompt(text)         — tokenize once
  2. append_response_tokens(ids)      — direct append (no tokenization)
  3. append_tool_result(text)         — tokenize external data
  4. repeat 2-3
  5. get_trajectory()                 — complete TokenTrajectory for training
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List
from loguru import logger


@dataclass
class TokenSegment:
    """A contiguous segment in the token trajectory."""
    segment_type: str       # "prompt", "response", or "tool_result"
    start_idx: int
    end_idx: int
    trainable: bool
    text: str = ""          # for debugging


@dataclass
class TokenTrajectory:
    """Complete token trajectory ready for training."""
    token_ids: List[int] = field(default_factory=list)
    segments: List[TokenSegment] = field(default_factory=list)
    prompt_length: int = 0
    # Per-token rollout log-probs, aligned 1:1 with ``token_ids`` (0.0 for
    # prompt / tool-result tokens the model did not generate). Used for
    # train-inference mismatch correction (TIS / bypass) in MoE RL.
    logprobs: List[float] = field(default_factory=list)
    # Latest full-sequence routed-experts tensor/list from the rollout engine,
    # expected to be aligned with token_ids: [seq_len, num_layers, topk].
    routed_experts: Any = None

    def get_prompt_ids(self) -> List[int]:
        """Return prompt token IDs."""
        return self.token_ids[:self.prompt_length]

    def get_response_ids(self) -> List[int]:
        """Return response token IDs."""
        return self.token_ids[self.prompt_length:]

    def get_response_logprobs(self) -> List[float]:
        """Per-token rollout log-probs for the response portion (0.0 where the
        model did not generate, i.e. tool-result tokens). Aligned with
        ``get_response_ids()`` / ``get_loss_mask()``."""
        if not self.logprobs:
            return [0.0] * (len(self.token_ids) - self.prompt_length)
        return self.logprobs[self.prompt_length:]

    def get_routed_experts(self) -> Any:
        """Return latest full-sequence routed experts for R3, if available."""
        return self.routed_experts

    @property
    def text(self) -> str:
        """Full trajectory text (concatenation of all segment texts)."""
        return "".join(s.text for s in self.segments)

    def get_loss_mask(self) -> List[bool]:
        """Per-token loss mask for the response portion (True = trainable)."""
        resp_len = len(self.token_ids) - self.prompt_length
        mask = [False] * resp_len
        for seg in self.segments:
            if seg.start_idx >= self.prompt_length and seg.trainable:
                lo = seg.start_idx - self.prompt_length
                hi = seg.end_idx - self.prompt_length
                for i in range(max(0, lo), min(hi, resp_len)):
                    mask[i] = True
        return mask

    # Alias used by the RL trajectory module
    get_trainable_mask = get_loss_mask

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "token_ids": self.token_ids,
            "segments": [
                {
                    "type": s.segment_type,
                    "start_idx": s.start_idx,
                    "end_idx": s.end_idx,
                    "trainable": s.trainable,
                    "text": s.text[:100] + "..." if len(s.text) > 100 else s.text,
                }
                for s in self.segments
            ],
            "prompt_length": self.prompt_length,
            "total_length": len(self.token_ids),
        }


class TokenTrajectoryManager:
    """
    Maintains a growing token sequence during TITO rollout.

    Three core operations:
    - set_initial_prompt(): tokenize the prompt once at the start
    - append_response_tokens(): append LLM output token IDs directly
    - append_tool_result(): tokenize external tool result text and append
    """

    def __init__(self, tokenizer: Any, skip_special_tokens: bool = False, **_kw):
        self._tokenizer = tokenizer
        self._skip_special_tokens = skip_special_tokens
        self._token_ids: List[int] = []
        self._logprobs: List[float] = []  # aligned 1:1 with _token_ids
        self._routed_experts: Any = None  # latest full-sequence routing table
        self._segments: List[TokenSegment] = []
        self._prompt_length: int = 0
        self._full_text: str = ""

    def reset(self):
        """Reset for a new rollout."""
        self._token_ids.clear()
        self._logprobs.clear()
        self._routed_experts = None
        self._segments.clear()
        self._prompt_length = 0
        self._full_text = ""

    # ------------------------------------------------------------------
    # Core append operations
    # ------------------------------------------------------------------

    def set_initial_prompt(self, prompt_text: str, add_special_tokens: bool = True):
        """Tokenize the initial prompt (called once per rollout)."""
        self.reset()
        tokens = self._tokenizer.encode(prompt_text, add_special_tokens=add_special_tokens)
        self._token_ids = tokens
        self._logprobs = [0.0] * len(tokens)  # prompt tokens not generated
        self._prompt_length = len(tokens)
        self._full_text = prompt_text
        self._segments.append(TokenSegment(
            segment_type="prompt", start_idx=0, end_idx=len(tokens),
            trainable=False, text=prompt_text,
        ))
        logger.debug("TITO Manager: prompt set, {} tokens", len(tokens))

    def append_response_tokens(
        self, output_tokens: List[int], trainable: bool = True, response_text: str = "",
        logprobs: Any = None,
    ):
        """Append LLM response token IDs directly (no tokenization).

        ``logprobs`` (optional) are the rollout engine's per-token log-probs for
        ``output_tokens`` (same length); stored for train-inference mismatch
        correction (TIS). Missing/mismatched -> filled with 0.0.
        """
        self._append_segment("response", output_tokens, trainable, response_text, logprobs)
        logger.debug(
            "TITO Manager: appended {} response tokens (trainable={})",
            len(output_tokens), trainable,
        )

    def append_tool_result(
        self, result_text: str, trainable: bool = False, add_special_tokens: bool = False,
    ):
        """Tokenize a tool result and append (the only tokenization in the loop)."""
        tokens = self._tokenizer.encode(result_text, add_special_tokens=add_special_tokens)
        self._append_segment("tool_result", tokens, trainable, result_text)
        logger.debug("TITO Manager: tokenized {} tool-result tokens", len(tokens))

    def _append_segment(
        self, segment_type: str, tokens: List[int], trainable: bool, text: str,
        logprobs: Any = None,
    ):
        start = len(self._token_ids)
        self._token_ids.extend(tokens)
        # Keep per-token logprobs aligned 1:1 with token_ids. Only model-generated
        # (response) tokens carry real logprobs; everything else gets 0.0.
        if logprobs is not None and len(logprobs) == len(tokens):
            self._logprobs.extend(float(x) for x in logprobs)
        else:
            self._logprobs.extend([0.0] * len(tokens))
        self._segments.append(TokenSegment(
            segment_type=segment_type, start_idx=start, end_idx=len(self._token_ids),
            trainable=trainable, text=text,
        ))
        self._full_text += text

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_token_ids(self) -> List[int]:
        """Current complete token sequence."""
        return list(self._token_ids)

    def set_routed_experts(self, routed_experts: Any) -> None:
        """Store latest full-sequence routed experts from the rollout engine."""
        self._routed_experts = routed_experts

    def get_trajectory(self) -> TokenTrajectory:
        """Snapshot of the complete trajectory."""
        return TokenTrajectory(
            token_ids=list(self._token_ids),
            segments=list(self._segments),
            prompt_length=self._prompt_length,
            logprobs=list(self._logprobs),
            routed_experts=self._routed_experts,
        )

    def get_full_text(self) -> str:
        """Full trajectory as text (for debugging)."""
        return self._full_text

    @property
    def tokenizer(self):
        """Return the tokenizer."""
        return self._tokenizer

    @property
    def total_length(self) -> int:
        """Total token count."""
        return len(self._token_ids)

    @property
    def prompt_length(self) -> int:
        """Prompt token count."""
        return self._prompt_length

    @property
    def response_length(self) -> int:
        """Response token count."""
        return len(self._token_ids) - self._prompt_length
