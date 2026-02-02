"""
Post-processing agent that produces BOTH direct extraction AND code in a single LLM call.

This agent is cost-optimized:
- ONE LLM call (tool output sent only once as input)
- Generates both: direct extraction text AND Python code
- Executes the code
- Returns both outputs to main agent

Iteration only happens if:
- Output is empty from both methods
- Code execution fails
"""
import json
from typing import Any, Dict, Optional, Union, List
from dataclasses import dataclass

from mcpuniverse.agent.base import BaseAgent, BaseAgentConfig
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.mcpplus.common.executor import SafeCodeExecutor
from mcpuniverse.mcpplus.agent.react_postprocess import count_tokens, PostProcessStats


@dataclass
class DualPostProcessAgentConfig(BaseAgentConfig):
    """
    Configuration for DualPostProcessAgent.

    Attributes:
        enable_memory: Enable session memory (not used currently).
        max_iterations: Maximum iterations if output is empty or code fails.
        enable_reflection: Enable LLM-based reflection on output quality.
        max_tool_output_chars: Maximum characters of tool output to show to LLM.
        execution_timeout: Timeout for code execution.
        custom_prompt: Optional custom prompt text to use instead of default DUAL_EXTRACTION_PROMPT.
    """
    enable_memory: bool = False
    max_iterations: int = 3
    enable_reflection: bool = False
    max_tool_output_chars: Optional[int] = None
    execution_timeout: int = 500
    custom_prompt: Optional[str] = None


# Prompt that asks for both extraction and code
DUAL_EXTRACTION_PROMPT = """
You are analyzing tool output to extract specific information. You must provide TWO extraction methods:

1. DIRECT EXTRACTION: Simple text-based extraction of the key information
2. CODE-BASED EXTRACTION: Python code that parses/filters the data

Tool: {tool_name}
{tool_description_section}

Tool Output ({output_length} characters):
{tool_output}

Agent's Goal: {expected_info}

{iteration_history_section}

YOUR TASK:

Provide BOTH extraction methods in JSON format:

{{
  "direct_extraction": "<extracted information as plain text>",
  "code": "<Python code that extracts/filters the data>"
}}

Guidelines:
- **direct_extraction**: Extract and return the relevant information as simple, readable text
- **code**: Write Python code that processes `data` (the tool output) and assigns result to `result` variable
  - The tool output is available as `data` (string)
  - Parse, filter, or transform as needed
  - Assign final output to `result`
  - Keep code concise and focused

{iteration_instruction_section}

Output ONLY valid JSON with both fields. No other text.
""".strip()


REFLECTION_PROMPT = """
Evaluate if the extraction results correctly address the agent's goal.

Agent's Goal: {expected_info}

Tool Output (first 500 chars):
{tool_output_preview}

Direct Extraction Result:
{direct_result}

Generated Code:
{generated_code}

Code Execution Result:
{code_result}

Evaluate BOTH extraction methods:
1. Does the direct extraction provide what the agent needs?
2. Does the code output provide what the agent needs?
3. Are they complete and accurate?
4. Is the code output concise (not just returning all raw data)?
5. Could the code be improved to be more selective?

Respond with JSON:

{{
  "success": true or false,
  "reasoning": "which result is better and why, or what's wrong with both",
  "code_feedback": "if code needs improvement, specific suggestions (e.g., 'filter to only X field', 'limit to first N items', 'extract only Y property')",
  "issue": "if success=false, what's missing or wrong"
}}

Output ONLY valid JSON, no other text.
""".strip()


