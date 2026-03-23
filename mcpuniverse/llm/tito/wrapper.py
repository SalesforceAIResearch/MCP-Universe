"""
TITO LLM Wrapper — agent-compatible LLM that avoids retokenization.

Wraps an inference engine (vLLM/SGLang async engine or VERL Ray actor)
and exposes the standard ``generate_async(messages)`` interface while
internally maintaining a token sequence via TokenTrajectoryManager.

Supports both vLLM and SGLang backends — both return
``TokenOutput(token_ids, log_probs)`` via the same generate() API.

Workflow per agent turn:
  1. Agent calls generate_async(messages=[{"role": "raw", "content": prompt}])
  2. Wrapper detects new content since last call
  3. New content (tool result) is tokenized and appended
  4. Engine generates from the full token sequence (token in -> token out)
  5. Response tokens are appended directly (no retokenization)
  6. Response text is returned to the agent
"""

import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import ray
except ImportError:
    ray = None

from mcpuniverse.common.config import BaseConfig
from .manager import TokenTrajectoryManager, TokenTrajectory


@dataclass
class TITOLLMConfig(BaseConfig):
    """Sampling configuration for TITO LLM."""
    model_name: str = "tito"
    temperature: float = 1.0
    top_p: float = 1.0
    max_completion_tokens: int = 4096
    reasoning: str = "low"


