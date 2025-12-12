"""
Post-process agent for filtering structured tool outputs.

This agent generates Python code to filter and extract relevant information
from long structured tool outputs based on expected information.
"""
# pylint: disable=broad-exception-caught
import json
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime
from dataclasses import dataclass, field

from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.agent.base import BaseAgentConfig, BaseAgent
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.tracer import Tracer
from mcpuniverse.mcpplus.mcp.wrapper_manager import SafeCodeExecutor


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for.
        model: Model name for tokenizer (default: gpt-4).

    Returns:
        Number of tokens in the text.
    """
    try:
        import tiktoken
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception:
        # Fallback: rough approximation (4 chars per token)
        return len(text) // 4


@dataclass
class PostProcessStats:
    """
    Statistics from post-processing a single tool output.

    Attributes:
        postprocessor_iterations: Number of ReAct iterations taken.
        original_chars: Character count of original tool output.
        filtered_chars: Character count of filtered output.
        chars_reduced: Number of characters reduced (original - filtered).
        original_tokens: Token count of original tool output.
        filtered_tokens: Token count of filtered output.
        tokens_reduced: Number of tokens reduced (original - filtered).
        postprocessor_llm_tokens: Total tokens used by LLM during post-processing.
        success: Whether post-processing succeeded.
        extraction_method: Method used for final successful extraction ("direct" or "code").
        direct_attempts: Number of direct extraction attempts.
        code_attempts: Number of code generation attempts.
    """
    postprocessor_iterations: int = 0
    original_chars: int = 0
    filtered_chars: int = 0
    chars_reduced: int = 0
    original_tokens: int = 0
    filtered_tokens: int = 0
    tokens_reduced: int = 0
    postprocessor_llm_tokens: int = 0
    success: bool = True
    extraction_method: str = "unknown"
    direct_attempts: int = 0
    code_attempts: int = 0


@dataclass
class PostProcessAgentConfig(BaseAgentConfig):
    """
    Configuration for PostProcessAgent.

    Extends BaseAgentConfig with post-processing specific parameters.

    Attributes:
        enable_memory: Enable session memory for code reuse across similar queries.
        max_iterations: Maximum ReAct-style refinement iterations (default: 3).
        enable_reflection: Enable LLM-based reflection on output quality.
        max_tool_output_chars: Maximum characters of tool output to show to LLM.
            If None or 0, shows entire output. Default is 2000.
    """
    enable_memory: bool = True
    max_iterations: int = 3
    enable_reflection: bool = True
    max_tool_output_chars: Optional[int] = 2000


FILTER_CODE_GENERATION_PROMPT = """
You are a code generation assistant. Your task is to write Python code that extracts specific information from tool output based on the agent's stated goal.

Tool: {tool_name}
{tool_description_section}

Tool Output{tool_output_size_info}:
{tool_output_preview}

Agent's Goal: {expected_info}

{memory_section}

{iteration_history_section}

Your task is to analyze whether post-processing is needed and generate appropriate Python code.

DECISION FRAMEWORK:
1. If the agent explicitly states "all information is needed" or similar → Set result = data (no filtering)
2. If the tool output is small/simple and already matches what's needed → Set result = data (no filtering)
3. If specific information needs to be extracted from large/complex output → Write extraction code
4. If the agent's goal is vague or unclear → Set result = data (preserve all information when in doubt)

CODE GENERATION GUIDELINES:
- The input will be available as the variable `data` (always a string)
- Store the result in a variable called `result`
- Handle different data formats: JSON, HTML, plain text, XML, etc.
- If extraction is needed, be precise: extract ONLY what matches the agent's goal
- Keep code concise but readable
- Use any Python libraries you need for the task (json, re, datetime, BeautifulSoup, etc.)
- AVOID dangerous operations: no eval, exec, open, file operations, network calls, or system commands
- Include error handling (try/except) for parsing operations
- If extraction fails, the specific error should be clearly communicated. Do not simply return the original data
  without change.

EXAMPLES:

Example 1 - Extract specific field from JSON:
Agent's Goal: "The status field from the API response, needed to determine if the operation succeeded"
```python
import json
try:
    parsed = json.loads(data)
    result = str(parsed.get('status', 'Status not found'))
except json.JSONDecodeError as e:
    result = f'JSONDecodeError was raised: {{e}}'
except Exception as e:
    result = f'Exception raised: {{e}}'
```

