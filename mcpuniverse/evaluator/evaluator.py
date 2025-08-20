"""
The evaluator for assessing agent performance
"""
# pylint: disable=broad-exception-caught
import os
import re
import json
from typing import Any, Dict, List, Optional
import traceback
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_core import from_json
from jinja2 import Environment, meta
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.common.context import Context
from .functions import EVALUATION_FUNCTIONS, COMPARISON_FUNCTIONS, FunctionResult

load_dotenv()


class EvaluatorConfig(BaseModel):
    """
    The configuration for an evaluator. It will evaluate this expression: `func(...) op value`.
    """
    func: str  # A chain of function calls, e.g., get(key1) -> foreach -> get(key2)
    op: str = ""  # The operator for comparison, e.g., "=", "<".
    value: Any = None  # The operand for comparison.
    op_args: Any = None  # Additional op args.
    desc: str = ""  # The Evaluator description, will be used 1. dump a report 2. verbose mode

    def set_environ_variables(self, context: Optional[Context] = None):
        """Set environment variables specified in the config."""
        self.value = EvaluatorConfig._set_environ_variables(self.value, context)
        self.op_args = EvaluatorConfig._set_environ_variables(self.op_args, context)

    @staticmethod
    def _set_environ_variables(value: Any, context: Optional[Context] = None):
        """Set environment variables recursively."""
        if isinstance(value, List):
            return [EvaluatorConfig._set_environ_variables(v) for v in value]
        if isinstance(value, Dict):
            return {k: EvaluatorConfig._set_environ_variables(v) for k, v in value.items()}
        if not isinstance(value, str):
            return value
        params = dict(os.environ)
        if context:
            params.update(context.env)
        env = Environment(trim_blocks=True, lstrip_blocks=True)
        undefined_vars = meta.find_undeclared_variables(env.parse(value))
        d = {var: params.get(var, f"{{{{ {var} }}}}") for var in undefined_vars}
        template = env.from_string(value)
        return template.render(**d)


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

    def __init__(self, config: str | Dict | EvaluatorConfig, context: Optional[Context] = None):
        self._context = context if context else Context()
        if isinstance(config, str):
            config = from_json(config)
        self._config = config if isinstance(config, EvaluatorConfig) \
            else EvaluatorConfig.model_validate(config)
        self._config.set_environ_variables(context=context)
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

    async def execute(self, x: Dict) -> Any:
        """
        Execute the function specified in the config.

        Args:
            x (Dict): An agent output.
        """
        res = FunctionResult(result=x)
        for func in self._funcs:
            name = func["name"]
            args = func.get("args", [])
            res = await EVALUATION_FUNCTIONS[name](res, *args)
        return res

    async def evaluate(self, x: str | Dict) -> EvaluationResult:
        """
        Evaluate whether an agent output satisfies the rules specified in the config.

        Args:
            x (Dict): An agent output.
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
            results = _extract_results(await self.execute(x))
            op, value, op_args = self._config.op, self._config.value, self._config.op_args
            for r in results:
                if op:
                    passed, reason = await COMPARISON_FUNCTIONS[op](
                        r.result, value, op_args, context=self._context)
                else:
                    passed, reason = True, ""
                if not passed:
                    return EvaluationResult(
                        config=self._config, response=x, passed=passed, reason=reason)
            return EvaluationResult(config=self._config, response=x, passed=True)

        except json.JSONDecodeError as e:
            return EvaluationResult(
                config=self._config, response=x, passed=False, reason="JSON decoding error", error=str(e))
        except Exception as e:
            return EvaluationResult(
                config=self._config, response=x, passed=False, reason="Execution error",
                error=str(e) + str(traceback.format_exc()))
