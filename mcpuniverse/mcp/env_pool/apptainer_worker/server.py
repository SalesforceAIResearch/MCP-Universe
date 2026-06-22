"""Apptainer env worker control server (stdlib-only, no third-party deps).

Runs INSIDE a long-lived **privileged** worker container on each CPU pod.  The
``ApptainerProvisioner`` (in the rollouter process) drives the env lifecycle
over HTTP; ALL per-task container churn happens here, **daemon-less**, via
``apptainer run`` -- so dockerd never touches the per-task create/run/rm path.

Each env == one ``apptainer run --writable-tmpfs`` process:
  * read-only shared **base** from ``/sifs/<image_key>`` (sandbox dir or .sif),
  * ephemeral per-task **tmpfs overlay** (writes discarded on stop),
  * runs the image's own entrypoint (an MCP gateway, plus optionally a sidecar
    control API that uses the auxiliary port below).

Because apptainer shares the worker's network namespace, every env binds on the
worker's netns: the MCP gateway on a unique, externally-published
``gateway_port`` (the rollouter connects here) and, when the caller requests it,
an optional per-env **auxiliary/control port** on a unique internal port
(localhost-only).  Unique ports avoid the collision that a shared netns would
otherwise cause.

HTTP API (JSON request/response):
  GET  /healthz
  POST /env/start  {env_id, image_key, gateway_port, [startup_timeout], [env_vars]}
  POST /env/stop   {env_id}
  POST /env/reset  {env_id}
  GET  /env/health?env_id=...
"""
# Worker control script: the HTTP handler uses the stdlib do_GET/do_POST names,
# the env process + its log file are intentionally long-lived (not closed via
# ``with``), and every control path must swallow errors rather than crash the
# worker -- so the matching pylint checks are relaxed module-wide here.
# pylint: disable=broad-exception-caught,consider-using-with,invalid-name
# pylint: disable=protected-access,missing-function-docstring,missing-class-docstring

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Config (env-overridable so the worker image needs no rebuild to tune)
# ---------------------------------------------------------------------------
SIF_STORE = os.environ.get("SIF_STORE", "/sifs")
APPTAINER_BIN = os.environ.get("APPTAINER_BIN", "apptainer")
# Internal (localhost-only) range for an optional per-env auxiliary control port.
CTRL_PORT_BASE = int(os.environ.get("APPTAINER_CTRL_PORT_BASE", "21000"))
CTRL_PORT_SPAN = int(os.environ.get("APPTAINER_CTRL_PORT_SPAN", "2000"))
DEFAULT_STARTUP_TIMEOUT = float(os.environ.get("APPTAINER_STARTUP_TIMEOUT", "180"))
USE_PID_NS = os.environ.get("APPTAINER_PID_NS", "1") not in ("0", "false", "False")
LOG_DIR = os.environ.get("APPTAINER_ENV_LOG_DIR", "/tmp/apptainer_envs")
# Max time to wait for a recycled gateway port to be released by a just-stopped
# env's container before (a) reusing it on start or (b) reporting stop done.
# Prevents the port-reuse race where a new env routes to a stale wrong-repo
# container still holding the port (see _wait_port_free / start / stop).
PORT_FREE_TIMEOUT = float(os.environ.get("APPTAINER_PORT_FREE_TIMEOUT", "30"))
# Extra runtime ``apptainer run --bind`` mounts (comma-separated ``src:dst``
# pairs). Lets us patch files baked into already-staged SIFs WITHOUT rebuilding
# them -- e.g. patching a staged image's entrypoint or a sidecar with fixed
# copies on the shared SIF store. ``src`` must be readable inside this
# worker container (the SIF store at /sifs is always mounted, so put overrides
# there, e.g. /sifs/_overrides/...). Binds whose ``src`` is missing are skipped
# (so a stale/partial override dir can never wedge every env start).
def _resolve_binds(spec: str):
    out = []
    for b in spec.split(","):
        b = b.strip()
        if not b:
            continue
        src = b.split(":", 1)[0]
        if os.path.exists(src):
            out.append(b)
        else:
            print(f"[apptainer-worker] WARN: skipping bind (src missing): {b}", flush=True)
    return out