Example 2 - Extract list items from JSON:
Agent's Goal: "List of IDs from the items array, needed to make subsequent API calls for each item"
```python
import json
try:
    parsed = json.loads(data)
    items = parsed.get('items', [])
    ids = [str(item.get('id', '')) for item in items if 'id' in item]
    result = "\\n".join(ids) if ids else "No IDs found"
except json.JSONDecodeError as e:
    result = f'JSONDecodeError was raised: {{e}}'
except Exception as e:
    result = f'Exception raised: {{e}}'
```

IMPORTANT: When in doubt about what to extract, prefer returning the original data (result = data) rather than
accidentally filtering out important information.

{iteration_instruction_section}

Output ONLY the Python code, no explanations. The code should be executable as-is.
""".strip()


REFLECTION_PROMPT = """
You are evaluating whether a filtered output correctly addresses the agent's stated goal.

Agent's Goal: {expected_info}

Tool Output (original, first 500 chars):
{tool_output_preview}

Filtered Output (what the code produced):
{filtered_output}

Your task: Determine if the filtered output successfully extracts what the agent needs.

Evaluation criteria:
1. Does it contain the information described in the agent's goal?
2. Is the information accurate and properly extracted?
3. Is it concise while still being complete?
4. If the goal was vague (e.g., "all information is needed"), is returning the full output appropriate?

Respond with a JSON object:
{{
  "success": true or false,
  "reasoning": "brief explanation of why it succeeds or fails",
  "issue": "if success=false, what specific information is missing or wrong"
}}

