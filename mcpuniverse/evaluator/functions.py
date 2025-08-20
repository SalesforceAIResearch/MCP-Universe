"""
Evaluation functions and operators.
"""
# pylint: disable=unused-argument
import json
from typing import List, Any, Callable
from pydantic import BaseModel

EVALUATION_FUNCTIONS = {}
COMPARISON_FUNCTIONS = {}


class FunctionResult(BaseModel):
    """
    The class for function output results.
    """
    result: Any


def eval_func(name: str):
    """A decorator for evaluation functions"""

    def _decorator(func: Callable):
        assert name not in EVALUATION_FUNCTIONS, "Duplicated evaluation function name"
        EVALUATION_FUNCTIONS[name] = func

        async def _wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator


def compare_func(name: str):
    """A decorator for comparison functions"""

    def _decorator(func: Callable):
        assert name not in COMPARISON_FUNCTIONS, "Duplicated comparison function name"
        COMPARISON_FUNCTIONS[name] = func

        async def _wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator


##################################################################################
# Functions for evaluation
##################################################################################

@eval_func(name="json")
async def json_decode(x: Any, *args, **kwargs) -> Any:
    """JSON decoding."""
    if isinstance(x, FunctionResult):
        assert isinstance(x.result, str), "The input is not a string"
        x = x.result.strip().strip("`").strip()
        if x.startswith("json"):
            x = x[4:].strip()
        return FunctionResult(result=json.loads(x))
    if isinstance(x, (list, tuple)):
        return [await json_decode(y, *args, **kwargs) for y in x]
    raise NotImplementedError(f"`json_decode` doesn't support type {type(x)}")


@eval_func(name="get")
async def get(x: Any, key: str, *args, **kwargs) -> Any:
    """Get the value of a key in a dict."""
    if isinstance(x, FunctionResult):
        assert isinstance(x.result, dict), "The input is not a dict"
        return FunctionResult(result=x.result.get(key, None))
    if isinstance(x, (list, tuple)):
        return [await get(y, key, *args, **kwargs) for y in x]
    raise NotImplementedError(f"`get` doesn't support type {type(x)}")


@eval_func(name="len")
async def length(x: Any, *args, **kwargs) -> Any:
    """Get the length of a list."""
    if isinstance(x, FunctionResult):
        assert isinstance(x.result, (list, tuple)), "The input is not a list"
        return FunctionResult(result=len(x.result))
    if isinstance(x, (list, tuple)):
        return [await length(y, *args, **kwargs) for y in x]
    raise NotImplementedError(f"`len` doesn't support type {type(x)}")


@eval_func(name="foreach")
async def foreach(x: List, *args, **kwargs) -> Any:
    """Foreach loop."""
    if isinstance(x, FunctionResult):
        assert isinstance(x.result, (list, tuple)), "The input is not a list"
        return [FunctionResult(result=y) for y in x.result]
    if isinstance(x, (list, tuple)):
        return [await foreach(y, *args, **kwargs) for y in x]
    raise NotImplementedError(f"`foreach` doesn't support type {type(x)}")


@eval_func(name="raw")
async def raw_decode(x: Any, *args, **kwargs) -> Any:
    """return raw data, no need to process"""
    if isinstance(x, FunctionResult):
        return FunctionResult(result=x)
    if isinstance(x, (list, tuple)):
        return [await raw_decode(y, *args, **kwargs) for y in x]
    raise NotImplementedError(f"`raw_decode` doesn't support type {type(x)}")


@eval_func(name="list")
async def to_list(x: Any, *args, **kwargs) -> Any:
    """Convert to list"""
    if isinstance(x, FunctionResult):
        return FunctionResult(result=[x.result])
    if isinstance(x, (list, tuple)):
        return [await to_list(y, *args, **kwargs) for y in x]


##################################################################################
# Functions for comparison
##################################################################################

@compare_func(name="=")
async def equal(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Equal"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if a == b:
        return True, ""
    return False, "output is not equal to ground-truth"


@compare_func(name="<")
async def less_than(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Less than"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if a < b:
        return True, ""
    return False, "output is not less than ground-truth"


@compare_func(name="<=")
async def less_equal(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Less than or equal to"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if a <= b:
        return True, ""
    return False, "output is not less than or equal to ground-truth"


@compare_func(name=">")
async def greater_than(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Greater than"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if a > b:
        return True, ""
    return False, "output is not greater than ground-truth"


@compare_func(name=">=")
async def greater_equal(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Greater than or equal to"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if a >= b:
        return True, ""
    return False, "output is not greater than or equal to ground-truth"


@compare_func(name="in")
async def is_in(a: Any, b: List | FunctionResult, *args, **kwargs) -> (bool, str):
    """In a list"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if not isinstance(b, (str, list, tuple)):
        raise ValueError("The second argument in comparison function `in` is not a list or a str")
    if a in b:
        return True, ""
    return False, "ground-truth doesn't contain output"


@compare_func(name="contain")
async def contain(a: List | str | FunctionResult, b: Any, *args, **kwargs) -> (bool, str):
    """Contains"""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if not isinstance(a, (str, list, tuple)):
        raise ValueError("The first argument in comparison function `contain` is not a list or a str")
    if b in a:
        return True, ""
    return False, "output doesn't contain ground-truth"
