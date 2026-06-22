"""Unit tests for the apptainer worker control server (server-side).

This is the half the apptainer mock-worker client test (test_apptainer_provisioner)
can't reach: the worker's own ``start()`` logic that turns a caller-supplied
``control_port_vars`` template into a concrete, uniquely-allocated aux port and
injects it into the ``apptainer run --env`` string. That templating + the aux
port bookkeeping (alloc on start, release on stop) is the most recently
refactored, most drift-prone code in the backend and previously had ZERO
coverage -- a silent break there yields an env that boots but whose gateway
control proxy points at the wrong/no port (404 / connection refused at run time).

No real apptainer or network is used: ``subprocess.Popen`` is mocked to a fake
process and the port-free / gateway-ready probes are stubbed True, so ``start()``
returns on the first readiness check.
"""

import contextlib
import os
import tempfile

import pytest
from unittest.mock import patch

from mcpuniverse.mcp.env_pool.apptainer_worker import server as W


class _FakeProc:
    """A subprocess.Popen stand-in that always looks alive."""

    def __init__(self, pid: int = 999_999):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return None  # alive -> start()'s readiness loop proceeds to _gateway_ready

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _staged_store(image_key: str = "default") -> str:
    """A SIF store with ``<key>/rootfs`` so resolve_base() succeeds."""
    store = tempfile.mkdtemp()
    os.makedirs(os.path.join(store, W._safe_name(image_key), "rootfs"))
    return store


@contextlib.contextmanager
def _running_worker(image_key: str = "default"):
    """Yield (manager, rec) with all real side effects (proc spawn, port/gateway
    probes, teardown) stubbed; ``rec['cmd']`` captures the last apptainer argv."""
    store = _staged_store(image_key)
    logdir = tempfile.mkdtemp()
    rec: dict = {}

    def fake_popen(cmd, **kw):
        rec["cmd"] = list(cmd)
        rec["kw"] = kw
        return _FakeProc()

    with patch.object(W, "LOG_DIR", logdir), \
            patch.object(W, "_wait_port_free", return_value=True), \
            patch.object(W, "_gateway_ready", return_value=True), \
            patch.object(W, "_terminate", lambda *a, **k: None), \
            patch.object(W.subprocess, "Popen", side_effect=fake_popen):
        yield W.ApptainerEnvManager(sif_store=store), rec


def _env_map(cmd) -> dict:
    """Parse the ``--env k=v,k=v`` argv item into a dict."""
    i = cmd.index("--env")
    return dict(kv.split("=", 1) for kv in cmd[i + 1].split(","))


def _in_ctrl_range(port: int) -> bool:
    return W.CTRL_PORT_BASE <= port < W.CTRL_PORT_BASE + W.CTRL_PORT_SPAN


def test_control_port_vars_templated_into_env_and_bookkept():
    """{port} templates render to the allocated aux port in the run --env, and the
    port is recorded as used + stored on the EnvRec."""
    with _running_worker() as (mgr, rec):
        res = mgr.start(
            "e1", "default", 9000, startup_timeout=5.0,
            control_port_vars={
                "R2E_CONTROL_PORT": "{port}",
                "GATEWAY_CONTROL_PROXY_URL": "http://localhost:{port}",
            },
        )
        port = res["control_port"]
        assert res["ok"] is True
        assert _in_ctrl_range(port)

        env = _env_map(rec["cmd"])
        assert env["R2E_CONTROL_PORT"] == str(port)
        assert env["GATEWAY_CONTROL_PROXY_URL"] == f"http://localhost:{port}"
        # The gateway port is always exported regardless of aux ports.
        assert env["MCP_GATEWAY_PORT"] == "9000"

        erec = mgr._envs["e1"]  # pylint: disable=protected-access
        assert erec.control_port == port
        assert erec.control_port_vars  # preserved for reset()
        assert port in mgr._used_ctrl_ports  # pylint: disable=protected-access


def test_no_control_port_vars_allocates_no_aux_port():
    """Without control_port_vars the worker stays task-agnostic: no aux port, and
    no task-specific var leaks into the env."""
    with _running_worker() as (mgr, rec):
        res = mgr.start("e1", "default", 9000, startup_timeout=5.0)
        assert res["control_port"] is None

        env = _env_map(rec["cmd"])
        assert "R2E_CONTROL_PORT" not in env
        assert mgr._used_ctrl_ports == set()  # pylint: disable=protected-access
        assert mgr._envs["e1"].control_port is None  # pylint: disable=protected-access