class DualPostProcessAgent(BaseAgent):
    """
    Post-processing agent that produces both direct extraction and code in ONE LLM call.

    Inherits from BaseAgent for automatic tracing integration.
    """

    config_class = DualPostProcessAgentConfig
    alias = ["dual_postprocess"]

    def __init__(
        self,
        llm: BaseLLM,
        safe_executor: SafeCodeExecutor,
        config: Optional[Union[DualPostProcessAgentConfig, Dict]] = None
    ):
        """
        Initialize DualPostProcessAgent.

        Args:
            llm: Language model for extraction.
            safe_executor: Safe code executor.
            config: Configuration dict or object.
        """
        if config is None:
            parsed_config = DualPostProcessAgentConfig()
        elif isinstance(config, DualPostProcessAgentConfig):
            parsed_config = config
        elif isinstance(config, dict):
            parsed_config = DualPostProcessAgentConfig(**config)
        else:
            parsed_config = None

        if parsed_config is not None:
            super().__init__(mcp_manager=None, llm=llm, config=None)
            self._config = parsed_config
            self._name = self._config.name if self._config.name else str(__import__('uuid').uuid4())
            self._config.name = self._name
        else:
            super().__init__(mcp_manager=None, llm=llm, config=config)

        self._safe_executor = safe_executor
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

        # Get model name for token counting
        self._model_name = "gpt-4"
        if hasattr(llm, 'config') and hasattr(llm.config, 'model_name'):
            self._model_name = llm.config.model_name

        self._max_tool_output_chars = self._config.max_tool_output_chars

        # Load custom prompt if provided in config, else use default
        if self._config.custom_prompt:
            self._extraction_prompt = self._config.custom_prompt
            self._logger.info("Using custom extraction prompt (%d chars)", len(self._extraction_prompt))
        else:
            self._extraction_prompt = DUAL_EXTRACTION_PROMPT
            self._logger.info("Using default DUAL_EXTRACTION_PROMPT")

    async def initialize(self, mcp_servers=None):
        """Initialize agent.

        Args:
            mcp_servers: Ignored (not needed for post-processor).
        """
        del mcp_servers  # Unused, but required for BaseAgent interface
        if self._initialized:
            return
        self._initialized = True

    async def cleanup(self):
        """Cleanup resources (no-op for post-processor)."""

    async def _execute(
        self,
        message: Union[str, List[str]],
        **kwargs
    ) -> AgentResponse:
        """
        Execute dual extraction (direct + code) in ONE LLM call.

        Message format is JSON string:
        {
            "tool_name": str,
            "tool_description": str,
            "tool_output": str,
            "expected_info": str
        }

        Returns:
            AgentResponse with both extraction results.
        """
        if isinstance(message, list):
            message = message[0] if message else "{}"

        try:
            input_data = json.loads(message)
        except json.JSONDecodeError:
            self._logger.error("Invalid JSON input: %s", message[:200])
            response_data = {
                "filtered_output": "ERROR: Invalid JSON input",
                "stats": {
                    "postprocessor_iterations": 0,
                    "original_chars": 0,
                    "filtered_chars": 0,
                    "chars_reduced": 0,
                    "original_tokens": 0,
                    "filtered_tokens": 0,
                    "tokens_reduced": 0,
                    "success": False,
                    "extraction_method": "dual",
                    "direct_attempts": 0,
                    "code_attempts": 0,
                },
            }
            return AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response=json.dumps(response_data),
                trace_id=""
            )

        tool_name = input_data.get("tool_name", "unknown_tool")
        tool_description = input_data.get("tool_description", "")
        tool_output = input_data.get("tool_output", "")
        expected_info = input_data.get("expected_info", "")

        tracer = kwargs.get("tracer", Tracer())

        # Truncate tool output if needed (keep original for stats)
        original_tool_output = tool_output
        if self._max_tool_output_chars and self._max_tool_output_chars > 0:
            tool_output = tool_output[:self._max_tool_output_chars]

        self._logger.info(
            "Processing tool=%s, output_length=%d (truncated from %d), expected_info=%s",
            tool_name, len(tool_output), len(original_tool_output), expected_info[:100]
        )

        stats = {
            "postprocessor_iterations": 0,
            "direct_attempts": 0,
            "code_attempts": 0
        }

        result = await self._extract_with_iterations(
            tool_name=tool_name,
            tool_description=tool_description,
            tool_output=tool_output,
            expected_info=expected_info,
            stats=stats,
            tracer=tracer
        )

        original_tokens = count_tokens(original_tool_output, model=self._model_name)
        filtered_tokens = count_tokens(result, model=self._model_name)

        postprocess_stats = PostProcessStats(
            postprocessor_iterations=stats["postprocessor_iterations"],
            original_chars=len(original_tool_output),
            filtered_chars=len(result),
            chars_reduced=len(original_tool_output) - len(result),
            original_tokens=original_tokens,
            filtered_tokens=filtered_tokens,
            tokens_reduced=original_tokens - filtered_tokens,
            success=bool(result and result.strip()),
            extraction_method="dual",
            direct_attempts=stats["direct_attempts"],
            code_attempts=stats["code_attempts"],
        )

        response_data = {
            "filtered_output": result,
            "stats": {
                "postprocessor_iterations": postprocess_stats.postprocessor_iterations,
                "original_chars": postprocess_stats.original_chars,
                "filtered_chars": postprocess_stats.filtered_chars,
                "chars_reduced": postprocess_stats.chars_reduced,
                "original_tokens": postprocess_stats.original_tokens,
                "filtered_tokens": postprocess_stats.filtered_tokens,
                "tokens_reduced": postprocess_stats.tokens_reduced,
                "success": postprocess_stats.success,
                "extraction_method": postprocess_stats.extraction_method,
                "direct_attempts": stats["direct_attempts"],
                "code_attempts": stats["code_attempts"],
            }
        }

        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=json.dumps(response_data),
            trace_id=tracer.trace_id
        )

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, str]]:
        """
        Parse LLM response and extract extraction data.

        Args:
            response: Raw LLM response string.

        Returns:
            Dict with direct_extraction, code, thought keys, or None if parsing fails.
        """
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            response_text = "\n".join(lines)

        extraction_data = json.loads(response_text)
        return {
            "direct_extraction": extraction_data.get("direct_extraction", ""),
            "code": extraction_data.get("code", ""),
            "thought": extraction_data.get("thought", "")
        }

    def _execute_extraction_code(self, code: str, tool_output: str) -> tuple[str, Optional[str]]:
        """
        Execute extraction code safely.

        Args:
            code: Python code to execute.
            tool_output: Tool output to process.

        Returns:
            Tuple of (result, error). If successful, error is None.
        """
        if not code:
            return "", None
        try:
            result = str(self._safe_executor.execute(code, tool_output))
            self._logger.info("Code executed successfully: %d chars", len(result))
            return result, None
        except Exception as e:  # pylint: disable=broad-exception-caught
            error = str(e)
            self._logger.error("Code execution exception: %s", error)
            return "", error

    def _validate_output_sizes(
        self,
        tool_output: str,
        direct_extraction: str,
        code_result: str
    ) -> Dict[str, Any]:
        """
        Validate output sizes against token limits.

        Args:
            tool_output: Original tool output.
            direct_extraction: Direct extraction result.
            code_result: Code execution result.

        Returns:
            Dict with validation results including token counts and flags.
        """
        input_tokens = count_tokens(tool_output, model=self._model_name)
        direct_tokens = count_tokens(direct_extraction, model=self._model_name)
        code_tokens = count_tokens(code_result, model=self._model_name)
        max_allowed = int(input_tokens * 0.5)

        return {
            "input_tokens": input_tokens,
            "direct_tokens": direct_tokens,
            "code_tokens": code_tokens,
            "max_allowed": max_allowed,
            "direct_too_large": direct_tokens > max_allowed,
            "code_too_large": code_tokens > max_allowed
        }

    async def _extract_with_iterations(
        self,
        tool_name: str,
        tool_description: str,
        tool_output: str,
        expected_info: str,
        stats: Dict[str, Any],
        tracer
    ) -> str:
        """
        Run dual extraction with iteration support.

        Iterates only if:
        - Both outputs are empty
        - Code execution fails

        Args:
            tool_name: Name of the tool.
            tool_description: Description of the tool.
            tool_output: Output from the tool.
            expected_info: What the agent expects to extract.
            stats: Statistics dict to update.
            tracer: Tracer for logging.

        Returns:
            Formatted string with both extraction results.
        """
        iteration_history: List[Dict] = []
        best_direct, best_code, best_code_error = "", "", None

        for iteration in range(self._config.max_iterations):
            stats["postprocessor_iterations"] = iteration + 1
            stats["direct_attempts"] += 1
            stats["code_attempts"] += 1

            self._logger.info(
                "Dual extraction attempt %d/%d", iteration + 1, self._config.max_iterations
            )

            prompt = self._build_prompt(
                tool_name, tool_description, tool_output, expected_info, iteration_history, iteration
            )
            self._logger.info("%s", prompt)

            # Call LLM and parse response
            extraction_data = await self._call_llm_for_extraction(
                prompt, iteration, iteration_history, tracer
            )
            if extraction_data is None:
                continue

            direct_extraction = extraction_data["direct_extraction"]
            code = extraction_data["code"]

            # Execute code
            code_result, code_error = self._execute_extraction_code(code, tool_output)

            # Track results
            has_direct = bool(direct_extraction and direct_extraction.strip())
            has_code = bool(code_result and code_result.strip())

            if has_direct:
                best_direct = direct_extraction
            if has_code:
                best_code = code_result
                best_code_error = None
            elif code_error and not best_code:
                best_code_error = code_error

            iteration_history.append({
                "iteration": iteration + 1,
                "direct": direct_extraction,
                "code": code,
                "code_result": code_result,
                "error": code_error
            })

            # Check if we have valid outputs
            if has_direct and has_code:
                result = await self._process_successful_extraction(
                    tool_output, expected_info, direct_extraction, code, code_result,
                    iteration, iteration_history, tracer
                )
                if result is not None:
                    return result
                continue

            # Log why we're retrying
            self._log_retry_reason(iteration, has_direct, has_code, code_error)

        # Return best partial results or original
        return self._finalize_extraction(tool_output, best_direct, best_code, best_code_error)

    async def _call_llm_for_extraction(
        self,
        prompt: str,
        iteration: int,
        iteration_history: List[Dict],
        tracer
    ) -> Optional[Dict[str, str]]:
        """Call LLM and return parsed extraction data, or None on failure."""
        try:
            response = await self._llm.generate_async(
                messages=[{"role": "user", "content": prompt}],
                tracer=tracer,
                timeout=self._config.execution_timeout
            )
            extraction_data = self._parse_llm_response(response)
            thought = extraction_data.get("thought", "")
            if thought:
                self._logger.info("Postprocessor thought: %s", thought)
            else:
                self._logger.info("LLM response: %s", response[:200])
            return extraction_data

        except json.JSONDecodeError as e:
            self._logger.error("Invalid JSON from LLM: %s", str(e))
            iteration_history.append({
                "iteration": iteration + 1,
                "direct": "", "code": "", "code_result": "",
                "error": f"Invalid JSON response: {str(e)}"
            })
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = str(e)
            self._logger.error("LLM call failed: %s", error_msg)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                self._logger.warning("LLM timeout on iteration %d, retrying...", iteration + 1)
            else:
                iteration_history.append({
                    "iteration": iteration + 1,
                    "direct": "", "code": "", "code_result": "",
                    "error": f"LLM error: {error_msg}"
                })
            return None

    async def _process_successful_extraction(
        self,
        tool_output: str,
        expected_info: str,
        direct_extraction: str,
        code: str,
        code_result: str,
        iteration: int,
        iteration_history: List[Dict],
        tracer
    ) -> Optional[str]:
        """
        Process successful extraction results with size validation.

        Returns formatted output if valid, None if should retry.
        """
        sizes = self._validate_output_sizes(tool_output, direct_extraction, code_result)

        # Both too large
        if sizes["direct_too_large"] and sizes["code_too_large"]:
            return self._handle_both_too_large(
                tool_output, direct_extraction, code_result, sizes, iteration, iteration_history
            )

        use_direct = not sizes["direct_too_large"]
        use_code = not sizes["code_too_large"]

        self._log_size_warnings(sizes, use_direct, use_code)

        if not use_direct and not use_code:
            self._logger.error("Both outputs excluded due to size, this shouldn't happen")
            return None if iteration < self._config.max_iterations - 1 else tool_output

        # Reflection check
        if self._config.enable_reflection and iteration < self._config.max_iterations - 1:
            should_retry, feedback = await self._should_retry_with_reflection(
                tool_output, expected_info,
                direct_extraction if use_direct else "",
                code, code_result if use_code else "", tracer
            )
            if should_retry:
                if feedback:
                    iteration_history[-1]["error"] = feedback
                self._logger.info("Reflection suggests retry")
                return None

        self._log_success(use_direct, use_code)
        return self._format_output(
            direct_extraction if use_direct else "",
            code_result if use_code else "",
            None
        )

    def _handle_both_too_large(
        self,
        tool_output: str,
        direct_extraction: str,
        code_result: str,
        sizes: Dict[str, Any],
        iteration: int,
        iteration_history: List[Dict]
    ) -> Optional[str]:
        """Handle case where both outputs exceed size limits."""
        if iteration < self._config.max_iterations - 1:
            self._logger.warning(
                "Both outputs too large: direct=%d tokens, code=%d tokens "
                "(input: %d, max allowed: %d). Retrying...",
                sizes["direct_tokens"], sizes["code_tokens"],
                sizes["input_tokens"], sizes["max_allowed"]
            )
            iteration_history[-1]["error"] = (
                f"Both direct extraction ({sizes['direct_tokens']} tokens) and code output "
                f"({sizes['code_tokens']} tokens) exceed max allowed ({sizes['max_allowed']} tokens). "
                "Generate more concise extraction and code."
            )
            return None

        self._logger.warning(
            "Last iteration: both outputs too large (direct=%d, code=%d, max=%d). "
            "Comparing filtered vs original size...",
            sizes["direct_tokens"], sizes["code_tokens"], sizes["max_allowed"]
        )
        filtered_output = self._format_output(direct_extraction, code_result, None)
        filtered_tokens = count_tokens(filtered_output, model=self._model_name)

        if filtered_tokens < sizes["input_tokens"]:
            self._logger.info(
                "Filtered output (%d tokens) smaller than original (%d tokens), using filtered",
                filtered_tokens, sizes["input_tokens"]
            )
            return filtered_output

        self._logger.warning(
            "Filtered output (%d tokens) larger than original (%d tokens), returning original",
            filtered_tokens, sizes["input_tokens"]
        )
        return tool_output

    def _log_size_warnings(self, sizes: Dict[str, Any], use_direct: bool, use_code: bool) -> None:
        """Log warnings about excluded outputs due to size."""
        if not use_direct and sizes["direct_too_large"]:
            self._logger.warning(
                "Direct extraction too large (%d tokens > %d allowed), excluding from output",
                sizes["direct_tokens"], sizes["max_allowed"]
            )
        if not use_code and sizes["code_too_large"]:
            self._logger.warning(
                "Code output too large (%d tokens > %d allowed), excluding from output",
                sizes["code_tokens"], sizes["max_allowed"]
            )

    def _log_success(self, use_direct: bool, use_code: bool) -> None:
        """Log success message based on which methods were used."""
        if use_direct and use_code:
            self._logger.info("Both extraction methods succeeded and passed size check")
        elif use_direct:
            self._logger.info("Direct extraction succeeded (code output excluded due to size)")
        else:
            self._logger.info("Code extraction succeeded (direct extraction excluded due to size)")

    def _log_retry_reason(
        self, iteration: int, has_direct: bool, has_code: bool, code_error: Optional[str]
    ) -> None:
        """Log reason for retrying extraction."""
        if not has_direct and not has_code:
            self._logger.warning("Iteration %d: both outputs empty, retrying...", iteration + 1)
        elif not has_direct:
            self._logger.warning("Iteration %d: direct extraction empty, retrying...", iteration + 1)
        elif not has_code:
            self._logger.warning(
                "Iteration %d: code execution failed (%s), retrying...",
                iteration + 1, code_error or "empty result"
            )

    def _finalize_extraction(
        self,
        tool_output: str,
        best_direct: str,
        best_code: str,
        best_code_error: Optional[str]
    ) -> str:
        """Return final extraction result after all iterations."""
        if best_direct or best_code:
            self._logger.warning(
                "All %d iterations exhausted. Returning best partial results: direct=%s, code=%s",
                self._config.max_iterations,
                "yes" if best_direct else "no",
                "yes" if best_code else "no"
            )
            return self._format_output(
                best_direct, best_code, best_code_error if not best_code else None
            )

        self._logger.error(
            "All %d iterations exhausted with no valid results from either method. "
            "Returning original tool output.",
            self._config.max_iterations
        )
        return tool_output

    def _build_prompt(
        self,
        tool_name: str,
        tool_description: str,
        tool_output: str,
        expected_info: str,
        iteration_history: List[Dict],
        iteration: int
    ) -> str:
        """Build the extraction prompt."""
        if tool_description:
            tool_description_section = f"Description: {tool_description}"
        else:
            tool_description_section = ""

        if iteration_history:
            history_lines = ["\nPREVIOUS ATTEMPTS:"]
            for hist in iteration_history:
                history_lines.append(f"\nAttempt {hist['iteration']}:")
                if hist.get("error"):
                    history_lines.append(f"  Error: {hist['error']}")
                if hist.get("direct"):
                    history_lines.append(f"  Direct: {hist['direct'][:100]}...")
                if hist.get("code"):
                    history_lines.append(f"  Code: {hist['code'][:100]}...")
                if hist.get("code_result"):
                    history_lines.append(f"  Result: {hist['code_result'][:100]}...")
            iteration_history_section = "\n".join(history_lines)
        else:
            iteration_history_section = ""

        if iteration > 0:
            iteration_instruction_section = "\nIMPORTANT: Previous attempt(s) failed. Try a different approach."
        else:
            iteration_instruction_section = ""

        return self._extraction_prompt.format(
            tool_name=tool_name,
            tool_description_section=tool_description_section,
            tool_output=tool_output,
            output_length=len(tool_output),
            expected_info=expected_info,
            iteration_history_section=iteration_history_section,
            iteration_instruction_section=iteration_instruction_section
        )

    async def _should_retry_with_reflection(
        self,
        tool_output: str,
        expected_info: str,
        direct_result: str,
        generated_code: str,
        code_result: str,
        tracer
    ) -> tuple[bool, Optional[str]]:
        """
        Use LLM to evaluate if results are satisfactory.

        Returns:
            Tuple of (should_retry, feedback_message):
            - should_retry: True if reflection suggests retry
            - feedback_message: Combined feedback to include in iteration history
        """
        try:
            reflection_prompt = REFLECTION_PROMPT.format(
                expected_info=expected_info,
                tool_output_preview=tool_output[:500],
                direct_result=direct_result,
                generated_code=generated_code,
                code_result=code_result
            )

            response = await self._llm.generate_async(
                messages=[{"role": "user", "content": reflection_prompt}],
                tracer=tracer,
                timeout=self._config.execution_timeout
            )
            reflection = json.loads(response)

            success = reflection.get("success", False)
            reasoning = reflection.get("reasoning", "")
            code_feedback = reflection.get("code_feedback", "")
            issue = reflection.get("issue", "")

            self._logger.info("Reflection: success=%s, reasoning=%s", success, reasoning)
            if code_feedback:
                self._logger.info("Code feedback: %s", code_feedback)

            feedback_parts = []
            if not success:
                feedback_parts.append(f"Reflection failed: {reasoning}")
                if issue:
                    feedback_parts.append(f"Issue: {issue}")
            if code_feedback:
                feedback_parts.append(f"Code feedback: {code_feedback}")

            feedback_message = " | ".join(feedback_parts) if feedback_parts else None

            return not success, feedback_message

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Reflection failed: %s", str(e))
            return False, None

    def _format_output(
        self,
        direct_extraction: str,
        code_result: str,
        code_error: Optional[str]
    ) -> str:
        """Format the final output with both results."""
        lines = []
        lines.append("=" * 80)
        lines.append("DUAL EXTRACTION RESULTS")
        lines.append("=" * 80)
        lines.append("")
        lines.append("Two extraction methods were used. You can use either result,")
        lines.append("or combine information from both as appropriate.")
        lines.append("")

        lines.append("-" * 80)
        lines.append("DIRECT EXTRACTION:")
        lines.append("-" * 80)
        if direct_extraction:
            lines.append(direct_extraction)
        else:
            lines.append("(No output)")
        lines.append("")

        lines.append("-" * 80)
        lines.append("CODE-BASED EXTRACTION:")
        lines.append("-" * 80)
        if code_error:
            lines.append(f"ERROR: {code_error}")
        elif code_result:
            lines.append(code_result)
        else:
            lines.append("(No output)")
        lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)
