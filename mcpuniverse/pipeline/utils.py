"""Pipeline utilities for task output serialization and deserialization."""

import json
from typing import Dict, Any
from pydantic import BaseModel
from mcpuniverse.tracer.types import BaseDataClass, TraceRecord
from mcpuniverse.evaluator.evaluator import EvaluationResult


def serialize_task_output(task_output: Dict[str, Any]) -> bytes:
    """
    Serialize task output for message queue transmission.
    
    Args:
        task_output: Dictionary containing task execution results.
        
    Returns:
        JSON string representation of the task output.
    """
    def _serialize(value: Any):
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, BaseDataClass):
            return value.to_dict()
        if isinstance(value, (list, tuple)):
            return [_serialize(v) for v in value]
        return value

    outputs = {}
    for key, val in task_output.items():
        outputs[key] = _serialize(val)
    return json.dumps(outputs).encode("utf-8")


def deserialize_task_output(output: bytes) -> Dict[str, Any]:
    """
    Deserialize task output from message queue transmission.
    
    Args:
        output: JSON string containing serialized task output.
        
    Returns:
        Dictionary with deserialized task execution results.
        
    Raises:
        RuntimeError: If required fields are missing from task output.
    """
    d = json.loads(output.decode("utf-8"))
    if "result" not in d:
        raise RuntimeError("Task output doesn't contain `result`")
    if "evaluation_results" not in d:
        raise RuntimeError("Task output doesn't contain `evaluation_results`")
    if "trace" not in d:
        raise RuntimeError("Task output doesn't contain `trace`")

    d["evaluation_results"] = [EvaluationResult.model_validate(v) for v in d["evaluation_results"]]
    d["trace"] = [TraceRecord.from_dict(v) for v in d["trace"]]
    return d