def test_concurrent_envs_get_distinct_ports_released_on_stop():
    """Shared netns => aux ports must be unique across live envs, and stop() must
    return the port to the pool (else the worker slowly leaks its aux range)."""
    with _running_worker() as (mgr, _rec):
        cpv = {"P": "{port}"}
        r1 = mgr.start("e1", "default", 9000, startup_timeout=5.0, control_port_vars=cpv)
        r2 = mgr.start("e2", "default", 9001, startup_timeout=5.0, control_port_vars=cpv)

        assert r1["control_port"] != r2["control_port"]
        assert {r1["control_port"], r2["control_port"]} <= mgr._used_ctrl_ports  # noqa: E501  # pylint: disable=protected-access

        assert mgr.stop("e1") is True
        assert r1["control_port"] not in mgr._used_ctrl_ports  # released  # pylint: disable=protected-access
        assert r2["control_port"] in mgr._used_ctrl_ports       # still held  # pylint: disable=protected-access
        assert "e1" not in mgr._envs  # pylint: disable=protected-access


def test_reset_reuses_gateway_port_and_reinjects_control_vars():
    """reset() == restart on the SAME gateway port (so the rollouter's
    gateway_address stays valid) and must re-inject the aux port template."""
    with _running_worker() as (mgr, rec):
        cpv = {"R2E_CONTROL_PORT": "{port}"}
        mgr.start("e1", "default", 9000, startup_timeout=5.0, control_port_vars=cpv)

        res = mgr.reset("e1")
        assert res["ok"] is True
        assert res["gateway_port"] == 9000  # same port across reset

        env = _env_map(rec["cmd"])
        assert "R2E_CONTROL_PORT" in env
        assert _in_ctrl_range(int(env["R2E_CONTROL_PORT"]))
        assert mgr._envs["e1"].control_port_vars == cpv  # pylint: disable=protected-access


def test_start_idempotent_replaces_stale_env_same_id():
    """A second start() with the same env_id tears down the stale one first
    (idempotent), leaving exactly one live record."""
    with _running_worker() as (mgr, _rec):
        cpv = {"P": "{port}"}
        mgr.start("e1", "default", 9000, startup_timeout=5.0, control_port_vars=cpv)
        second = mgr.start("e1", "default", 9000, startup_timeout=5.0, control_port_vars=cpv)

        assert "e1" in mgr._envs  # pylint: disable=protected-access
        # The implicit stop() must release the stale env's aux port, so a restart
        # NEVER leaks: exactly one port is held (the freed one may be re-used).
        assert len(mgr._used_ctrl_ports) == 1  # pylint: disable=protected-access
        assert second["control_port"] in mgr._used_ctrl_ports  # pylint: disable=protected-access


def test_resolve_base_prefers_sandbox_then_sif_else_raises():
    """Base resolution order: <key>/rootfs sandbox > <key>/image.sif > <key>.sif,
    and a missing base raises (so a never-staged image fails loudly, not silently
    onto the wrong path)."""
    with patch.object(W, "LOG_DIR", tempfile.mkdtemp()):
        store = tempfile.mkdtemp()
        mgr = W.ApptainerEnvManager(sif_store=store)

        with pytest.raises(FileNotFoundError):
            mgr.resolve_base("missing")

        # Flat <key>.sif at the store root.
        open(os.path.join(store, "flat.sif"), "wb").close()
        assert mgr.resolve_base("flat").endswith("flat.sif")

        # Sandbox rootfs wins over everything.
        os.makedirs(os.path.join(store, "sb", "rootfs"))
        assert mgr.resolve_base("sb").endswith(os.path.join("sb", "rootfs"))


def test_alloc_ctrl_port_exhaustion_raises():
    """The aux-port allocator must fail cleanly when its (small) range is full
    rather than hand out a duplicate."""
    with patch.object(W, "LOG_DIR", tempfile.mkdtemp()), \
            patch.object(W, "CTRL_PORT_SPAN", 2):
        mgr = W.ApptainerEnvManager(sif_store=tempfile.mkdtemp())
        a = mgr._alloc_ctrl_port()  # pylint: disable=protected-access
        b = mgr._alloc_ctrl_port()  # pylint: disable=protected-access
        assert a != b
        with pytest.raises(RuntimeError):
            mgr._alloc_ctrl_port()  # pylint: disable=protected-access
