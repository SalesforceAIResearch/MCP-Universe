"""Trajectory - Agent rollout trajectory for RL training.

This module provides trajectory implementation using MCP-Universe's native
Agent and LLM components:
- Supports both text mode (any LLM API) and token mode (TITO, token-in-token-out for RL training)
- Works with any LLM API (OpenAI, Claude, Gemini, vLLM via OpenAI-compatible API, etc.)
- Uses MCP-Universe's native Agent implementations (ReActTrain, HarmonyReAct, etc.)

Captures complete trajectory information including:
- Agent history (thought, action, result, answer)
- Conversation messages
- Trace records
"""
# pylint: disable=broad-exception-caught,too-many-lines
from typing import Any, Awaitable, Callable, Dict, List, Optional
import asyncio
import json
from loguru import logger

from omegaconf import OmegaConf, DictConfig

from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.agent.manager import AgentManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.llm.tito import AsyncSGLangEngine, AsyncVLLMEngine, TITOLLMWrapper
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.evaluator import Evaluator
from mcpuniverse.common.context import Context
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.types import TraceRecord

from .config import TrajectoryConfig, AgentMode
from .formatters import get_formatter
from .trace_logger import TrajectoryTraceLogger
from .types import TraceData, TokenData, TrajectoryResult


# Constants
TRACE_TYPE_LLM = "llm"
TRACE_TYPE_TOOL = "tool"
TRACE_TYPE_AGENT = "agent"
FINISH_REASON_STOP = "stop"
FINISH_REASON_ERROR = "error"
FINISH_REASON_ERROR_EXTRACTION = "error_extraction"
FINISH_REASON_ERROR_RUNTIME = "error_runtime"
FINISH_REASON_ERROR_EVALUATION = "error_evaluation"


