"""Agentic RL Data Type Mirrors.

The dataclasses here define adapter boundaries without depending on veRL,
Ray, or trainer internals. They are split into two layers:

* Trajectory primitives (``TrajectoryStep``, ``TraceData``, ``TokenData``,
  ``TrajectoryResult``) - the per-rollout records produced by an agent run.
* Rollout I/O (``RolloutSample``, ``RolloutBatchResult``,
  ``TokenizedRolloutBatch``) - the batch-level boundary between a rollout
  engine and a trainer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Trajectory primitives - per-rollout execution records.
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryStep:
    """Single step in a trajectory.

    Attributes:
        step_type: Type of step (thought, action, action_input, result, answer, error).
        content: Step content.
        metadata: Additional metadata dictionary.
    """
    step_type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary.

        Returns:
            Dictionary representation of the step.
        """
        return {
            "type": self.step_type,
            "content": self.content,
            "metadata": self.metadata
        }


@dataclass
class TraceData:
    """Trace-level data from trajectory execution.

    Attributes:
        records: Serialised trace records.
        full_text: Complete raw trace text for training.
        prompt_text: System + first user prompt (not trained).
        output_text: Everything after: assistant, tool calls, tool results.
        output_segments: Segments with trainable flag.
    """
    records: List[Dict[str, Any]] = field(default_factory=list)
    full_text: str = ""
    prompt_text: str = ""
    output_text: str = ""
    output_segments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_records": self.records,
            "full_trace_text": self.full_text,
            "prompt_text": self.prompt_text,
            "output_text": self.output_text,
            "output_segments": self.output_segments,
        }


@dataclass
class TokenData:
    """Token-level data for RL training (token mode only).

    Attributes:
        ids: Complete token sequence.
        segments: Token segments with trainable flags.
        trainable_mask: Boolean mask for trainable tokens.
    """
    ids: List[int] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    trainable_mask: List[bool] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "token_ids": self.ids,
            "token_segments": self.segments,
            "trainable_mask": self.trainable_mask,
        }


@dataclass
class TrajectoryResult:  # pylint: disable=too-many-instance-attributes
    """Result of a trajectory execution with complete trajectory data.

    Used by Trajectory with MCP-Universe's native Agent and LLM components.
    Provides text-level data (response, history, steps, messages, trace records).

    For token mode, also provides token-level data for RL training.

    Attributes:
        instance_id: Instance identifier.
        trajectory_id: Trajectory identifier.
        response: Final response text.
        reward: Reward value from evaluation.
        finish_reason: Reason for trajectory completion.
        error: Optional error message.
        trace_id: Optional trace identifier.
        trace: Trace-level data (records, full text, prompt/output split).
        num_steps: Number of LLM calls.
        num_tool_calls: Number of tool calls.
        running_time: Total running time in seconds.
        rollout_mode: Rollout mode used ("text" or "token").
        tokens: Token-level data for RL training (token mode only).
        verifier_pass_rate: Pass rate of the verifier.
        verifier_passed: Number of passes of the verifier.
        verifier_total: Total number of the verifier.
    """
    instance_id: Any
    trajectory_id: int
    response: str
    reward: float
    finish_reason: str
    error: Optional[str] = None
    trace_id: Optional[str] = None
    trace: TraceData = field(default_factory=TraceData)
    num_steps: int = 0
    num_tool_calls: int = 0
    running_time: float = 0.0
    rollout_mode: str = "text"
    tokens: TokenData = field(default_factory=TokenData)
    verifier_pass_rate: float = 0.0
    verifier_passed: int = 0
    verifier_total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary.

        Returns:
            Dictionary representation of the trajectory result (flat structure).
        """
        result = {
            "instance_id": self.instance_id,
            "trajectory_id": self.trajectory_id,
            "response": self.response,
            "reward": self.reward,
            "finish_reason": self.finish_reason,
            "error": self.error,
            "trace_id": self.trace_id,
            **self.trace.to_dict(),
            "num_steps": self.num_steps,
            "num_tool_calls": self.num_tool_calls,
            "running_time": self.running_time,
            "rollout_mode": self.rollout_mode,
            "verifier_pass_rate": self.verifier_pass_rate,
            "verifier_passed": self.verifier_passed,
            "verifier_total": self.verifier_total,
        }

        # Include token data only in token mode
        if self.rollout_mode == "token":
            result.update(self.tokens.to_dict())

        return result

    def to_rollout_record(
        self,
        *,
        instance_id: Any | None = None,
        trajectory_id: int | None = None,
    ) -> Dict[str, Any]:
        """Materialize this result for rollout collection.

        The rollout collection layer may be iterating over a dispatcher-owned
        trajectory map, so it can pass the authoritative keys here while this
        dataclass still owns the flattened result schema.
        """
        record = self.to_dict()
        if instance_id is not None:
            record["instance_id"] = instance_id
        if trajectory_id is not None:
            record["trajectory_id"] = trajectory_id
        return record

    def get_training_text(self) -> str:
        """Get complete raw trace text for training.

        Returns:
            Complete raw trace text string.
        """
        return self.trace.full_text

    def get_training_tokens(self) -> Dict[str, Any]:
        """Get token-level data for training (token mode only).

        Returns:
            Dictionary containing:
            - token_ids: Complete token sequence
            - trainable_mask: Boolean mask for trainable tokens
            - segments: Token segments with metadata
        """
        return {
            "token_ids": self.tokens.ids,
            "trainable_mask": self.tokens.trainable_mask,
            "segments": self.tokens.segments
        }


# ---------------------------------------------------------------------------
# Rollout I/O - batch-level boundary between rollout engine and trainer.
# ---------------------------------------------------------------------------


@dataclass
class RolloutSample:
    """Input sample for a rollout engine."""

    instance_id: Any
    instruction: str
    question: str = ""
    output_format: Any = None
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    evaluators: list[Any] = field(default_factory=list)
    env_pool: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, sample: dict[str, Any]) -> "RolloutSample":
        """Create a rollout sample while preserving unknown fields."""
        known_keys = {
            "instance_id",
            "instruction",
            "question",
            "output_format",
            "mcp_servers",
            "evaluators",
            "env_pool",
            "metadata",
        }
        metadata = dict(sample.get("metadata") or {})
        for key, value in sample.items():
            if key not in known_keys:
                metadata[key] = value

        instruction = sample.get("instruction") or sample.get("question", "")
        question = sample.get("question", "")

        return cls(
            instance_id=sample.get("instance_id"),
            instruction=instruction,
            question=question,
            output_format=sample.get("output_format"),
            mcp_servers=_list_from_value(sample.get("mcp_servers", [])),
            evaluators=_list_from_value(sample.get("evaluators", [])),
            env_pool=dict(sample.get("env_pool") or {}),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat sample dict (canonical keys + metadata fields)."""
        result = {
            "instance_id": self.instance_id,
            "instruction": self.instruction or self.question,
            "question": self.question,
            "output_format": self.output_format,
            "mcp_servers": self.mcp_servers,
            "evaluators": self.evaluators,
            "env_pool": self.env_pool,
        }
        result.update(self.metadata)
        return result


