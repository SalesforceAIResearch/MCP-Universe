"""Trajectory - Agent rollout trajectory for RL training.

This module provides trajectory implementation using MCP-Universe's native
Agent and LLM components.

Trajectory uses MCP-Universe native Agent and LLM components:
- Supports both text mode (any LLM API) and token mode (TITO, token-in-token-out for RL training)
- Works with any LLM API (OpenAI, Claude, Gemini, vLLM via OpenAI-compatible API, etc.)
- Uses MCP-Universe's native Agent implementations (ReActTrain, HarmonyReAct, etc.)

Captures complete trajectory information including:
- Agent history (thought, action, result, answer)
- Conversation messages
- Trace records
"""
# pylint: disable=broad-exception-caught
from typing import Any, Awaitable, Callable, Dict, List, Optional
from dataclasses import dataclass, field
import json
from loguru import logger

from omegaconf import OmegaConf, DictConfig

from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.agent.manager import AgentManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.llm.tito import AsyncVLLMEngine, TITOLLMWrapper
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.evaluator import Evaluator
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.types import TraceRecord

from .config import TrajectoryConfig, AgentMode
from .formatters import get_formatter
from .trace_logger import TrajectoryTraceLogger


# Constants
DEFAULT_FORMATTER_TYPE = "gpt_oss"
TRACE_TYPE_LLM = "llm"
TRACE_TYPE_TOOL = "tool"
TRACE_TYPE_AGENT = "agent"
FINISH_REASON_STOP = "stop"
FINISH_REASON_ERROR = "error"
FINISH_REASON_ERROR_EXTRACTION = "error_extraction"
FINISH_REASON_ERROR_RUNTIME = "error_runtime"
FINISH_REASON_ERROR_EVALUATION = "error_evaluation"


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
class TrajectoryResult:
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
        }

        # Include token data only in token mode
        if self.rollout_mode == "token":
            result.update(self.tokens.to_dict())

        return result

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


