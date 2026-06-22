"""Unit tests for DockerProvisioner._run_docker_cmd hardening.

These lock in the behavior that protects the rollout loop from a slow/hung or
504-ing Docker endpoint:

- a hung ``docker`` call times out (instead of pinning its worker thread
  forever) and is retried, then fails fast with a RuntimeError;
- transient gateway errors (502/503/504) are retried and can recover;
- non-transient errors fail immediately without burning retries.

``subprocess.run`` is mocked so no real Docker daemon is required, and
``asyncio.sleep`` is stubbed so retry backoff doesn't slow the test.
"""

import asyncio
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from mcpuniverse.mcp.env_pool.docker import DockerProvisioner


def _provisioner(**kw):
    return DockerProvisioner(docker_host="tcp://fake:2375", **kw)


def test_is_transient_docker_error_classification():
    prov = _provisioner()
    assert prov._is_transient_docker_error("Error response from daemon: 504 Gateway Time-out")
    assert prov._is_transient_docker_error("502 Bad Gateway")
    assert prov._is_transient_docker_error("connection reset by peer")
    assert not prov._is_transient_docker_error("No such container: x")
    assert not prov._is_transient_docker_error("")


def test_run_docker_cmd_timeout_is_retried_then_fails_fast():
    """A hung docker call must time out + retry, then raise (never hang)."""
    prov = _provisioner(docker_cmd_retries=2)
    calls = {"n": 0}

    def fake_run(*_a, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="docker", timeout=kwargs.get("timeout"))

    async def go():
        with patch("subprocess.run", side_effect=fake_run), \
                patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError):
                await prov._run_docker_cmd(["ps"], timeout=0.01, retries=2)

    asyncio.run(go())
    assert calls["n"] == 3  # initial attempt + 2 retries


def test_run_docker_cmd_retries_transient_gateway_error_and_recovers():
    """A transient 504 is retried; a subsequent success is returned."""
    prov = _provisioner()
    seq = [
        subprocess.CompletedProcess(["docker"], 1, b"", b"Error: 504 Gateway Time-out"),
        subprocess.CompletedProcess(["docker"], 0, b"ok", b""),
    ]

    def fake_run(*_a, **_k):
        return seq.pop(0)

    async def go():
        with patch("subprocess.run", side_effect=fake_run), \
                patch("asyncio.sleep", new=AsyncMock()):
            res = await prov._run_docker_cmd(["ps"], retries=2)
            assert res.returncode == 0
            assert res.stdout == "ok"

    asyncio.run(go())
    assert seq == []  # both responses consumed -> exactly one retry


def test_run_docker_cmd_non_transient_error_fails_without_retry():
    """A normal docker failure must not waste the retry budget."""
    prov = _provisioner()
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return subprocess.CompletedProcess(["docker"], 1, b"", b"No such container: x")

    async def go():
        with patch("subprocess.run", side_effect=fake_run), \
                patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError):
                await prov._run_docker_cmd(["rm", "x"], retries=2)

    asyncio.run(go())
    assert calls["n"] == 1  # non-transient -> no retry


def test_run_docker_cmd_uses_dedicated_executor():
    """Docker calls must run on the dedicated pool, not the loop default."""
    prov = _provisioner(max_docker_workers=8)
    assert prov._docker_executor is not None
    assert prov._docker_executor._max_workers == 8

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(["docker"], 0, b"out", b"")

    seen = {}

    async def go():
        loop = asyncio.get_running_loop()
        orig = loop.run_in_executor

        def spy(executor, func, *args):
            seen["executor"] = executor
            return orig(executor, func, *args)

        with patch("subprocess.run", side_effect=fake_run), \
                patch.object(loop, "run_in_executor", side_effect=spy):
            await prov._run_docker_cmd(["ps"])

    asyncio.run(go())
    assert seen["executor"] is prov._docker_executor
