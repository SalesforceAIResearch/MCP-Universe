"""Offline benchmark with a real MCP server and a scripted model."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from openai.types.chat import ChatCompletion

from mcpuniverse.benchmark.deep_research import run


def completion(message):
    return ChatCompletion.model_validate({
        "id": "offline", "created": 0, "model": "offline", "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    })


@pytest.mark.asyncio
async def test_example_runs_and_resumes_without_provider_calls(tmp_path):
    response = completion({
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call-1", "type": "function", "function": {
            "name": "research-primitives__run_research_program",
            "arguments": json.dumps({"code": "print(6 * 7)", "timeout": 5}),
        }}],
    })
    final = completion({"role": "assistant", "content": json.dumps({
        "thought": "The program computed the answer.", "answer": "42",
    })})
    config = str(Path(__file__).resolve().parents[2] / "examples/deep_research/benchmark.yaml")
    # Exercise the ordinary API-only install, without optional GPU engines.
    with patch.dict(sys.modules, {"vllm": None, "sglang": None}), patch(
        "mcpuniverse.llm.openai.OpenAIModel._generate", side_effect=[response, final]
    ) as model:
        results = await run(config, str(tmp_path))
        assert model.call_count == 2
        assert results[0]["task_trace_ids"]
        traces = (tmp_path / "traces.log").read_text()
        assert "42" in traces
        assert '"success": true' in traces or '\\"success\\": true' in traces
        await run(config, str(tmp_path), resume=True)
        assert model.call_count == 2
    assert (tmp_path / "results.json").is_file()