Output ONLY valid JSON, no other text.
""".strip()


class PostProcessAgent(BaseAgent):
    """
    Post-processing agent that generates and executes filter code.

    This agent maintains session memory to reuse successful filter code
    for similar queries within the same session.

    Inherits from BaseAgent for automatic tracing integration.
    """

    config_class = PostProcessAgentConfig
    alias = ["postprocess"]

    def __init__(
        self,
        llm: BaseLLM,
        safe_executor: SafeCodeExecutor,
        config: Optional[Union[Dict, str]] = None
    ):
        """
        Initialize the post-process agent.

        Args:
            llm: Language model for code generation.
            safe_executor: Safe code executor with restrictions.
            config: Configuration dict or JSON string with PostProcessAgentConfig fields.
        """
        # Initialize BaseAgent (mcp_manager not needed for post-processor)
        super().__init__(mcp_manager=None, llm=llm, config=config)

        self._safe_executor = safe_executor
        self._session_memory: List[Dict[str, Any]] = []
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

        # Get model name for accurate token counting
        self._model_name = "gpt-4"  # Default fallback
        if hasattr(llm, 'config') and hasattr(llm.config, 'model_name'):
            self._model_name = llm.config.model_name
            self._logger.debug("Using tokenizer for model: %s", self._model_name)

        # Config shortcuts for convenience
        self._enable_memory = self._config.enable_memory
        self._max_iterations = self._config.max_iterations
        self._enable_reflection = self._config.enable_reflection
        self._max_tool_output_chars = self._config.max_tool_output_chars

    async def initialize(self, mcp_servers=None):
        """
        Initialize the post-processor.

        PostProcessAgent doesn't need MCP servers, so this just marks as initialized.

        Args:
            mcp_servers: Ignored (not needed for post-processor).
        """
        if self._initialized:
            return
        # No MCP setup needed for post-processor
        self._initialized = True

    async def cleanup(self):
        """Cleanup resources (no-op for post-processor)."""
        pass

    async def _execute(
        self,
        message: Union[str, List[str]],
        **kwargs
    ) -> AgentResponse:
        """
        Execute post-processing via BaseAgent interface.

        Message format is JSON string with fields:
        {
            "tool_output": str,
            "expected_info": str,
            "tool_name": str,
            "tool_description": Optional[str]
        }

        Args:
            message: JSON string or list with post-processing parameters.
            **kwargs: Additional arguments including tracer and callbacks.

        Returns:
            AgentResponse with filtered output and statistics.
        """
        # Parse message
        if isinstance(message, (list, tuple)):
            message = message[0]

        try:
            params = json.loads(message)
        except json.JSONDecodeError as e:
            self._logger.error("Failed to parse message as JSON: %s", str(e))
            raise ValueError(f"Message must be valid JSON: {str(e)}") from e

        # Extract parameters
        tool_output = params.get("tool_output", "")
        expected_info = params.get("expected_info", "")
        tool_name = params.get("tool_name", "unknown")
        tool_description = params.get("tool_description")

        # Get tracer from kwargs (BaseAgent.execute will pass it)
        tracer = kwargs.get("tracer", Tracer())

        # Call internal process method with tracing
        filtered_output, stats = await self._process_internal(
            tool_output=tool_output,
            expected_info=expected_info,
            tool_name=tool_name,
            tool_description=tool_description,
            tracer=tracer
        )

        # Return AgentResponse with results
        # Encode stats as JSON in response
        response_data = {
            "filtered_output": filtered_output,
            "stats": {
                "postprocessor_iterations": stats.postprocessor_iterations,
                "original_chars": stats.original_chars,
                "filtered_chars": stats.filtered_chars,
                "chars_reduced": stats.chars_reduced,
                "original_tokens": stats.original_tokens,
                "filtered_tokens": stats.filtered_tokens,
                "tokens_reduced": stats.tokens_reduced,
                "success": stats.success
            }
        }

        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=json.dumps(response_data),
            trace_id=tracer.trace_id
        )

    async def _process_internal(
        self,
        tool_output: str,
        expected_info: str,
        tool_name: str,
        tool_description: Optional[str] = None,
        tracer: Optional[Tracer] = None
    ) -> Tuple[str, PostProcessStats]:
        """
        Internal processing method that uses BaseAgent's LLM calls with tracing.

        This method replaces direct _llm.generate_async() calls with traced calls.

        Args:
            tool_output: Raw tool output to filter.
            expected_info: Description of expected information.
            tool_name: Name of the tool that produced the output.
            tool_description: Optional description of what the tool does.
            tracer: Tracer for logging execution (passed from _execute).

        Returns:
            Tuple of (filtered output string, PostProcessStats with metrics).
        """
        # This method will contain the same logic as the old process() method,
        # but will use the tracer parameter for LLM calls
        # For now, call the existing process method (will refactor LLM calls next)
        return await self.process(
            tool_output=tool_output,
            expected_info=expected_info,
            tool_name=tool_name,
            tool_description=tool_description,
            tracer=tracer
        )

    async def process(
        self,
        tool_output: str,
        expected_info: str,
        tool_name: str,
        tool_description: Optional[str] = None,
        tracer=None
    ) -> Tuple[str, PostProcessStats]:
        """
        Process tool output using ReAct-style iterative refinement.

        This method:
        1. Checks session memory for existing successful code
        2. If not cached, enters ReAct loop:
           - Iteration 1: Generate initial code (Thought → Action)
           - Observe: Execute code, check result
           - Iterations 2-N: Refine based on feedback (Thought → Action → Observation)
        3. Returns best successful result with statistics

        Args:
            tool_output: Raw tool output to filter.
            expected_info: Description of expected information.
            tool_name: Name of the tool that produced the output.
            tool_description: Optional description of what the tool does.
            tracer: Optional tracer for logging execution.

        Returns:
            Tuple of (filtered output string, PostProcessStats with metrics).

        Raises:
            Exception: If all iterations fail to produce working code.
        """
        # Single clean INFO log at start
        self._logger.info("Processing %s (%d chars)...", tool_name, len(tool_output))

        # Initialize statistics
        original_tokens = count_tokens(tool_output, model=self._model_name)
        original_chars = len(tool_output)

        # Step 1: Check cache
        cached_code = self._find_in_memory(tool_name, expected_info)
        if cached_code:
            self._logger.debug("Found cached code in session memory, reusing")
            try:
                success, result, error = await self._execute_and_evaluate(cached_code, tool_output)
                if success:
                    self._logger.debug("Cached code executed successfully")
                    # Calculate stats for cached result
                    filtered_tokens = count_tokens(result, model=self._model_name)
                    filtered_chars = len(result)
                    stats = PostProcessStats(
                        postprocessor_iterations=0,  # Cached, no new iterations
                        original_chars=original_chars,
                        filtered_chars=filtered_chars,
                        chars_reduced=original_chars - filtered_chars,
                        original_tokens=original_tokens,
                        filtered_tokens=filtered_tokens,
                        tokens_reduced=original_tokens - filtered_tokens,
                        postprocessor_llm_tokens=0,  # No LLM calls for cached result
                        success=True
                    )
                    return result, stats
                else:
                    self._logger.warning(
                        "Cached code failed: %s. Falling back to ReAct loop", error
                    )
            except Exception as e:
                self._logger.warning(
                    "Cached code execution failed: %s. Falling back to ReAct loop", str(e)
                )

        # Step 2: ReAct loop
        self._logger.debug("Starting ReAct loop with max_iterations=%d", self._max_iterations)

        iteration_history = []
        successful_result = None
        successful_code = None
        iterations_taken = 0

        for iteration in range(1, self._max_iterations + 1):
            iterations_taken = iteration
            self._logger.debug("Iteration %d/%d", iteration, self._max_iterations)

            # Thought + Action: Generate/refine code
            self._logger.debug("Generating filter code via LLM...")
            filter_code = await self.generate_filter_code(
                tool_output=tool_output,
                expected_info=expected_info,
                tool_name=tool_name,
                tool_description=tool_description,
                iteration=iteration,
                iteration_history=iteration_history,
                tracer=tracer
            )

            self._logger.debug("Generated code:\n%s", filter_code)

            # Observation 1: Execute and evaluate
            self._logger.debug("Executing generated code...")
            execution_success, result, execution_error = await self._execute_and_evaluate(
                filter_code, tool_output
            )

            if not execution_success:
                # Code has bugs - record and continue
                iteration_entry = {
                    "iteration": iteration,
                    "code": filter_code,
                    "execution_success": False,
                    "result": None,
                    "execution_error": execution_error,
                    "quality_ok": False,
                    "quality_reasoning": None
                }
                iteration_history.append(iteration_entry)

                self._logger.warning(
                    "Iteration %d EXECUTION FAILED: %s",
                    iteration, execution_error
                )
                continue

            # Observation 2: Reflect on output quality (if enabled)
            if self._enable_reflection:
                self._logger.debug("Code executed successfully. Reflecting on output quality...")
                quality_ok, quality_reasoning = await self._evaluate_output_quality(
                    filtered_output=result,
                    tool_output=tool_output,
                    expected_info=expected_info,
                    tracer=tracer
                )
            else:
                # Skip reflection - assume execution success is sufficient
                quality_ok = True
                quality_reasoning = "Reflection disabled, assuming execution success is sufficient"

            # Record iteration with both execution and quality results
            iteration_entry = {
                "iteration": iteration,
                "code": filter_code,
                "execution_success": True,
                "result": result,
                "execution_error": None,
                "quality_ok": quality_ok,
                "quality_reasoning": quality_reasoning
            }
            iteration_history.append(iteration_entry)

            if quality_ok:
                # Both execution and quality passed!
                successful_result = result
                successful_code = filter_code
                self._logger.debug("Iteration %d SUCCESS", iteration)
                self._logger.debug("Quality check: %s", quality_reasoning)
                break
            else:
                # Code runs but output doesn't meet the goal
                self._logger.warning(
                    "Iteration %d: Code executes but output quality insufficient",
                    iteration
                )
                self._logger.warning("Quality issue: %s", quality_reasoning)

        # Step 3: Handle final result
        if successful_result is not None:
            # Add to memory with iteration count
            self._add_to_memory(
                tool_name=tool_name,
                expected_info=expected_info,
                filter_code=successful_code,
                success=True,
                error=None,
                output_length=len(tool_output),
                filtered_length=len(successful_result),
                iterations_taken=iterations_taken
            )

            # Clean INFO log at end with stats
            reduction_pct = round((original_chars - len(successful_result)) / original_chars * 100) if original_chars > 0 else 0
            self._logger.info(
                "Done: %d -> %d chars (%d%% reduced, %d iteration%s)",
                original_chars, len(successful_result), reduction_pct,
                iterations_taken, "s" if iterations_taken > 1 else ""
            )

            # Calculate final statistics
            filtered_tokens = count_tokens(successful_result, model=self._model_name)
            filtered_chars = len(successful_result)
            stats = PostProcessStats(
                postprocessor_iterations=iterations_taken,
                original_chars=original_chars,
                filtered_chars=filtered_chars,
                chars_reduced=original_chars - filtered_chars,
                original_tokens=original_tokens,
                filtered_tokens=filtered_tokens,
                tokens_reduced=original_tokens - filtered_tokens,
                postprocessor_llm_tokens=0,
                success=True
            )
            return successful_result, stats
        else:
            # All iterations failed
            # Add last attempt to memory as failure
            last_entry = iteration_history[-1] if iteration_history else None
            if last_entry:
                self._add_to_memory(
                    tool_name=tool_name,
                    expected_info=expected_info,
                    filter_code=last_entry['code'],
                    success=False,
                    error=last_entry['execution_error'],
                    output_length=len(tool_output),
                    filtered_length=0,
                    iterations_taken=iterations_taken
                )

            error_msg = f"Failed to generate working code after {iterations_taken} iterations"
            self._logger.error(error_msg)
            self._logger.warning("Returning original tool output after all iterations failed")

            # Return original output with failure stats
            stats = PostProcessStats(
                postprocessor_iterations=iterations_taken,
                original_chars=original_chars,
                filtered_chars=original_chars,  # No filtering occurred
                chars_reduced=0,
                original_tokens=original_tokens,
                filtered_tokens=original_tokens,  # No filtering occurred
                tokens_reduced=0,
                postprocessor_llm_tokens=0,
                success=False
            )
            return tool_output, stats

    async def generate_filter_code(
        self,
        tool_output: str,
        expected_info: str,
        tool_name: str,
        tool_description: Optional[str] = None,
        iteration: int = 1,
        iteration_history: Optional[List[Dict]] = None,
        tracer: Optional[Tracer] = None
    ) -> str:
        """
        Generate Python filter code using LLM.

        Args:
            tool_output: Raw tool output (will be truncated for prompt).
            expected_info: Description of expected information.
            tool_name: Name of the tool.
            tool_description: Optional description of what the tool does.
            iteration: Current iteration number (1-indexed).
            iteration_history: History of previous iteration attempts.
            tracer: Optional tracer for logging execution.

        Returns:
            Generated Python code as string.
        """
        # Truncate output for prompt based on configuration
        if self._max_tool_output_chars is None or self._max_tool_output_chars <= 0:
            tool_output_preview = tool_output
            tool_output_size_info = f" (complete, {len(tool_output)} chars)"
            self._logger.debug("Showing entire tool output to LLM (%d chars)", len(tool_output))
        else:
            if len(tool_output) > self._max_tool_output_chars:
                half_budget = self._max_tool_output_chars // 2
                first_part = tool_output[:half_budget]
                last_part = tool_output[-half_budget:]
                omitted_chars = len(tool_output) - (half_budget * 2)

                tool_output_preview = (
                    f"{first_part}\n"
                    f"... [TRUNCATED: {omitted_chars} characters omitted from middle] ...\n"
                    f"{last_part}"
                )
                tool_output_size_info = (
                    f" (first {half_budget} and last {half_budget} chars of {len(tool_output)} total)"
                )
                self._logger.debug(
                    "Truncated tool output: showing first %d + last %d of %d chars",
                    half_budget, half_budget, len(tool_output)
                )
            else:
                tool_output_preview = tool_output
                tool_output_size_info = f" (complete, {len(tool_output)} chars)"

        # Escape curly braces in dynamic content
        tool_output_preview = tool_output_preview.replace('{', '{{').replace('}', '}}')
        expected_info_escaped = expected_info.replace('{', '{{').replace('}', '}}')
        tool_name_escaped = tool_name.replace('{', '{{').replace('}', '}}')

        # Build tool description section
        tool_description_section = ""
        if tool_description:
            tool_description_escaped = tool_description.replace('{', '{{').replace('}', '}}')
            tool_description_section = f"Tool Description: {tool_description_escaped}\n"

        # Build memory section with relevant past examples
        memory_section = self._build_memory_section(tool_name)

        # Build iteration history section
        iteration_history_section = ""
        if iteration > 1 and iteration_history:
            iteration_history_section = self._format_iteration_history(iteration_history)

        # Build iteration instruction section
        if iteration == 1:
            iteration_instruction_section = f"\nThis is iteration 1 of {self._max_iterations}. Generate your best initial solution."
        else:
            attempts_remaining = self._max_iterations - iteration + 1
            iteration_instruction_section = f"""
