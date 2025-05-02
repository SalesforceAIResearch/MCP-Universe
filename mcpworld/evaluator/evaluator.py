"""
The evaluator for assessing agent performance
"""
# pylint: disable=broad-exception-caught
import re
import json
from typing import Any, Dict, List
from pydantic import BaseModel
from pydantic_core import from_json
from mcpworld.common.misc import AutodocABCMeta
from .functions import EVALUATION_FUNCTIONS, COMPARISON_FUNCTIONS, FunctionResult


class EvaluatorConfig(BaseModel):
    """
    The configuration for an evaluator. It will evaluate this expression: `func(...) op value`.
    """
    func: str  # A chain of function calls, e.g., get(key1) -> foreach -> get(key2)
    op: str = ""  # The operator for comparison, e.g., "=", "<".
    value: Any = None  # The operand for comparison.
    op_args: Any = None  # Additional op args.


class EvaluationResult(BaseModel):
    """
    The class for evaluation results.
    """
    config: EvaluatorConfig
    response: str | Dict
    passed: bool
    reason: str = ""
    error: str = ""


class Evaluator(metaclass=AutodocABCMeta):
    """
    The evaluator for assessing agent performance.
    """

    def __init__(self, config: str | Dict | EvaluatorConfig):
        if isinstance(config, str):
            config = from_json(config)
        self._config = config if isinstance(config, EvaluatorConfig) \
            else EvaluatorConfig.model_validate(config)
        self._funcs = self._parse_func(self._config.func)
        assert self._config.op == "" or self._config.op in COMPARISON_FUNCTIONS, \
            f"Unknown comparison op: {self._config.op}"

    @staticmethod
    def _parse_func(func: str) -> List[Dict[str, Any]]:
        """Parse the function strings"""
        items = [f.strip() for f in func.split("->") if f.strip()]
        funcs = []
        for item in items:
            info = {"name": item.split("(")[0].strip()}
            assert info["name"] in EVALUATION_FUNCTIONS, \
                f"Unknown func `{info['name']}`"
            match = re.search(r"\((.*?)\)", item)
            if match:
                args = match.group(1).split(",")
                info["args"] = [arg.strip() for arg in args]
            funcs.append(info)
        return funcs

    def execute(self, x: Dict) -> Any:
        """
        Execute the function specified in the config.

        :param x: An agent output.
        """
        res = FunctionResult(result=x)
        for func in self._funcs:
            name = func["name"]
            args = func.get("args", [])
            res = EVALUATION_FUNCTIONS[name](res, *args)
        return res

    def evaluate(self, x: str | Dict) -> EvaluationResult:
        """
        Evaluate whether an agent output satisfies the rules specified in the config.

        :param x: An agent output.
        """

        def _extract_results(_res: Any) -> List[FunctionResult]:
            """Extract function results."""
            if isinstance(_res, FunctionResult):
                return [_res]
            if isinstance(_res, (list, tuple)):
                _results = []
                for _r in _res:
                    _results.extend(_extract_results(_r))
                return _results
            raise NotImplementedError(f"Cannot extract function results from type `{type(_res)}`")

        try:
            results = _extract_results(self.execute(x))
            op, value, op_args = self._config.op, self._config.value, self._config.op_args
            for r in results:
                passed, reason = COMPARISON_FUNCTIONS[op](r.result, value, op_args)
                if not passed:
                    return EvaluationResult(
                        config=self._config, response=x, passed=passed, reason=reason)
            return EvaluationResult(config=self._config, response=x, passed=True)

        except json.JSONDecodeError as e:
            return EvaluationResult(
                config=self._config, response=x, passed=False, reason="JSON decoding error", error=str(e))
        except Exception as e:
            return EvaluationResult(
                config=self._config, response=x, passed=False, reason="Execution error", error=str(e))
