"""Exercise actual subprocess isolation without external providers."""
import asyncio
import time
from unittest.mock import patch

import pytest

from mcpuniverse.mcp.servers.research_primitives import server


@pytest.mark.asyncio
async def test_async_program_returns_only_printed_findings():
    result = await server._run_program(
        "values = await asyncio.gather(asyncio.sleep(0, result=20), "
        "asyncio.sleep(0, result=22))\nprint(sum(values))", 5
    )
    assert result == {"success": True, "error": "", "stdout": "42\n"}


@pytest.mark.parametrize("code", ["import os", "print(open('/etc/passwd'))", "print((1).__class__)"])
@pytest.mark.asyncio
async def test_restricted_program_is_rejected(code):
    result = await server._run_program(code, 5)
    assert not result["success"]
    assert "not allowed" in result["error"]


@pytest.mark.asyncio
async def test_runaway_program_is_killed_without_blocking_other_calls():
    started = time.monotonic()
    with patch.object(server, "_SUBPROCESS_OVERHEAD_S", 1):
        runaway, healthy = await asyncio.gather(
            server._run_program("while True: pass", 1),
            server._run_program("print('healthy')", 5),
        )
    assert not runaway["success"]
    assert "wall budget" in runaway["error"]
    assert healthy["stdout"] == "healthy\n"
    assert time.monotonic() - started < 15


@pytest.mark.asyncio
async def test_runtime_error_keeps_partial_output():
    result = await server._run_program("print('progress')\n1 / 0", 5)
    assert not result["success"]
    assert "ZeroDivisionError" in result["error"]
    assert result["stdout"] == "progress\n"


@pytest.mark.asyncio
async def test_output_is_capped():
    result = await server._run_program("print('x' * 100000)", 5)
    assert result["success"]
    assert len(result["stdout"]) <= server.MAX_STDOUT_CHARS
    assert "truncated" in result["stdout"]
