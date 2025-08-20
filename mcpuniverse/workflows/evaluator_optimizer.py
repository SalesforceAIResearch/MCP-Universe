"""
Agent workflow pattern: Evaluator-optimizer

This module implements the Evaluator-Optimizer workflow pattern as described in
https://www.anthropic.com/engineering/building-effective-agents. It provides a
mechanism for iteratively improving AI-generated responses through evaluation
and refinement.

The prompts used in this implementation are inspired by:
https://github.com/lastmile-ai/mcp-agent/blob/main/src/mcp_agent/workflows/evaluator_optimizer/evaluator_optimizer.py
"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import from_json

from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.workflows.base import BaseWorkflow
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.agent.utils import render_prompt_template
from mcpuniverse.tracer import Tracer

EVAL_PROMPT_TEMPLATE = """
Original Request: 
{{REQUEST}}

Current Response (Iteration {{ITERATION}}): 
{{RESPONSE}}

Provide your evaluation as a structured response with:
1. A quality rating (EXCELLENT, GOOD, FAIR, or POOR)
2. Specific feedback and suggestions
3. Whether improvement is needed (true or false)
4. Focus areas for improvement

Rate as EXCELLENT only if no improvements are needed.
Rate as GOOD if only minor improvements are possible.
Rate as FAIR if several improvements are needed.
Rate as POOR if major improvements are needed.

Return your response in the following JSON structure:
{
    "rating": "Quality rating of the response: EXCELLENT, GOOD, FAIR or POOR",
    "needs_improvement": "Whether the output needs further improvement: true or false",
    "feedback": "Specific feedback and suggestions for improvement",
    "focus_areas": "Specific areas to focus on in next iteration"
}

You must respond with valid JSON only, with no triple backticks. No markdown formatting.
No extra text. Do not wrap in ```json code fences.
"""

REFINE_PROMPT_TEMPLATE = """
Improve your previous response based on the evaluation feedback.
        
Original Request: 
{{REQUEST}}

Previous Response (Iteration {{ITERATION}}): 
{{RESPONSE}}

Quality Rating: {{RATING}}
Feedback: {{FEEDBACK}}
Areas to Focus On: {{FOCUS_AREAS}}

Generate an improved result addressing the feedback while maintaining accuracy and relevance.
"""


class EvaluationResult(BaseModel):
    """
    Represents the result of an evaluation in the Evaluator-Optimizer workflow.

    This model encapsulates the evaluation metrics and feedback provided by the
    evaluator agent, which are used to guide the optimization process.
    """
    rating: str = Field(description="Quality rating of the response")
    feedback: str = Field(description="Specific feedback and suggestions for improvement")
    needs_improvement: bool = Field(description="Whether the output needs further improvement")
    focus_areas: str = Field(description="Specific areas to focus on in next iteration")


class EvaluatorOptimizer(BaseWorkflow):
    """
    Implements the Evaluator-Optimizer workflow for iterative response improvement.

    This workflow uses two agents: an optimizer that generates responses, and an
    evaluator that assesses the quality of these responses. The process iterates
    until a satisfactory response is achieved or the maximum number of iterations
    is reached.
    """
    alias = ["evaluator-optimizer"]

    def __init__(
            self,
            optimizer: BaseAgent,
            evaluator: BaseAgent,
            max_iterations: int = 3,
            min_rating: str = "GOOD"
    ):
        """
        Initialize an EvaluatorOptimizer workflow.

        Args:
            optimizer (BaseAgent): The agent responsible for generating and refining responses.
            evaluator (BaseAgent): The agent responsible for evaluating response quality.
            max_iterations (int, optional): The maximum number of refinement steps. Defaults to 3.
            min_rating (str, optional): The minimum acceptable quality rating. Defaults to "GOOD".
        """
        super().__init__()
        self._name = "evaluator-optimizer"
        self._agents = [optimizer, evaluator]
        self._optimizer = optimizer
        self._evaluator = evaluator
        self._max_iterations = max_iterations
        self._min_rating = min_rating
        self._ratings = {"EXCELLENT": 3, "GOOD": 2, "FAIR": 1, "POOR": 0}

    async def execute(
            self,
            message: str | List[str],
            output_format: Optional[str | Dict] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the Evaluator-Optimizer workflow.

        This method runs the iterative process of generating, evaluating, and refining
        responses until a satisfactory result is achieved or the maximum number of
        iterations is reached.

        Args:
            message (str | List[str]): The input message or question to be addressed.
            output_format (Optional[str | Dict], optional): The desired format for the final output.
            **kwargs: Additional keyword arguments.

        Returns:
            AgentResponse: The best response generated during the workflow execution.

        Raises:
            ValueError: If the planner output cannot be parsed.
            Exception: For any other errors that occur during execution.
        """
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            if isinstance(message, (list, tuple)):
                message = "\n".join(message)

            best_rating = "POOR"
            response = await self._optimizer.execute(message, output_format=output_format, tracer=tracer)
            best_response = response
            try:
                for i in range(self._max_iterations):
                    eval_prompt = render_prompt_template(EVAL_PROMPT_TEMPLATE, **{
                        "REQUEST": message,
                        "ITERATION": i + 1,
                        "RESPONSE": response.get_response_str()
                    })
                    output = await self._evaluator.execute(eval_prompt, tracer=tracer)
                    eval_response = EvaluationResult.model_validate(from_json(output.get_response_str()))
                    if self._compare_ratings(eval_response.rating, best_rating):
                        best_rating = eval_response.rating
                        best_response = response
                    if (self._compare_ratings(eval_response.rating, self._min_rating) or
                            not eval_response.needs_improvement):
                        break

                    refine_prompt = render_prompt_template(REFINE_PROMPT_TEMPLATE, **{
                        "REQUEST": message,
                        "ITERATION": i + 1,
                        "RESPONSE": response.get_response_str(),
                        "RATING": eval_response.rating,
                        "FEEDBACK": eval_response.feedback,
                        "FOCUS_AREAS": eval_response.focus_areas
                    })
                    response = await self._optimizer.execute(
                        refine_prompt, output_format=output_format, tracer=tracer)

                response = AgentResponse(
                    name=self._name,
                    class_name=self.__class__.__name__,
                    response=best_response.response,
                    trace_id=tracer.trace_id
                )
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": response.get_response(),
                    "response_type": response.get_response_type(),
                    "error": ""
                })
                tracer.add(trace_data)
                return response

            except ValidationError as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                raise ValueError("Failed to parse the planner output") from e
            except Exception as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                raise e

    def _compare_ratings(self, a: str, b: str) -> bool:
        """Compare two quality ratings."""
        return self._ratings.get(a.upper(), -1) >= self._ratings.get(b.upper(), -1)

    def dump_config(self) -> dict:
        """
        Dump the workflow configuration as a dictionary.

        Returns:
            dict: A dictionary containing the configuration of this workflow,
                  including the optimizer and evaluator agent configurations.
        """
        return {
            "type": "workflow",
            "class": self.__class__.__name__,
            "optimizer": self._optimizer.dump_config(),
            "evaluator": self._evaluator.dump_config(),
            "max_iterations": self._max_iterations,
            "min_rating": self._min_rating
        }