class TITOLLMWrapper:
    """
    Agent-compatible LLM wrapper with TITO (Token In Token Out) support.

    Accepts a local async engine (vLLM or SGLang) or a VERL Ray actor as the
    backing engine.  The agent sees text in / text out; internally the
    wrapper keeps an ever-growing token sequence and only tokenizes new
    external content (tool results).

    Args:
        engine: Async inference engine instance or Ray actor reference (VERL).
        tokenizer: HuggingFace tokenizer.
        sampling_params: Default sampling parameters dict.  Standard keys
            (``temperature``, ``top_p``, ``max_tokens``) populate
            ``TITOLLMConfig``; all others (``stop``, etc.) are passed
            through to the engine on every call.
        skip_special_tokens: Whether to skip special tokens when decoding.
    """

    config_class = TITOLLMConfig
    alias = ["tito", "tito_llm"]

    def __init__(
        self,
        engine: Any,
        tokenizer: Any,
        sampling_params: Optional[Dict[str, Any]] = None,
        skip_special_tokens: bool = False,
        max_context_length: int = 0,
    ):
        self._engine = engine
        self._tokenizer = tokenizer
        self._skip_special_tokens = skip_special_tokens
        self._max_context_length = max_context_length  # 0 = no limit

        # Detect engine type: local async engine vs Ray actor
        gen = getattr(engine, "generate", None)
        self._is_local = gen is not None and asyncio.iscoroutinefunction(gen)

        # Store full default sampling params (passed through to engine)
        self._default_sampling_params = dict(sampling_params or {})

        # Build config for agent-framework compatibility
        cfg = dict(self._default_sampling_params)
        if "max_tokens" in cfg:
            cfg.setdefault("max_completion_tokens", cfg.pop("max_tokens"))
        _valid = {f.name for f in dataclasses.fields(TITOLLMConfig)}
        self.config = TITOLLMConfig(**{k: v for k, v in cfg.items() if k in _valid})

        # Token trajectory manager
        self._manager = TokenTrajectoryManager(
            tokenizer=tokenizer, skip_special_tokens=skip_special_tokens,
        )

        # Prompt tracking for incremental updates
        self._last_prompt_length: int = 0
        self._request_counter: int = 0

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def reset_trajectory(self):
        """Reset for a new rollout episode."""
        self._manager.reset()
        self._last_prompt_length = 0
        self._request_counter = 0

    async def generate_async(
        self,
        messages: Optional[List[Dict[str, str]]] = None,
        _tracer: Any = None,
        _callbacks: Any = None,
        **kwargs,
    ) -> str:
        """
        Generate a response (agent-compatible interface).

        Args:
            messages: ``[{"role": "raw", "content": full_prompt_text}]``
            tracer: Ignored (agent compatibility).
            callbacks: Ignored (agent compatibility).
            **kwargs: Per-call overrides for sampling params
                      (temperature, stop, max_tokens, etc.).

        Returns:
            Generated response text.
        """
        # Extract prompt text
        if messages and len(messages) == 1 and messages[0].get("role") == "raw":
            prompt_text = messages[0]["content"]
        elif messages:
            prompt_text = self._format_messages(messages)
        else:
            raise ValueError("No messages provided")

        # First call: tokenize full prompt
        # Continuation: tokenize only new content (tool result)
        if not self._manager.get_token_ids():
            self._manager.set_initial_prompt(prompt_text, add_special_tokens=True)
            self._last_prompt_length = len(prompt_text)
        elif len(prompt_text) > self._last_prompt_length:
            new_content = prompt_text[self._last_prompt_length:]
            self._manager.append_tool_result(
                new_content, trainable=False, add_special_tokens=False,
            )
            self._last_prompt_length = len(prompt_text)

        # Guard: stop early if token count exceeds model context length
        current_len = self._manager.total_length
        if self._max_context_length and current_len >= self._max_context_length:
            raise ValueError(
                f"Token count ({current_len}) exceeds max context length "
                f"({self._max_context_length}). Stopping trajectory."
            )

        # Build sampling params: defaults + per-call overrides
        sp = dict(self._default_sampling_params)
        sp.update(kwargs)

        self._request_counter += 1
        request_id = f"tito_{id(self)}_{self._request_counter}"

        # Engine call: token in -> token out
        response_text, output_tokens = await self._call_engine(
            self._manager.get_token_ids(), sp, request_id,
        )

        # Append response tokens directly (no retokenization)
        self._manager.append_response_tokens(
            output_tokens, trainable=True, response_text=response_text,
        )

        # Track prompt length so we can detect new content on next call
        self._last_prompt_length = len(prompt_text) + len(response_text)
        return response_text

    # ------------------------------------------------------------------
    # Engine dispatch
    # ------------------------------------------------------------------

    async def _call_engine(
        self,
        token_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: str,
    ) -> Tuple[str, List[int]]:
        """Call engine and return (response_text, output_token_ids)."""
        if self._is_local:
            return await self._call_local(token_ids, sampling_params, request_id)
        return await self._call_ray(token_ids, sampling_params, request_id)

    async def _call_local(self, token_ids, sampling_params, request_id):
        """Call a local async inference engine directly."""
        sampling_params = self._filter_sampling_params(sampling_params)
        text, meta = await self._engine.generate(
            prompt_ids=token_ids,
            sampling_params=sampling_params,
            request_id=request_id,
        )
        return text, meta.get("output_tokens", [])

    # Sampling params accepted by both vLLM and SGLang (union of both)
    _ENGINE_SAMPLING_KEYS = frozenset({
        # Common keys (both vLLM and SGLang)
        "temperature", "top_p", "top_k", "min_p",
        "frequency_penalty", "presence_penalty", "repetition_penalty",
        "stop", "stop_token_ids", "seed", "skip_special_tokens",
        "logprobs", "top_logprobs", "max_tokens", "n",
        # vLLM-specific (ignored by SGLang)
        "spaces_between_special_tokens",
        "min_tokens", "best_of", "use_beam_search", "length_penalty",
        # SGLang-specific (ignored by vLLM)
        "max_new_tokens", "return_logprob",
    })

    def _filter_sampling_params(self, sp: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only keys that the inference engine accepts."""
        return {k: v for k, v in sp.items() if k in self._ENGINE_SAMPLING_KEYS}

    async def _call_ray(self, token_ids, sampling_params, request_id):
        """Call a VERL Ray actor (works with both vLLM and SGLang servers)."""
        sampling_params = self._filter_sampling_params(sampling_params)
        # VERL sets max_tokens internally
        sampling_params.pop("max_tokens", None)
        sampling_params.pop("max_new_tokens", None)

        future = self._engine.generate.remote(
            prompt_ids=token_ids,
            sampling_params=sampling_params,
            request_id=request_id,
        )
        result = await asyncio.to_thread(ray.get, future)

        if hasattr(result, "token_ids"):
            # VERL TokenOutput (Pydantic model with .token_ids, .log_probs)
            tokens = list(result.token_ids)
            text = self._tokenizer.decode(
                tokens, skip_special_tokens=self._skip_special_tokens,
            )
            return text, tokens

        # Legacy (text, meta) tuple
        text, meta = result
        return text, meta.get("output_tokens", [])

    # ------------------------------------------------------------------
    # Trajectory access
    # ------------------------------------------------------------------

    def get_trajectory(self) -> TokenTrajectory:
        """Complete token trajectory for training."""
        return self._manager.get_trajectory()

    # Alias expected by the RL trajectory module
    get_token_trajectory = get_trajectory

    def get_prompt_ids(self) -> List[int]:
        """Prompt token IDs."""
        return self._manager.get_token_ids()[:self._manager.prompt_length]

    def get_response_ids(self) -> List[int]:
        """Response token IDs (all non-prompt tokens)."""
        return self._manager.get_token_ids()[self._manager.prompt_length:]

    def get_loss_mask(self) -> List[bool]:
        """Loss mask (True for trainable tokens)."""
        return self._manager.get_trajectory().get_loss_mask()

    def get_full_text(self) -> str:
        """Full trajectory as text."""
        return self._manager.get_full_text()

    def get_tokenizer(self):
        """Return the tokenizer."""
        return self._tokenizer

    @property
    def tokenizer(self):
        """Return the tokenizer."""
        return self._tokenizer

    @property
    def total_length(self) -> int:
        """Total token count."""
        return self._manager.total_length

    @property
    def prompt_length(self) -> int:
        """Prompt token count."""
        return self._manager.prompt_length

    # ------------------------------------------------------------------
    # Agent-framework compatibility
    # ------------------------------------------------------------------

    async def close(self):
        """No-op (engine is managed externally)."""

    def dump_config(self) -> Dict[str, Any]:
        """Serialize configuration."""
        return {
            "class": self.__class__.__name__,
            "config": self.config.to_dict(),
            "skip_special_tokens": self._skip_special_tokens,
        }

    @staticmethod
    def _format_messages(messages: List[Dict[str, str]]) -> str:
        """Fallback message formatting for non-raw messages."""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "raw":
                parts.append(content)
            else:
                parts.append(f"{role}: {content}")
        return "\n\n".join(parts)