EXTRA_BINDS = _resolve_binds(os.environ.get("APPTAINER_EXTRA_BINDS", ""))

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_name(env_id: str) -> str:
    return _SAFE.sub("_", env_id)[:128]


# No-proxy opener: env http_proxy/https_proxy must NEVER be used for the
# loopback gateway check (a proxy would intercept localhost and break readiness).
_NOPROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _gateway_ready(port: int, timeout: float = 3.0) -> bool:
    """Match DockerProvisioner readiness (socket open + HTTP ``/`` < 500).

    The MCP gateway binds its port only after "all servers are ready" and has
    no ``/health`` route, so: (1) a TCP connect to 127.0.0.1:port confirms it's
    listening (proxy-immune), and (2) a GET ``/`` returning ``status < 500``
    (e.g. 404) confirms it's serving.  Uses 127.0.0.1 + a no-proxy opener so a
    corporate ``http_proxy`` in the env can't break the loopback check.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except OSError as e:
        if os.environ.get("APPTAINER_WORKER_DEBUG"):
            print(f"[gw_ready] socket {port} fail: {e!r}", flush=True)
        return False
    try:
        with _NOPROXY_OPENER.open(
            f"http://127.0.0.1:{port}/", timeout=timeout
        ) as resp:  # nosec - loopback
            return resp.status < 500
    except urllib.error.HTTPError as e:  # 4xx (incl. 404) == serving
        return e.code < 500
    except Exception as e:  # noqa: BLE001 - connection error / timeout == not ready
        if os.environ.get("APPTAINER_WORKER_DEBUG"):
            print(f"[gw_ready] http {port} fail: {e!r}", flush=True)
        return False


def _port_listening(port: int, timeout: float = 0.3) -> bool:
    """True if something is accepting TCP connections on 127.0.0.1:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_port_free(port: int, timeout: float) -> bool:
    """Poll until 127.0.0.1:port has no listener. Returns True once free.

    A connection-refused is immediate, so the common case (port already free)
    returns on the first probe with ~zero latency; it only actually waits when a
    straggler container still holds the recycled port.
    """
    deadline = time.time() + max(0.0, timeout)
    while True:
        if not _port_listening(port):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.1)