class Trajectory:  # pylint: disable=too-many-instance-attributes
    """Trajectory using MCP-Universe's native Agent and LLM components.

    This trajectory uses MCP-Universe's native Agent implementations (ReActTrain,
    HarmonyReAct, etc.) and works with any LLM API (OpenAI, Claude, Gemini,
    vLLM via OpenAI-compatible API, etc.).

    Features:
    - Uses MCP-Universe's native Agent implementations (ReActTrain, HarmonyReAct)
    - Supports both text mode and token mode rollouts
    - Text mode: text-in, text-out (no tokenization needed)
    - Token mode: token-in, token-out for RL training
    - Works with any LLM API (OpenAI, Claude, Gemini, vLLM via OpenAI-compatible API, etc.)

    Lifecycle:
    1. initialize_trajectory() - Create and initialize MCP-Universe agent
    2. generate_trajectory() - Call agent.execute() to run the task
    3. evaluate_trajectory() - Evaluate the result

    Attributes:
        cfg: Trajectory configuration.
        data: Input data dictionary.
        agent: BaseAgent instance.
        llm: LLM instance (needed for token mode trajectory extraction).
        mcp_servers: List of MCP server configuration dictionaries.
        evaluators: List of evaluators.
        val_mode: Whether in validation mode.
        response: Final response text.
        finished: Whether trajectory is finished.
        finish_reason: Reason for completion.
        error: Optional error message.
        tracer: Tracer instance for recording execution.
        result: Optional TrajectoryResult.
    """

    def __init__(
        self,
        cfg: TrajectoryConfig,
        data: Dict[str, Any],
        agent: BaseAgent,
        mcp_servers: List[Dict[str, Any]],
        evaluators: Optional[List[Evaluator]] = None,
        val_mode: bool = False,
        llm: Optional[Any] = None,
        acquire_env: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
        release_env: Optional[Callable[[], Awaitable[None]]] = None,
        trace_logger: Optional[TrajectoryTraceLogger] = None,
    ) -> None:
        self.cfg = cfg
        self.data = data
        self.agent = agent
        self.llm = llm  # Store LLM reference for token mode
        self.mcp_servers = mcp_servers
        self.evaluators = evaluators or []
        self.val_mode = val_mode

        # Env pool callables (injected by runner when docker_pool is active)
        self._acquire_env = acquire_env
        self._release_env_fn = release_env

        # Trace logger (logs trajectory data to JSONL on evaluate)
        self._trace_logger = trace_logger

        # State
        self.response = ""
        self.finished = False
        self.finish_reason = ""
        self.error = None
        self.tracer = Tracer()

        # Result
        self.result: Optional[TrajectoryResult] = None

    async def initialize_trajectory(self) -> None:
        """Initialize the trajectory - initialize MCP-Universe agent.

        For token mode, wraps the shared ``AsyncVLLMEngine`` in a
        per-trajectory ``TITOLLMWrapper`` so that each trajectory
        maintains independent token state.  Also resets the wrapper.

        If acquire_env callable is set (injected by runner/loop_manager),
        dynamically acquires an environment at init time.  The corresponding
        release_env callable is invoked after trajectory completes.
        """
        # ----- Token mode: create per-trajectory TITO wrapper -----
        if self.cfg.rollout_mode == "token" and self.llm is not None:
            if isinstance(self.llm, AsyncVLLMEngine):
                # Ensure engine is ready (idempotent)
                await self.llm.init_engine()
                tokenizer = await self.llm.get_tokenizer()

                # Build sampling params from TrajectoryConfig, excluding
                # non-sampling keys like max_prompt_length
                sp = {
                    k: v for k, v in self.cfg.sampling_params.items()
                    if k not in ("max_prompt_length",)
                }
                tito_wrapper = TITOLLMWrapper(
                    engine=self.llm,
                    tokenizer=tokenizer,
                    sampling_params=sp,
                    skip_special_tokens=False,
                )
                self.llm = tito_wrapper
                self.agent.set_llm(tito_wrapper)
                if hasattr(self.agent, 'set_tokenizer'):
                    self.agent.set_tokenizer(tokenizer)

            # Reset token trajectory (works for TITOLLMWrapper instances)
            if hasattr(self.llm, 'reset_trajectory'):
                self.llm.reset_trajectory()

        # ----- Dynamic environment acquisition -----
        if self._acquire_env is not None:
            gateway_addr = await self._acquire_env()
            if gateway_addr:
                self.cfg.mcp_gateway_address = gateway_addr

        # Prepare MCP servers, injecting gateway address if configured
        mcp_servers = self.mcp_servers

        if self.cfg.mcp_gateway_address:
            # Inject gateway address into each server config for SSE transport
            mcp_servers = []
            for server in self.mcp_servers:
                server_cfg = dict(server) if isinstance(server, dict) else {"name": server}
                # Set transport to SSE and inject gateway address
                server_cfg["transport"] = "sse"
                server_cfg["gateway_address"] = self.cfg.mcp_gateway_address
                mcp_servers.append(server_cfg)

        await self.agent.initialize(mcp_servers=mcp_servers)

    # ------------------------------------------------------------------
    # Trace extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_trace_records(records: List[TraceRecord]) -> List[Dict[str, Any]]:
        """Convert TraceRecord objects to serialisable dicts."""
        return [
            {
                "id": record.id,
                "trace_id": record.trace_id,
                "parent_id": record.parent_id,
                "records": [
                    {"timestamp": r.timestamp, "data": r.data}
                    for r in record.records
                ],
                "running_time": record.running_time,
                "timestamp": record.timestamp,
                "span_index": record.span_index,
            }
            for record in records
            if isinstance(record, TraceRecord)
        ]

    @staticmethod
    def _count_trace_metrics(
        records: List[TraceRecord],
    ) -> Dict[str, Any]:
        """Count num_steps, num_tool_calls, finish_reason, errors, running_time."""
        num_steps = 0
        num_tool_calls = 0
        running_time = 0.0
        finish_reason = ""
        last_llm_data = None
        errors: List[str] = []

        for record in records:
            if not isinstance(record, TraceRecord):
                continue
            for data_record in record.records:
                data = data_record.data
                record_type = data.get("type", "")

                if record_type == TRACE_TYPE_LLM:
                    num_steps += 1
                    last_llm_data = data
                    if data.get("error"):
                        errors.append(f"LLM error: {data.get('error')}")
                elif record_type == TRACE_TYPE_TOOL:
                    num_tool_calls += 1
                    if data.get("error"):
                        errors.append(f"Tool error: {data.get('error')}")
                elif record_type == TRACE_TYPE_AGENT:
                    if data.get("error"):
                        errors.append(f"Agent error: {data.get('error')}")

        # Last record's running_time is the total
        if records:
            last_record = records[-1]
            if isinstance(last_record, TraceRecord):
                running_time = last_record.running_time or 0.0

        # Derive finish_reason from last LLM record
        if last_llm_data:
            finish_reason = last_llm_data.get("finish_reason", "") or ""
            if not finish_reason:
                finish_reason = (
                    FINISH_REASON_ERROR if last_llm_data.get("error") else FINISH_REASON_STOP
                )

        return {
            "num_steps": num_steps,
            "num_tool_calls": num_tool_calls,
            "running_time": running_time,
            "finish_reason": finish_reason,
            "errors": errors,
        }

    @staticmethod
    def _extract_full_trace_text(
        records: List[TraceRecord],
    ) -> tuple:
        """Get text from the second-to-last TraceRecord.

        Returns ``(full_trace_text, errors)`` where *errors* is a list of
        strings describing any problems encountered.
        """
        errors: List[str] = []
        full_trace_text = ""
        try:
            if len(records) >= 2:
                second_last = records[-2]
                if isinstance(second_last, TraceRecord) and second_last.records:
                    data = second_last.records[0].data
                    if data.get("type") == TRACE_TYPE_LLM:
                        for msg in data.get("messages", []):
                            if isinstance(msg, dict) and msg.get("role") == "raw":
                                full_trace_text = msg.get("content", "")
                                break
                        llm_response = data.get("response", "")
                        if llm_response:
                            full_trace_text = full_trace_text + llm_response
        except Exception as e:
            errors.append(f"Failed to extract full_trace_text: {str(e)}")
            logger.exception("Failed to extract full_trace_text")
        return full_trace_text, errors

    def _split_prompt_output(
        self, full_trace_text: str
    ) -> tuple:
        """Use formatter to split prompt/output.

        Returns ``(result_dict, errors)`` where *result_dict* contains
        ``prompt_text``, ``output_text``, ``output_segments``.
        """
        errors: List[str] = []
        prompt_text = ""
        output_text = ""
        output_segments: List[Dict[str, Any]] = []

        if full_trace_text:
            try:
                formatter = get_formatter(self.cfg.formatter_type)
                instruction = self.data.get("instruction") or self.data.get("question", "")
                fmt_out = formatter.format_trace(full_trace_text, instruction)
                prompt_text = fmt_out.prompt_text
                output_text = fmt_out.output_text
                output_segments = fmt_out.output_segments
            except Exception as e:
                errors.append(f"Failed to split prompt/output: {str(e)}")
                logger.exception("Failed to split prompt/output")
                output_text = full_trace_text

        return {
            "prompt_text": prompt_text,
            "output_text": output_text,
            "output_segments": output_segments,
        }, errors

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def _extract_trajectory_from_trace(self) -> Dict[str, Any]:
        """Extract trajectory data from tracer.

        Returns a dict with trace_records, full_trace_text, prompt_text,
        output_text, output_segments, finish_reason, num_tool_calls,
        num_steps, running_time, and errors.
        """
        errors: List[str] = []

        try:
            records = self.tracer.get_trace()
        except Exception as e:
            errors.append(f"Failed to extract trajectory from trace: {str(e)}")
            logger.exception("Failed to extract trajectory from trace")
            return {
                "trace_records": [], "full_trace_text": "",
                "prompt_text": "", "output_text": "", "output_segments": [],
                "finish_reason": FINISH_REASON_ERROR_EXTRACTION,
                "num_tool_calls": 0, "num_steps": 0, "running_time": 0.0,
                "errors": errors,
            }

        trace_records = self._build_trace_records(records)
        metrics = self._count_trace_metrics(records)
        errors.extend(metrics.pop("errors"))

        full_trace_text, text_errors = self._extract_full_trace_text(records)
        errors.extend(text_errors)

        split_result, split_errors = self._split_prompt_output(full_trace_text)
        errors.extend(split_errors)

        return {
            "trace_records": trace_records,
            "full_trace_text": full_trace_text,
            **split_result,
            **metrics,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # generate_trajectory helpers
    # ------------------------------------------------------------------

    async def _run_agent(self) -> None:
        """Execute the agent. On error, sets ``self.error`` and leaves ``self.response`` empty."""
        try:
            instruction = self.data.get("instruction") or self.data.get("question", "")
            output_format = self.data.get("output_format")
            agent_response = await self.agent.execute(
                message=instruction,
                output_format=output_format,
                tracer=self.tracer,
            )
            self.response = agent_response.get_response()
            self.finished = True
        except Exception as e:
            self.error = str(e)
            self.response = ""
            logger.error(
                f"Trajectory error for {self.cfg.instance_id}-"
                f"{self.cfg.trajectory_id}: {e}"
            )
            logger.exception("Trajectory execution failed")

    def _extract_token_data(
        self, trajectory_data: Dict[str, Any]
    ) -> TokenData:
        """Return ``TokenData`` for token mode.

        Falls back to empty TokenData when token data is unavailable.
        May mutate *trajectory_data* to fill in ``full_trace_text``.
        """
        if self.cfg.rollout_mode != "token" or self.llm is None:
            return TokenData()
        if not hasattr(self.llm, "get_token_trajectory"):
            return TokenData()

        try:
            token_traj = self.llm.get_token_trajectory()
            result = TokenData(
                ids=token_traj.token_ids,
                segments=token_traj.segments,
                trainable_mask=token_traj.get_trainable_mask(),
            )
            if token_traj.text and not trajectory_data["full_trace_text"]:
                trajectory_data["full_trace_text"] = token_traj.text
            return result
        except Exception as e:
            logger.warning(f"Failed to extract token trajectory: {e}")

        return TokenData()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def generate_trajectory(self) -> None:
        """Run the agent using MCP-Universe's native execution."""
        try:
            # 1. Run agent
            await self._run_agent()

            # 2. Extract trace data
            try:
                trajectory_data = self._extract_trajectory_from_trace()
            except Exception as e:
                logger.error(
                    f"Trace extraction failed for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )
                trajectory_data = {
                    "finish_reason": FINISH_REASON_ERROR_RUNTIME,
                    "errors": [],
                    "trace_records": [],
                    "full_trace_text": "",
                    "prompt_text": "",
                    "output_text": "",
                    "output_segments": [],
                    "num_steps": 0,
                    "num_tool_calls": 0,
                    "running_time": 0.0,
                }
                self.error = self.error or str(e)

            # 3. Determine finish reason
            if self.error:
                self.finish_reason = FINISH_REASON_ERROR_RUNTIME
            else:
                self.finish_reason = trajectory_data["finish_reason"] or FINISH_REASON_STOP

            # 4. Log extraction warnings
            for err in trajectory_data["errors"]:
                logger.warning(f"Trajectory extraction warning: {err}")

            # 5. Extract token data (token mode only)
            token_data = self._extract_token_data(trajectory_data)

            # 6. Build result
            self.result = TrajectoryResult(
                instance_id=self.cfg.instance_id,
                trajectory_id=self.cfg.trajectory_id,
                response=self.response,
                reward=0.0,  # Set by evaluate_trajectory
                finish_reason=self.finish_reason,
                error=self.error,
                trace_id=self.tracer.trace_id,
                trace=TraceData(
                    records=trajectory_data["trace_records"],
                    full_text=trajectory_data["full_trace_text"],
                    prompt_text=trajectory_data.get("prompt_text", ""),
                    output_text=trajectory_data.get("output_text", ""),
                    output_segments=trajectory_data.get("output_segments", []),
                ),
                num_steps=trajectory_data["num_steps"],
                num_tool_calls=trajectory_data["num_tool_calls"],
                running_time=trajectory_data["running_time"],
                rollout_mode=self.cfg.rollout_mode,
                tokens=token_data,
            )
        except Exception as e:
            # Ensure result is ALWAYS set, even if extraction/building failed
            logger.error(
                f"generate_trajectory failed for {self.cfg.instance_id}-"
                f"{self.cfg.trajectory_id}: {e}"
            )
            if self.result is None:
                self.result = TrajectoryResult(
                    instance_id=self.cfg.instance_id,
                    trajectory_id=self.cfg.trajectory_id,
                    response=self.response or "",
                    reward=0.0,
                    finish_reason=FINISH_REASON_ERROR_RUNTIME,
                    error=self.error or str(e),
                    trace_id=self.tracer.trace_id if self.tracer else "",
                    trace=TraceData(),
                    num_steps=0,
                    num_tool_calls=0,
                    running_time=0.0,
                    rollout_mode=self.cfg.rollout_mode,
                )
        finally:
            # Cleanup agent's MCP clients to ensure proper resource release
            if self.agent and hasattr(self.agent, "cleanup"):
                try:
                    await self.agent.cleanup()
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup agent for {self.cfg.instance_id}-"
                        f"{self.cfg.trajectory_id}: {e}"
                    )

            # Always release environment back to pool, even if errors occurred
            await self._release_env()

    async def _release_env(self) -> None:
        """Release acquired environment back to pool for reuse.

        This is called after generate_trajectory completes to allow
        environment reuse across batches of trajectories.
        """
        if self._release_env_fn is not None:
            try:
                await self._release_env_fn()
            except Exception as e:
                logger.warning("Failed to release env: %s", e)

    async def evaluate_trajectory(self) -> None:
        """Evaluate the trajectory result.

        All evaluators must pass for the trajectory to be considered successful.

        Note: Agent cleanup is performed in generate_trajectory()'s finally block
        to ensure MCP clients are properly closed after task completion.
        """
        if self.result is None:
            return

        # All evaluators must pass to be successful
        reward = 1.0 if self.evaluators else 0.0

        # Convert response to string for evaluation
        response_for_eval = self.response
        if isinstance(response_for_eval, dict):
            response_for_eval = json.dumps(response_for_eval, ensure_ascii=False)
        elif not isinstance(response_for_eval, str):
            response_for_eval = str(response_for_eval)

        for evaluator in self.evaluators:
            try:
                eval_result = await evaluator.evaluate(response_for_eval)
                if not eval_result.passed:
                    reward = 0.0
                    break  # Any failure means failure
            except Exception as e:
                logger.error(
                    f"Evaluation error for {self.cfg.instance_id}: {e}"
                )
                logger.exception("Evaluation failed")
                self.result.finish_reason = FINISH_REASON_ERROR_EVALUATION
                reward = 0.0
                break

        self.result.reward = reward

        # Log trace data to JSONL (if logger configured)
        if self._trace_logger is not None:
            self._trace_logger.log(self.result)


# ============================================================================
# Factory functions
# ============================================================================

def create_trajectory(
    cfg: TrajectoryConfig,
    data: Dict[str, Any],
    agent_mode: AgentMode,
    llm: Any,
    mcp_manager: MCPManager,
    mcp_servers: List[Dict[str, Any]],
    agent_config: Optional[Dict[str, Any]] = None,
    evaluators: Optional[List[Evaluator]] = None,
    val_mode: bool = False,
    tokenizer: Optional[Any] = None,
    acquire_env: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    release_env: Optional[Callable[[], Awaitable[None]]] = None,
    trace_logger: Optional[TrajectoryTraceLogger] = None,
) -> "Trajectory":
    """Create a Trajectory using MCP-Universe's native Agent and LLM components.

    This creates a trajectory that works with any LLM API.
    Supports both text mode and token mode rollouts.

    Args:
        cfg: Trajectory configuration (includes rollout_mode).
        data: Input data (instruction, output_format, etc.).
        agent_mode: Agent mode (react_train, harmony).
        llm: MCP-Universe LLM instance (OpenAI, Claude, Gemini, AsyncVLLMModel, etc.).
        mcp_manager: MCPManager instance.
        mcp_servers: List of MCP server configuration dictionaries.
        agent_config: Optional agent-specific config.
        evaluators: List of evaluators.
        val_mode: Validation mode flag.
        tokenizer: Optional tokenizer for token count checking.
        acquire_env: Optional async callable returning a gateway address.
        release_env: Optional async callable to release the acquired environment.
        trace_logger: Optional TrajectoryTraceLogger for JSONL trace logging.

    Returns:
        Trajectory wrapping the native agent.
    """
    # Get agent class name from mode
    agent_class_name = agent_mode.to_agent_class_name()

    # Build agent config
    # Convert OmegaConf to dict if needed (OmegaConf struct mode doesn't allow adding new keys)
    if agent_config is not None:
        if isinstance(agent_config, DictConfig):
            full_agent_config = OmegaConf.to_container(agent_config, resolve=True)
        else:
            full_agent_config = dict(agent_config)
    else:
        full_agent_config = {}
    if "max_iterations" not in full_agent_config:
        full_agent_config["max_iterations"] = cfg.max_iterations

    # Create agent using MCP-Universe's AgentManager
    agent_manager = AgentManager()
    agent = agent_manager.build_agent(
        class_name=agent_class_name,
        mcp_manager=mcp_manager,
        llm=llm,
        config=full_agent_config
    )

    # Set tokenizer if provided (for token count checking).
    # For token mode, try to get tokenizer from LLM.
    if tokenizer is not None and hasattr(agent, 'set_tokenizer'):
        agent.set_tokenizer(tokenizer)
    elif cfg.rollout_mode == "token" and hasattr(llm, 'get_tokenizer'):
        try:
            llm_tokenizer = llm.get_tokenizer()
            if llm_tokenizer is not None and hasattr(agent, 'set_tokenizer'):
                agent.set_tokenizer(llm_tokenizer)
        except Exception:
            pass  # Tokenizer not available yet (will be initialized on first call)

    return Trajectory(
        cfg=cfg,
        data=data,
        agent=agent,
        mcp_servers=mcp_servers,
        evaluators=evaluators,
        val_mode=val_mode,
        llm=llm,  # Pass LLM for token mode trajectory extraction
        acquire_env=acquire_env,
        release_env=release_env,
        trace_logger=trace_logger,
    )


def create_llm(llm_type: str, llm_config: Dict[str, Any]) -> Any:
    """Create an LLM using MCP-Universe's ModelManager.

    For ``async_vllm`` / ``AsyncVLLMModel`` types, constructs an
    ``AsyncVLLMEngine`` directly (it is not registered in ModelManager).
    The engine is returned *without* calling ``init_engine()``; callers
    should await that separately (it is idempotent).

    Args:
        llm_type: LLM class name (OpenAI, Claude, async_vllm, etc.).
        llm_config: LLM configuration dictionary.

    Returns:
        MCP-Universe LLM instance (or AsyncVLLMEngine for token mode).
    """
    if llm_type in ("async_vllm", "AsyncVLLMModel"):
        cfg = dict(llm_config)
        # Strip keys that belong to sampling / rollout, not the engine
        _non_engine_keys = (
            "rollout_mode", "temperature", "top_p", "max_tokens",
            "stop", "include_stop_str_in_output", "skip_special_tokens",
            "max_completion_tokens", "reasoning", "max_prompt_length",
        )
        for k in _non_engine_keys:
            cfg.pop(k, None)

        model_path = cfg.pop("model_path", None) or cfg.pop("model_name", None)
        if not model_path:
            raise ValueError(
                "async_vllm requires 'model_path' or 'model_name' in llm_config"
            )
        return AsyncVLLMEngine(
            model_path=model_path,
            tensor_parallel_size=cfg.pop("tensor_parallel_size", 1),
            dtype=cfg.pop("dtype", "auto"),
            trust_remote_code=cfg.pop("trust_remote_code", True),
            max_model_len=cfg.pop("max_model_len", None),
            gpu_memory_utilization=cfg.pop("gpu_memory_utilization", 0.9),
        )

    model_manager = ModelManager()
    return model_manager.build_model(llm_type, llm_config)