class Trajectory:  # pylint: disable=too-many-instance-attributes
    """This trajectory uses MCP-Universe's native Agent implementations (e.g. ReActTrain,
    HarmonyReAct, etc.) and works with any LLM API (OpenAI, Claude, Gemini,
    vLLM via OpenAI-compatible API, etc.).

    Features:
    - Uses MCP-Universe's native Agent implementations (ReActTrain, HarmonyReAct)
    - Supports both text mode and token mode rollouts
    - Text mode: text-in, text-out (no tokenization needed)
    - Token mode: token-in, token-out for RL training
    - Works with any LLM API (OpenAI, Claude, Gemini, vLLM via OpenAI-compatible API, etc.)

    Lifecycle:
    1. initialize() - Create and initialize MCP-Universe agent
    2. generate()   - Call agent.execute() to run the task
    3. evaluate()   - Evaluate the result
    4. cleanup()    - Release env back to pool and run user hook

    Key Attributes:
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
        before_evaluate_hook: Optional[Callable[..., Awaitable[None]]] = None,
        cleanup_hook: Optional[Callable[..., Awaitable[None]]] = None,
        setup_hook: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        self.cfg = cfg
        self.data = data
        self.agent = agent
        self.llm = llm  # Store LLM reference for token mode
        self.mcp_servers = mcp_servers
        self.evaluators = evaluators or []
        self.val_mode = val_mode

        # Per-trajectory context shared with evaluators. Stateful envs populate
        # it during setup (e.g. gateway address, task name) so context-aware
        # comparison funcs can read it at eval time. Empty for stateless tasks.
        self.context = Context()

        # Env pool callables (injected by runner when docker_pool is active)
        self._acquire_env = acquire_env
        self._release_env_fn = release_env

        # Trace logger (logs trajectory data to JSONL on evaluate)
        self._trace_logger = trace_logger
        self._before_evaluate_hook = before_evaluate_hook
        self._cleanup_hook = cleanup_hook
        # Optional async hook run after env acquisition and before the agent
        # runs (used by stateful envs to reset/seed task state). No-op if None.
        self._setup_hook = setup_hook

        # State
        self.response = ""
        self.finished = False
        self.finish_reason = ""
        self.error = None
        self.tracer = Tracer()
        self._agent_cleaned = False
        self._env_released = False
        self._cleanup_done = False
        self._closed = False
        # Token-mode (TITO) LLM wrapper; attached post-construction by the
        # rollout builder when rollout_mode == "token". None otherwise.
        self._tito_llm = None

        # Result
        self.result: Optional[TrajectoryResult] = None

    # ------------------------------------------------------------------
    # TokenizableTrajectory protocol accessors
    # (used by the postprocess layer to tokenize a completed rollout)
    # ------------------------------------------------------------------

    def get_tito_tokens(self) -> Optional[tuple[Any, Any, List[int]]]:
        """Return pre-computed ``(prompt_ids, response_ids, response_mask)`` if
        the LLM wrapper produced token IDs natively (TITO / token mode).

        Token sequences are returned **as-is** from the wrapper (list, numpy
        array, tensor, ...) to avoid unnecessary copies on the hot rollout
        path. The downstream framework adapter
        is responsible for any conversion. The loss mask is always
        materialized as ``list[int]`` since it is computed here.

        Returns ``None`` when the trajectory did not use a token-emitting LLM,
        signaling the postprocess layer to fall back to text tokenization.
        """
        tito_llm = getattr(self, "_tito_llm", None)
        if tito_llm is None:
            return None
        return (
            tito_llm.get_prompt_ids(),
            tito_llm.get_response_ids(),
            [1 if mask else 0 for mask in tito_llm.get_loss_mask()],
        )

    def get_tito_logprobs(self) -> Optional[List[float]]:
        """Per-response-token rollout log-probs (TITO/token mode), aligned with
        the response_ids from ``get_tito_tokens``. ``None`` for non-TITO."""
        tito_llm = getattr(self, "_tito_llm", None)
        if tito_llm is None or not hasattr(tito_llm, "get_response_logprobs"):
            return None
        return tito_llm.get_response_logprobs()

    def get_tito_routed_experts(self) -> Any:
        """Latest full-sequence routed experts for R3 (TITO/token mode).

        Expected shape before padding: [len(prompt_ids)+len(response_ids),
        num_layers, topk]. Returns None for non-TITO or when the rollout engine
        did not provide routing data.
        """
        tito_llm = getattr(self, "_tito_llm", None)
        if tito_llm is None or not hasattr(tito_llm, "get_routed_experts"):
            return None
        return tito_llm.get_routed_experts()

    def get_trace_text(self) -> str:
        """Return the full trace text for formatter-based tokenization, or
        an empty string if no trace was captured (e.g. trajectory failed
        before any LLM call).
        """
        result = self.result
        if result is None or result.trace is None:
            return ""
        return result.trace.full_text or ""

    def get_instruction(self) -> str:
        """Return the original user instruction used as the prompt prefix.

        Falls back to ``question`` when ``instruction`` is missing, mirroring `RolloutSample.from_mapping`.
        """
        data = self.data or {}
        return data.get("instruction") or data.get("question", "") or ""

    def get_response_text(self) -> str:
        """Return the final response text, JSON-serialising dict responses."""
        result = self.result
        if result is None:
            return ""
        response = result.response or ""
        if isinstance(response, dict):
            return json.dumps(response, ensure_ascii=False)
        return response

    async def initialize(self) -> None:
        """Full per-trajectory init = env stage + connect, as a single step.

        Convenience for callers that run init in one shot (e.g. the slime
        integration). The ``RolloutPipeline`` instead calls
        ``initialize_env`` (env worker) and ``connect`` (run worker)
        as two separate stages, so the slow container acquisition stays off
        the run worker's hot path.
        """
        await self.initialize_env()
        await self.connect()

    async def initialize_env(self) -> None:
        """Env-stage init (slow, NOT task-bound): acquire a docker env and run
        the optional setup hook.

        Safe to run in a dedicated env worker, separate from the run task that
        later opens the MCP connection. Sets ``cfg.mcp_gateway_address`` and the
        per-trajectory context so the run / eval stages can use them.
        """
        # A dispatcher init retry may have already run cleanup for a failed
        # attempt. Reset these per-attempt gates so the successful attempt still
        # cleans up its newly acquired resources.
        self._agent_cleaned = False
        self._env_released = False
        self._cleanup_done = False

        # ----- Dynamic environment acquisition -----
        if self._acquire_env is not None:
            gateway_addr = await self._acquire_env()
            if gateway_addr:
                self.cfg.mcp_gateway_address = gateway_addr

        # ----- Optional stateful-env setup (after acquire, before agent) -----
        # Expose the runtime gateway address on the shared context and let an
        # optional setup hook reset/seed task state (e.g. reset a database,
        # seed fixture files). No-op for stateless tasks (setup_hook is None).
        if self.cfg.mcp_gateway_address:
            self.context.env.setdefault("MCP_GATEWAY_ADDRESS", self.cfg.mcp_gateway_address)
        if self._setup_hook is not None:
            await self._setup_hook(
                context=self.context,
                gateway_address=self.cfg.mcp_gateway_address,
                data=self.data,
                cfg=self.cfg,
            )

    async def connect(self) -> None:
        """Run-stage init (task-bound): build the per-trajectory TITO wrapper
        (token mode) and open the MCP connection.

        MUST run in the same asyncio task as ``generate``: the MCP client
        uses anyio cancel scopes / task groups bound to the task that opens the
        connection (exiting them from a different task raises "Attempted to exit
        cancel scope in a different task"). That is exactly why env acquisition
        (not task-bound) can be a separate stage but the connection cannot.
        """
        # ----- Token mode: create per-trajectory TITO wrapper -----
        if self.cfg.rollout_mode == "token" and self.llm is not None:
            if isinstance(self.llm, (AsyncVLLMEngine, AsyncSGLangEngine)):
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
    # generate() helpers
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
    # Rollout lifecycle (generate / evaluate / cleanup)
    # ------------------------------------------------------------------

    async def generate(self) -> None:
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
                reward=0.0,  # Set by evaluate()
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
                f"generate() failed for {self.cfg.instance_id}-"
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
            await self._cleanup_agent_runtime()
            # NOTE: env release is NOT done here. Some
            # evaluators need to query the live env during
            # evaluate().

    async def _cleanup_agent_runtime(self) -> None:
        """Close agent MCP clients once while preserving trajectory data."""
        if self._agent_cleaned:
            return
        self._agent_cleaned = True
        if self.agent and hasattr(self.agent, "cleanup"):
            try:
                await self.agent.cleanup()
            except asyncio.CancelledError as e:
                logger.warning(
                    f"Agent cleanup cancelled for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup agent for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )

    async def _release_env(self) -> None:
        """Release acquired environment back to pool for reuse.

        This is called after generate() completes to allow
        environment reuse across batches of trajectories.
        """
        if self._env_released:
            return
        self._env_released = True
        if self._release_env_fn is not None:
            try:
                await self._release_env_fn()
            except asyncio.CancelledError as e:
                logger.warning("Env release cancelled: {}", repr(e))
            except Exception as e:
                logger.warning("Failed to release env: {}", e)

    async def cleanup(self) -> None:
        """Finalize trajectory-local resources without clearing materialized results.

        Order: agent runtime (MCP clients) is closed first, then the optional
        user ``cleanup_hook`` runs (with the result still available for
        post-processing), then the docker env is released back to the pool.

        Idempotent: subsequent calls return immediately.
        """
        if self._cleanup_done:
            return
        self._cleanup_done = True

        await self._cleanup_agent_runtime()

        if self._cleanup_hook is not None:
            try:
                trace_records = self.result.trace.records if self.result else []
                await self._cleanup_hook(
                    data=self.data,
                    result=self.result,
                    trace_records=trace_records,
                    trajectory=self,
                )
            except asyncio.CancelledError as e:
                logger.warning(
                    f"Cleanup hook cancelled for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Cleanup hook failed for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )

        await self._release_env()

    async def evaluate(self) -> None:
        """Evaluate the trajectory result.

        All evaluators must pass for the trajectory to be considered successful.

        Note: Agent cleanup is performed in generate()'s finally block to
        ensure MCP clients are properly closed after task completion.
        """
        if self.result is None:
            return

        if self._before_evaluate_hook is not None:
            try:
                await self._before_evaluate_hook(
                    data=self.data,
                    result=self.result,
                    trajectory=self,
                )
            except Exception as e:
                logger.warning(
                    f"Before-evaluate hook failed for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )

        # All evaluators must pass to be successful
        reward = 1.0 if self.evaluators else 0.0
        verifier_total = len(self.evaluators)
        verifier_passed = 0

        # Convert response to string for evaluation
        response_for_eval = self.response
        if isinstance(response_for_eval, dict):
            response_for_eval = json.dumps(response_for_eval, ensure_ascii=False)
        elif not isinstance(response_for_eval, str):
            response_for_eval = str(response_for_eval)

        for evaluator in self.evaluators:
            try:
                # Surface per-trajectory runtime context (e.g. env gateway
                # address, task name written by the setup hook) to context-aware
                # comparison funcs. Evaluators are per-trajectory, so updating
                # their context here is local and keeps the shared Evaluator API
                # unchanged. No effect when context is empty (stateless tasks).
                ev_ctx = getattr(evaluator, "_context", None)
                if ev_ctx is not None and self.context.env:
                    ev_ctx.env.update(self.context.env)
                eval_result = await evaluator.evaluate(response_for_eval)
                if not eval_result.passed:
                    reward = 0.0
                    break  # Any failure means failure
                verifier_passed += 1
            except Exception as e:
                logger.error(
                    f"Evaluation error for {self.cfg.instance_id}: {e}"
                )
                logger.exception("Evaluation failed")
                self.result.finish_reason = FINISH_REASON_ERROR_EVALUATION
                reward = 0.0
                break

        self.result.reward = reward
        self.result.verifier_total = verifier_total
        self.result.verifier_passed = verifier_passed
        self.result.verifier_pass_rate = (
            verifier_passed / verifier_total if verifier_total else 0.0
        )

        # Log trace data to JSONL (if logger configured)
        if self._trace_logger is not None:
            self._trace_logger.log(self.result)

    async def close(
        self,
        *,
        clear_result: bool = False,
        clear_inputs: bool = False,
    ) -> None:
        """Finalize and optionally release large runtime references."""
        if self._closed:
            return
        self._closed = True

        await self.cleanup()

        llms_to_close: List[Any] = []
        if self.llm is not None:
            llms_to_close.append(self.llm)
        tito_llm = getattr(self, "_tito_llm", None)
        if tito_llm is not None and tito_llm not in llms_to_close:
            llms_to_close.append(tito_llm)

        for llm in llms_to_close:
            if hasattr(llm, "close"):
                try:
                    close_result = llm.close()
                    if hasattr(close_result, "__await__"):
                        await close_result
                except asyncio.CancelledError as e:
                    logger.warning(
                        f"LLM close cancelled for {self.cfg.instance_id}-"
                        f"{self.cfg.trajectory_id}: {e}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to close LLM for {self.cfg.instance_id}-"
                        f"{self.cfg.trajectory_id}: {e}"
                    )

        if clear_inputs and self.agent is not None and hasattr(
            self.agent, "release_runtime_references",
        ):
            try:
                self.agent.release_runtime_references()
            except Exception as e:
                logger.warning(
                    f"Failed to release agent runtime refs for {self.cfg.instance_id}-"
                    f"{self.cfg.trajectory_id}: {e}"
                )

        if clear_result:
            self.result = None
        if clear_inputs:
            self.data = None
            self.agent = None
            self.llm = None
            self._tito_llm = None
            self.mcp_servers = []


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
    before_evaluate_hook: Optional[Callable[..., Awaitable[None]]] = None,
    cleanup_hook: Optional[Callable[..., Awaitable[None]]] = None,
    setup_hook: Optional[Callable[..., Awaitable[None]]] = None,
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
        before_evaluate_hook: Optional async hook run before evaluators.
        cleanup_hook: Optional async hook run by cleanup().

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
        before_evaluate_hook=before_evaluate_hook,
        cleanup_hook=cleanup_hook,
        setup_hook=setup_hook,
    )


def create_llm(llm_type: str, llm_config: Dict[str, Any]) -> Any:
    """Create an LLM using MCP-Universe's ModelManager.

    For direct token-mode engines (``async_vllm`` / ``async_sglang``),
    constructs the TITO-compatible engine directly (these are not registered
    in ModelManager). The engine is returned *without* calling
    ``init_engine()``; callers should await that separately (it is
    idempotent).

    Args:
        llm_type: LLM class name (OpenAI, Claude, async_vllm, async_sglang, etc.).
        llm_config: LLM configuration dictionary.

    Returns:
        MCP-Universe LLM instance (or a direct async TITO engine for token mode).
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

    if llm_type in ("async_sglang", "AsyncSGLangModel"):
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
                "async_sglang requires 'model_path' or 'model_name' in llm_config"
            )
        return AsyncSGLangEngine(
            model_path=model_path,
            tensor_parallel_size=cfg.pop("tensor_parallel_size", 1),
            dtype=cfg.pop("dtype", "auto"),
            trust_remote_code=cfg.pop("trust_remote_code", True),
            max_model_len=cfg.pop("max_model_len", None),
            gpu_memory_utilization=cfg.pop("gpu_memory_utilization", 0.9),
            random_seed=cfg.pop("random_seed", 42),
            **cfg,
        )

    model_manager = ModelManager()
    return model_manager.build_model(llm_type, llm_config)