def _kill_listeners_on_port(port: int) -> None:
    """Best-effort SIGKILL of whatever process still holds *port* (a straggler).

    The previous tenant's env was already removed from bookkeeping, so anything
    still listening here is an orphan -- safe to kill. Uses ss then lsof; both
    are best-effort (absent tool / parse miss just no-ops).
    """
    pids: set[str] = set()
    try:
        out = subprocess.run(
            ["ss", "-Hltnp"], capture_output=True, text=True, timeout=5, check=False,
        ).stdout
        for ln in out.splitlines():
            if f":{port} " in ln or ln.rstrip().endswith(f":{port}"):
                m = re.search(r"pid=(\d+)", ln)
                if m:
                    pids.add(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    if not pids:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
            pids.update(p for p in out.split() if p.isdigit())
        except Exception:  # noqa: BLE001
            pass
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass


@dataclass
class EnvRec:
    env_id: str
    image_key: str
    gateway_port: int
    control_port: Optional[int]   # optional aux internal port (None if not requested)
    base: str
    proc: subprocess.Popen
    log_path: str
    created_at: float = field(default_factory=time.time)
    control_port_vars: Optional[dict] = None  # name->template the aux port was injected under


class ApptainerEnvManager:
    """Manages the lifecycle of per-task apptainer env processes."""

    def __init__(self, sif_store: str = SIF_STORE):
        self.sif_store = sif_store
        self._envs: Dict[str, EnvRec] = {}
        self._used_ctrl_ports: set[int] = set()
        self._lock = threading.Lock()
        os.makedirs(LOG_DIR, exist_ok=True)

    # -- base resolution ---------------------------------------------------
    def resolve_base(self, image_key: str) -> str:
        """Return the base path for *image_key* (sandbox dir preferred, else .sif)."""
        key = _safe_name(image_key)
        sandbox = os.path.join(self.sif_store, key, "rootfs")
        if os.path.isdir(sandbox):
            return sandbox
        sif = os.path.join(self.sif_store, key, "image.sif")
        if os.path.isfile(sif):
            return sif
        # Also accept a bare <key>.sif at the store root.
        flat = os.path.join(self.sif_store, key + ".sif")
        if os.path.isfile(flat):
            return flat
        raise FileNotFoundError(
            f"No staged base for image_key={image_key!r} under {self.sif_store} "
            f"(looked for {sandbox}, {sif}, {flat})"
        )

    def _alloc_ctrl_port(self) -> int:
        for off in range(CTRL_PORT_SPAN):
            port = CTRL_PORT_BASE + off
            if port not in self._used_ctrl_ports:
                self._used_ctrl_ports.add(port)
                return port
        raise RuntimeError("No free control ports")

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        env_id: str,
        image_key: str,
        gateway_port: int,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        env_vars: Optional[Dict[str, str]] = None,
        control_port_vars: Optional[Dict[str, str]] = None,
    ) -> dict:
        # Idempotent: tear down any stale env first. stop() does the slow kill
        # OUTSIDE the manager lock, so this never serializes concurrent starts.
        self.stop(env_id)
        # Defense-in-depth against the gateway-port reuse race: a just-destroyed
        # env's container may still hold this recycled port. If we launched now,
        # our gateway would fail to bind (EADDRINUSE) while _gateway_ready() is
        # fooled by the stale container -> the agent would talk to the WRONG repo.
        # Normally the port is already free (instant check); only wait/kill if a
        # straggler lingers, and refuse to start onto a port we can't free.
        if not _wait_port_free(gateway_port, PORT_FREE_TIMEOUT):
            _kill_listeners_on_port(gateway_port)
            if not _wait_port_free(gateway_port, 2.0):
                raise RuntimeError(
                    f"gateway port {gateway_port} still held by a stale env; "
                    f"refusing to start {env_id} (would route to the wrong repo)"
                )
        with self._lock:
            base = self.resolve_base(image_key)
            # Allocate a generic auxiliary internal port ONLY if the caller asked
            # for one (control_port_vars). Shared netns -> it must be unique, and
            # only the worker knows which ports are free, so the worker allocates
            # it while the caller supplies the env-var name(s) + value template(s).
            # This keeps the worker task-agnostic (no task-specific names baked in).
            ctrl_port = self._alloc_ctrl_port() if control_port_vars else None

        # NOTE: do NOT override HOME via --env (apptainer forbids
        # APPTAINERENV_HOME); --no-home keeps the image's /root so the gateway
        # stack on the system python's user-site resolves.
        # Cap per-env math-library threads. numpy/pandas/scipy/sklearn default
        # their OpenBLAS/MKL/OpenMP pools to the host CPU count (e.g. 96); with
        # dozens of concurrent envs that is catastrophic oversubscription
        # (observed loadavg ~2257 on 96 cores -> every test/eval suite ~25x
        # slower -> suites exceed their timeout -> reward 0 across the whole
        # batch). Pin to a small value so N envs cost ~N*threads, not N*96.
        # Caller-supplied env_vars (below) still win on collision.
        _threads = os.environ.get("APPTAINER_ENV_THREADS", "1")
        env_pairs = {
            "MCP_GATEWAY_PORT": str(gateway_port),
            "OMP_NUM_THREADS": _threads,
            "OPENBLAS_NUM_THREADS": _threads,
            "MKL_NUM_THREADS": _threads,
            "NUMEXPR_NUM_THREADS": _threads,
            "VECLIB_MAXIMUM_THREADS": _threads,
            "BLIS_NUM_THREADS": _threads,
        }
        # Inject the aux port under the caller-supplied names, formatting {port}
        # into each value template (e.g. a task config maps a name to "{port}" or
        # "http://localhost:{port}"; the names are supplied by config, not here).
        if ctrl_port is not None:
            for _name, _tmpl in control_port_vars.items():
                try:
                    env_pairs[str(_name)] = str(_tmpl).format(port=ctrl_port)
                except (KeyError, IndexError, ValueError):
                    env_pairs[str(_name)] = str(_tmpl)
        if env_vars:
            env_pairs.update({str(k): str(v) for k, v in env_vars.items()})
        env_arg = ",".join(f"{k}={v}" for k, v in env_pairs.items())

        cmd = [APPTAINER_BIN, "run", "--writable-tmpfs", "--no-home"]
        if USE_PID_NS:
            cmd.append("--pid")
        for b in EXTRA_BINDS:
            cmd += ["--bind", b]
        cmd += ["--env", env_arg, base]

        log_path = os.path.join(LOG_DIR, f"{_safe_name(env_id)}.log")
        logf = open(log_path, "wb")  # noqa: SIM115 - kept open for the proc lifetime
        # start_new_session => own process group, so stop() can kill the whole tree.
        proc = subprocess.Popen(
            cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True,
        )

        rec = EnvRec(
            env_id=env_id, image_key=image_key, gateway_port=gateway_port,
            control_port=ctrl_port, base=base, proc=proc, log_path=log_path,
            control_port_vars=control_port_vars,
        )
        with self._lock:
            self._envs[env_id] = rec

        # Wait for the MCP gateway to start serving on the worker's netns.
        deadline = time.time() + float(startup_timeout)
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = self._log_tail(log_path)
                self.stop(env_id)
                raise RuntimeError(
                    f"apptainer env {env_id} exited early (rc={proc.returncode}); "
                    f"log tail:\n{tail}"
                )
            if _gateway_ready(gateway_port):
                return {
                    "ok": True, "env_id": env_id, "gateway_port": gateway_port,
                    "control_port": ctrl_port, "base": base,
                }
            time.sleep(0.5)

        tail = self._log_tail(log_path)
        self.stop(env_id)
        raise TimeoutError(
            f"apptainer env {env_id} gateway not ready in {startup_timeout}s; "
            f"log tail:\n{tail}"
        )

    def stop(self, env_id: str) -> bool:
        # Pop bookkeeping under the lock, then run the SLOW process teardown
        # (killpg + wait + apptainer mount cleanup) OUTSIDE the lock -- otherwise
        # N concurrent stops serialize on the lock (was the rollout bottleneck).
        with self._lock:
            rec = self._envs.pop(env_id, None)
            if rec is None:
                return False
            if rec.control_port is not None:
                self._used_ctrl_ports.discard(rec.control_port)
        _terminate(rec.proc)  # tmpfs overlay auto-discarded when apptainer exits
        # Don't report stopped until the gateway port is actually released. The
        # provisioner frees the port for reuse only after /env/stop returns, so
        # blocking here guarantees the port is never handed to a new env while our
        # (dying) container still holds it -> no stale wrong-repo routing.
        _wait_port_free(rec.gateway_port, PORT_FREE_TIMEOUT)
        return True

    def reset(self, env_id: str) -> dict:
        """Reset == discard overlay (pristine base) by restarting the env.

        Reuses the same gateway port so the rollouter's gateway_address stays
        valid across a reset.
        """
        with self._lock:
            rec = self._envs.get(env_id)
            if rec is None:
                raise KeyError(env_id)
            image_key, gateway_port = rec.image_key, rec.gateway_port
            control_port_vars = rec.control_port_vars
        return self.start(env_id, image_key, gateway_port,
                          control_port_vars=control_port_vars)

    def health(self, env_id: str) -> dict:
        with self._lock:
            rec = self._envs.get(env_id)
        if rec is None:
            return {"ok": False, "alive": False, "reason": "unknown env"}
        alive = rec.proc.poll() is None
        gw_ok = alive and _gateway_ready(rec.gateway_port)
        return {"ok": gw_ok, "alive": alive, "gateway_ok": gw_ok,
                "gateway_port": rec.gateway_port}

    def list_envs(self) -> list:
        with self._lock:
            return [
                {"env_id": r.env_id, "image_key": r.image_key,
                 "gateway_port": r.gateway_port, "alive": r.proc.poll() is None}
                for r in self._envs.values()
            ]

    @staticmethod
    def _log_tail(path: str, n: int = 25) -> str:
        try:
            with open(path, "r", errors="replace", encoding="utf-8") as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return "(no log)"


