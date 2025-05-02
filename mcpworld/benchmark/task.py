"""
The class for an agent task
"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from pydantic_core import from_json
from mcpworld.common.misc import AutodocABCMeta
from mcpworld.evaluator import EvaluatorConfig, Evaluator, EvaluationResult


class TaskConfig(BaseModel):
    """
    Task configuration.
    """
    category: str = Field(default="general", description="Task category")
    question: str = Field(default="", description="Task question")
    output_format: dict = Field(default_factory=dict, description="JSON output format")
    mcp_servers: List[dict] = Field(default_factory=list, description="MCP servers in this task")
    evaluators: List[EvaluatorConfig] = Field(default_factory=list, description="Evaluator configurations")


class Task(metaclass=AutodocABCMeta):
    """
    The class for an agent task.
    """

    def __init__(self, config: str | Dict):
        if isinstance(config, str):
            if config.endswith(".json"):
                with open(config, "r", encoding="utf-8") as f:
                    config = f.read()
            config = from_json(config)
        self._config = TaskConfig.model_validate(config)
        self._evaluators = [Evaluator(c) for c in self._config.evaluators]

    def get_question(self) -> str:
        """Return question prompt."""
        return self._config.question

    def get_output_format(self) -> Optional[dict]:
        """Return the output format."""
        if self._config.output_format:
            return self._config.output_format
        return None

    def get_mcp_servers(self) -> List[Dict]:
        """
        Return the MCP servers used in this task.
        """
        return self._config.mcp_servers

    def get_evaluators(self):
        """
        Return the specified evaluators.
        """
        return self._evaluators

    def evaluate(self, x: str | Dict) -> List[EvaluationResult]:
        """
        Run evaluations given the agent output.

        :param x: The agent output.
        """
        return [evaluator.evaluate(x) for evaluator in self._evaluators]