def _list_from_value(value: Any) -> list[Any]:
    """Normalize list-like values from framework batches."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return list(value) if isinstance(value, tuple) else [value]


@dataclass
class RolloutBatchResult:
    """Framework-neutral rollout result container.

    ``trajectories`` contains materialized root trajectory results.
    """

    trajectories: list[TrajectoryResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenizedRolloutBatch:
    """Framework-neutral tokenized rollout batch mirror."""

    prompt_ids: list[list[int]] = field(default_factory=list)
    response_ids: list[list[int]] = field(default_factory=list)
    response_mask: list[list[int]] = field(default_factory=list)
    # Per-response-token rollout log-probs (TITO/token mode), aligned with
    # response_ids; empty per-entry for non-TITO. Used for TIS / train-inference
    # mismatch correction.
    response_logprobs: list[list[float]] = field(default_factory=list)
    # Full-sequence routed experts for R3 (one entry per trajectory), aligned
    # with prompt_ids + response_ids before padding: [seq_len, num_layers, topk].
    routed_experts: list[Any] = field(default_factory=list)
    rewards: list[float] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    trajectories: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Behavioral protocols - structural contracts the postprocess layer relies on.
# ---------------------------------------------------------------------------


class TokenizableTrajectory(Protocol):
    """Structural contract for any rollout trajectory the postprocess layer
    can tokenize and aggregate into a `TokenizedRolloutBatch`.

    The concrete trajectory implementation
    (``mcpuniverse.rl.core.trajectory.Trajectory``) implements this Protocol
    directly. Test doubles or alternative engines only need to satisfy the
    same attribute/method shape - no inheritance required.
    """

    @property
    def result(self) -> Optional[TrajectoryResult]:
        """The completed result, or ``None`` if the rollout failed."""

    def get_tito_tokens(self) -> Optional[tuple[Any, Any, list[int]]]:
        """Return ``(prompt_ids, response_ids, response_mask)`` when the LLM
        produced token IDs natively (TITO / token mode), otherwise ``None``.

        Token sequences may be Python lists, numpy arrays, or tensors -
        whatever the LLM wrapper produced. The downstream framework adapter
        normalises them. The loss mask must already be ``list[int]``.
        """

    def get_trace_text(self) -> str:
        """Full trace text (system + user + assistant + tool calls) suitable
        for formatter-based tokenization. Empty string if unavailable.
        """

    def get_instruction(self) -> str:
        """Original user instruction used as the prompt prefix."""

    def get_response_text(self) -> str:
        """Final response text, already stringified (JSON-serialised if dict)."""


__all__ = [
    # Trajectory primitives
    "TrajectoryStep",
    "TraceData",
    "TokenData",
    "TrajectoryResult",
    # Rollout I/O
    "RolloutSample",
    "RolloutBatchResult",
    "TokenizedRolloutBatch",
    # Behavioral protocols
    "TokenizableTrajectory",
]
