"""Unit tests for ApptainerProvisioner against a mock worker control server.

Exercises the HTTP client + port-allocation logic without any real apptainer:
a stdlib ThreadingHTTPServer records calls and returns canned worker responses.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcpuniverse.mcp.env_pool.base import EnvConfig, EnvStatus
from mcpuniverse.mcp.env_pool.apptainer import ApptainerProvisioner


class _Rec:
    def __init__(self):
        self.start, self.stop, self.reset, self.health = [], [], [], []
        self.fail_start = False


def _make_handler(rec: _Rec):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if self.path.startswith("/env/health"):
                rec.health.append(self.path)
                self._send(200, {"ok": True, "alive": True, "gateway_ok": True})
            elif self.path == "/healthz":
                self._send(200, {"ok": True, "envs": []})
            else:
                self._send(404, {"ok": False})

        def do_POST(self):
            body = self._body()
            if self.path == "/env/start":
                rec.start.append(body)
                if rec.fail_start:
                    self._send(500, {"ok": False, "error": "boom"})
                else:
                    self._send(200, {"ok": True, "env_id": body["env_id"],
                                     "gateway_port": body["gateway_port"],
                                     "control_port": 21000})
            elif self.path == "/env/stop":
                rec.stop.append(body)
                self._send(200, {"ok": True})
            elif self.path == "/env/reset":
                rec.reset.append(body)
                self._send(200, {"ok": True})
            else:
                self._send(404, {"ok": False})

    return H


def _serve(rec: _Rec):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(rec))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _prov(port, **kw):
    return ApptainerProvisioner(
        host="127.0.0.1", worker_url=f"http://127.0.0.1:{port}",
        base_port=9000, port_range=kw.pop("port_range", 5),
        build_context=".", startup_timeout=5.0, **kw,
    )


def test_create_returns_env_info_and_posts_start():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)

        async def run():
            info = await prov.create("e1", EnvConfig())
            assert info.status == EnvStatus.READY
            assert info.gateway_address == "http://127.0.0.1:9000"
            assert rec.start[0]["env_id"] == "e1"
            assert rec.start[0]["gateway_port"] == 9000
            assert rec.start[0]["image_key"] == "default"

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_destroy_posts_stop_and_frees_port():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)

        async def run():
            await prov.create("e1", EnvConfig())
            assert await prov.destroy("e1") is True
            assert rec.stop[0]["env_id"] == "e1"
            # Port freed -> reused by the next create.
            info2 = await prov.create("e2", EnvConfig())
            assert info2.gateway_address == "http://127.0.0.1:9000"

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_distinct_ports_for_concurrent_envs():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)

        async def run():
            i1 = await prov.create("e1", EnvConfig())
            i2 = await prov.create("e2", EnvConfig())
            assert i1.gateway_address != i2.gateway_address
            ports = {s["gateway_port"] for s in rec.start}
            assert ports == {9000, 9001}

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_port_exhaustion_raises():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port, port_range=1)

        async def run():
            await prov.create("e1", EnvConfig())
            raised = False
            try:
                await prov.create("e2", EnvConfig())
            except RuntimeError:
                raised = True
            assert raised

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_failed_start_frees_port():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)
        rec.fail_start = True

        async def run():
            raised = False
            try:
                await prov.create("e1", EnvConfig())
            except RuntimeError:
                raised = True
            assert raised
            # Port must be released so a retry reuses 9000.
            rec.fail_start = False
            info = await prov.create("e2", EnvConfig())
            assert info.gateway_address == "http://127.0.0.1:9000"

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_reset_and_health_check():
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)

        async def run():
            await prov.create("e1", EnvConfig())
            assert await prov.reset("e1") is True
            assert rec.reset[0]["env_id"] == "e1"
            assert await prov.health_check("e1") is True
            assert rec.health

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_control_port_vars_forwarded_to_worker():
    """The aux control-port templates from EnvConfig must reach /env/start so the
    worker can allocate + inject them (this is the R2E control-proxy wiring; if it
    silently drops, the gateway loses its sidecar and the env is unusable)."""
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)
        cfg = EnvConfig(control_port_vars={
            "R2E_CONTROL_PORT": "{port}",
            "GATEWAY_CONTROL_PROXY_URL": "http://localhost:{port}",
        })

        async def run():
            await prov.create("e1", cfg)
            assert rec.start[0]["control_port_vars"] == {
                "R2E_CONTROL_PORT": "{port}",
                "GATEWAY_CONTROL_PROXY_URL": "http://localhost:{port}",
            }

        asyncio.run(run())
    finally:
        srv.shutdown()


def test_no_control_port_vars_sends_none():
    """A plain EnvConfig must forward control_port_vars=None (not {}), so the
    worker takes its task-agnostic path and allocates no aux port."""
    rec = _Rec()
    srv, port = _serve(rec)
    try:
        prov = _prov(port)

        async def run():
            await prov.create("e1", EnvConfig())
            assert rec.start[0]["control_port_vars"] is None

        asyncio.run(run())
    finally:
        srv.shutdown()