This is iteration {iteration} of {self._max_iterations}.
You have {attempts_remaining} attempts remaining.

CRITICAL: Review the previous attempts above. Identify what went wrong:
- Was it a KeyError, AttributeError, or TypeError?
- Was the regex pattern incorrect?
- Was the data structure different than assumed?
- Did the result not match the agent's goal?

Generate CORRECTED code that fixes these specific issues.
""".strip()

        # Build prompt
        prompt = FILTER_CODE_GENERATION_PROMPT.format(
            tool_name=tool_name_escaped,
            tool_description_section=tool_description_section,
            expected_info=expected_info_escaped,
            tool_output_preview=tool_output_preview,
            tool_output_size_info=tool_output_size_info,
            memory_section=memory_section,
            iteration_history_section=iteration_history_section,
            iteration_instruction_section=iteration_instruction_section
        )
        self._logger.debug("Full code generation prompt:\n%s", prompt)

        # Generate code via LLM with tracing
        response = await self._llm.generate_async(
            messages=[{"role": "user", "content": prompt}],
            tracer=tracer or Tracer()
        )

        # Clean up response (remove markdown code blocks if present)
        code = response.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        self._logger.debug("Generated filter code:\n%s", code)

        return code

    def _build_memory_section(self, tool_name: str) -> str:
        """Build memory section showing relevant past examples."""
        if not self._enable_memory or not self._session_memory:
            return ""

        relevant_entries = [
            entry for entry in self._session_memory
            if entry["tool_name"] == tool_name
        ]

        if not relevant_entries:
            return ""

        successful = [e for e in relevant_entries if e["success"]]
        failed = [e for e in relevant_entries if not e["success"]]

        memory_lines = ["\nPrevious Examples (for reference):"]

        if successful:
            memory_lines.append("\nSuccessful Examples:")
            for i, entry in enumerate(reversed(successful[-3:]), 1):
                iterations = entry.get('iterations_taken', 1)
                memory_lines.append(f"\n  Example {i} (solved in {iterations} iteration(s)):")
                memory_lines.append(f"    Expected Info: {entry['expected_info']}")
                memory_lines.append(f"    Code Used:")
                code_lines = entry['filter_code'].split('\n')
                for line in code_lines:
                    memory_lines.append(f"      {line}")
                memory_lines.append(f"    Result: Reduced from {entry['output_length']} to {entry['filtered_length']} chars")

        if failed:
            memory_lines.append("\nFailed Examples (avoid these patterns):")
            for i, entry in enumerate(reversed(failed[-2:]), 1):
                memory_lines.append(f"\n  Failed Example {i}:")
                memory_lines.append(f"    Expected Info: {entry['expected_info']}")
                memory_lines.append(f"    Code Attempted:")
                code_lines = entry['filter_code'].split('\n')
                for line in code_lines:
                    memory_lines.append(f"      {line}")
                memory_lines.append(f"    Error: {entry['error']}")

        return "\n".join(memory_lines)

    def _format_iteration_history(self, history: List[Dict]) -> str:
        """Format iteration history for prompt inclusion."""
        if not history:
            return ""

        lines = ["\nPREVIOUS ATTEMPTS IN THIS SESSION:\n"]

        for entry in history:
            lines.append(f"Iteration {entry['iteration']}:")
            lines.append("  Code Attempted:")
            for code_line in entry['code'].split('\n'):
                code_line_escaped = code_line.replace('{', '{{').replace('}', '}}')
                lines.append(f"    {code_line_escaped}")

            execution_success = entry.get('execution_success', entry.get('success', False))

            if not execution_success:
                lines.append(f"\n  Execution Result: FAILED")
                error = entry.get('execution_error', entry.get('error', 'Unknown error'))
                error_escaped = str(error).replace('{', '{{').replace('}', '}}')
                lines.append(f"  Error: {error_escaped}")
            else:
                lines.append(f"\n  Execution Result: SUCCESS")
                result_preview = str(entry.get('result', ''))[:200]
                result_escaped = result_preview.replace('{', '{{').replace('}', '}}')
                lines.append(f"  Output Preview: {result_escaped}...")

                quality_ok = entry.get('quality_ok')
                if quality_ok is not None:
                    quality_status = "PASSES QUALITY CHECK" if quality_ok else "FAILS QUALITY CHECK"
                    lines.append(f"  Quality Evaluation: {quality_status}")

                    quality_reasoning = entry.get('quality_reasoning')
                    if quality_reasoning:
                        reasoning_escaped = str(quality_reasoning).replace('{', '{{').replace('}', '}}')
                        lines.append(f"  Reasoning: {reasoning_escaped}")

            lines.append("")

        lines.append("Analyze what went wrong in previous attempts and generate IMPROVED code that addresses these issues.\n")

        return "\n".join(lines)

    async def _execute_and_evaluate(
        self,
        code: str,
        tool_output: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Execute code and check if it runs successfully."""
        try:
            filtered_output = self._safe_executor.execute(code, tool_output)
            result_str = str(filtered_output)
            return True, result_str, None
        except Exception as e:
            error_msg = str(e)
            self._logger.debug("Code execution failed: %s", error_msg)
            return False, None, error_msg

    async def _evaluate_output_quality(
        self,
        filtered_output: str,
        tool_output: str,
        expected_info: str,
        tracer: Optional[Tracer] = None
    ) -> tuple[bool, str]:
        """Use LLM to evaluate if the filtered output aligns with the agent's goal."""
        try:
            tool_output_preview = tool_output[:500]
            if len(tool_output) > 500:
                tool_output_preview += "\n... (truncated)"

            filtered_preview = filtered_output[:1000]
            if len(filtered_output) > 1000:
                filtered_preview += "\n... (truncated)"

            tool_output_preview = tool_output_preview.replace('{', '{{').replace('}', '}}')
            expected_info_escaped = expected_info.replace('{', '{{').replace('}', '}}')
            filtered_preview = filtered_preview.replace('{', '{{').replace('}', '}}')

            prompt = REFLECTION_PROMPT.format(
                expected_info=expected_info_escaped,
                tool_output_preview=tool_output_preview,
                filtered_output=filtered_preview
            )

            response = await self._llm.generate_async(
                messages=[{"role": "user", "content": prompt}],
                tracer=tracer or Tracer()
            )

            response_text = response.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response_text = "\n".join(lines)

            evaluation = json.loads(response_text)

            is_satisfactory = evaluation.get("success", False)
            reasoning = evaluation.get("reasoning", "No reasoning provided")
            issue = evaluation.get("issue", "")

            if not is_satisfactory and issue:
                reasoning = f"{reasoning}. Issue: {issue}"

            self._logger.debug(
                "Quality evaluation: success=%s, reasoning=%s",
                is_satisfactory, reasoning
            )

            return is_satisfactory, reasoning

        except Exception as e:
            self._logger.warning(
                "Reflection evaluation failed: %s. Assuming success.", str(e)
            )
            return True, "Reflection failed, assuming valid execution is sufficient"

    def _find_in_memory(self, tool_name: str, expected_info: str) -> Optional[str]:
        """Search session memory for successful code with matching criteria."""
        if not self._enable_memory:
            return None

        for entry in reversed(self._session_memory):
            if (entry["tool_name"] == tool_name and
                entry["expected_info"] == expected_info and
                entry["success"]):
                return entry["filter_code"]

        return None

    def _add_to_memory(
        self,
        tool_name: str,
        expected_info: str,
        filter_code: str,
        success: bool,
        error: Optional[str],
        output_length: int,
        filtered_length: int,
        iterations_taken: int = 1
    ):
        """Add execution record to session memory."""
        if not self._enable_memory:
            return

        memory_entry = {
            "tool_name": tool_name,
            "expected_info": expected_info,
            "filter_code": filter_code,
            "success": success,
            "error": error,
            "output_length": output_length,
            "filtered_length": filtered_length,
            "iterations_taken": iterations_taken,
            "timestamp": datetime.now().isoformat()
        }

        self._session_memory.append(memory_entry)

        self._logger.debug(
            "Added to session memory: tool=%s, success=%s, iterations=%d, entries=%d",
            tool_name, success, iterations_taken, len(self._session_memory)
        )

    def get_memory(self) -> List[Dict[str, Any]]:
        """Get the current session memory."""
        return self._session_memory.copy()

    def clear_memory(self):
        """Clear the session memory."""
        self._session_memory.clear()
        self._logger.debug("Session memory cleared")

    def get_memory_summary(self) -> Dict[str, Any]:
        """Get a summary of the session memory."""
        if not self._session_memory:
            return {
                "total_entries": 0,
                "successful": 0,
                "failed": 0,
                "unique_tools": 0,
                "unique_queries": 0
            }

        successful = sum(1 for entry in self._session_memory if entry["success"])
        failed = len(self._session_memory) - successful
        unique_tools = len(set(entry["tool_name"] for entry in self._session_memory))
        unique_queries = len(set(
            f"{entry['tool_name']}:{entry['expected_info']}"
            for entry in self._session_memory
        ))

        return {
            "total_entries": len(self._session_memory),
            "successful": successful,
            "failed": failed,
            "unique_tools": unique_tools,
            "unique_queries": unique_queries
        }