def _terminate(proc: subprocess.Popen, grace: float = 3.0) -> None:
    """Kill the whole process group of *proc* (SIGTERM then SIGKILL).

    apptainer ``run`` rarely exits on SIGTERM within a few seconds, so we fall
    back to SIGKILL quickly; the container's mount namespace (overlay + squashfs)
    is torn down automatically by the kernel when the process dies, so this is
    clean. Run OUTSIDE the manager lock (see ``stop``) so destroys parallelize.
    """
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    # Reap after SIGKILL so the process is truly gone (and its listening socket
    # released by the kernel) before returning -- callers recycle the gateway
    # port right after stop(), so returning while the proc still holds it is the
    # root cause of the wrong-repo port-reuse race.
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _apptainer_version() -> str:
    try:
        out = subprocess.run(
            [APPTAINER_BIN, "--version"], capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or out.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def make_handler(mgr: ApptainerEnvManager):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default stderr spam
            pass

        def _send(self, code: int, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"ok": True, "apptainer": _apptainer_version(),
                                 "sif_store": mgr.sif_store, "envs": mgr.list_envs()})
            elif self.path.startswith("/env/health"):
                q = parse_qs(urlparse(self.path).query)
                env_id = (q.get("env_id") or [""])[0]
                self._send(200, mgr.health(env_id))
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):  # noqa: N802
            try:
                body = self._read_json()
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"ok": False, "error": f"bad json: {e}"})
                return
            try:
                if self.path == "/env/start":
                    res = mgr.start(
                        env_id=body["env_id"],
                        image_key=body["image_key"],
                        gateway_port=int(body["gateway_port"]),
                        startup_timeout=float(body.get("startup_timeout",
                                                       DEFAULT_STARTUP_TIMEOUT)),
                        env_vars=body.get("env_vars"),
                        control_port_vars=body.get("control_port_vars"),
                    )
                    self._send(200, res)
                elif self.path == "/env/stop":
                    ok = mgr.stop(body["env_id"])
                    self._send(200, {"ok": ok})
                elif self.path == "/env/reset":
                    self._send(200, mgr.reset(body["env_id"]))
                else:
                    self._send(404, {"ok": False, "error": "not found"})
            except (KeyError, FileNotFoundError) as e:
                self._send(400, {"ok": False, "error": str(e)})
            except (RuntimeError, TimeoutError) as e:
                self._send(500, {"ok": False, "error": str(e)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Apptainer env worker control server")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("APPTAINER_WORKER_PORT", "8900")))
    parser.add_argument("--sif-store", default=SIF_STORE)
    args = parser.parse_args()

    mgr = ApptainerEnvManager(sif_store=args.sif_store)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(mgr))
    print(f"[apptainer-worker v3-socket] listening on :{args.port} "
          f"sif_store={args.sif_store} apptainer={_apptainer_version()}", flush=True)

    def _shutdown(*_):
        # NOTE: ThreadingHTTPServer.shutdown() blocks until serve_forever()
        # returns, so it must NOT run in the signal-handler thread (that would
        # deadlock).  Run it in a helper thread; env teardown happens in the
        # serve_forever() finally-block below.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        server.serve_forever()
    finally:
        for env in list(mgr._envs):  # noqa: SLF001
            mgr.stop(env)


if __name__ == "__main__":
    main()
