"""
The application gateway for MCP servers.
Redesigned for high-concurrency RL training scenarios.
"""
# pylint: disable=broad-exception-caught,protected-access,no-value-for-parameter
import asyncio
import copy
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import uuid
import multiprocessing
from collections import defaultdict
from contextlib import closing, AsyncExitStack, asynccontextmanager
from typing import List, Optional, Dict

import anyio
import click
import uvicorn
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from mcp import stdio_client, StdioServerParameters
from mcp.server.sse import SseServerTransport
from mcpuniverse.common.logger import get_logger
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.mcp.client import safe_sse_client, is_safe_cleanup_error
from mcpuniverse.mcp.config import ServerConfig
from mcpuniverse.mcp.manager import MCPManager


class ServerConnector(metaclass=AutodocABCMeta):
    """
    Connect to another MCP server.
    Improved for high-concurrency scenarios for SSE transport.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self._logger = get_logger(self.__class__.__name__)
        self._read_stream = None
        self._write_stream = None
        self._last_activity: float = 0.0
        self._idle_timed_out: bool = False

    async def cleanup(self):
        """Clean up client resources."""
        async with self._cleanup_lock:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                # Distinguish between safe errors (asyncio cancellation etc.) and errors that require real attention
                error_msg = str(e)
                if "cancel scope" in error_msg.lower() or "Attempted to exit" in error_msg:
                    self._logger.debug("Cleanup completed with minor asyncio warning (safe to ignore): %s", error_msg)
                else:
                    self._logger.error("Error during cleanup of server connector: %s", str(e))

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server via SSE with improved error handling."""
        # Retry mechanism: up to 5 retries, using exponential backoff strategy
        max_retries = 5
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                # Wait before retry (except first attempt)
                if attempt > 0:
                    wait_time = retry_delay * (1.5 ** attempt)
                    self._logger.debug(
                        "Waiting %.1f seconds before retry (attempt %d/%d)...",
                        wait_time, attempt + 1, max_retries
                    )
                    await asyncio.sleep(wait_time)

                self._logger.debug(
                    "Attempting to connect to SSE server: %s (attempt %d/%d)",
                    server_url, attempt + 1, max_retries
                )
                # Use longer timeouts for Gateway -> MCP server connections
                sse_transport = await self._exit_stack.enter_async_context(
                    safe_sse_client(
                        server_url,
                        logger=self._logger,
                        timeout=60.0,  # HTTP timeout for POST operations
                        sse_read_timeout=600.0  # SSE read timeout (10 minutes)
                    )
                )
                self._read_stream, self._write_stream = sse_transport
                self._logger.debug("Successfully connected to SSE server: %s", server_url)
                return
            except Exception as e:
                error_msg = str(e)
                error_traceback = traceback.format_exc()

                is_taskgroup_error = (
                    "TaskGroup" in error_msg or
                    "unhandled errors" in error_msg.lower() or
                    "sub-exception" in error_msg.lower()
                )

                if is_taskgroup_error:
                    if attempt < max_retries - 1:
                        self._logger.warning(
                            "TaskGroup error during SSE connection (attempt %d/%d): %s\n"
                            "Traceback:\n%s\n"
                            "This usually means the MCP server process is not running or not ready. Retrying...",
                            attempt + 1, max_retries, error_msg, error_traceback
                        )
                        continue
                    self._logger.error(
                        "TaskGroup error persisted after %d attempts: %s\n"
                        "Traceback:\n%s\n"
                        "The MCP server process may not be running or may have crashed.",
                        max_retries, error_msg, error_traceback
                    )
                    await self.cleanup()
                    raise ConnectionError("Connection closed: MCP server process may not be running") from e

                self._logger.error(
                    "Failed to initialize sse client in server connector: %s\n"
                    "Traceback:\n%s",
                    error_msg, error_traceback
                )
                await self.cleanup()
                raise ConnectionError("Connection closed") from e

    async def connect_to_stdio_server(self, config: ServerConfig):
        """Initializes a connection to an MCP server using stdio transport."""
        command = (
            shutil.which(config.stdio.command)
            if config.stdio.command in ["npx", "docker", "python", "python3"]
            else config.stdio.command
        )
        if command is None or command == "":
            raise ValueError("The command must be a valid string")

        envs = dict(os.environ)
        envs.update(config.env)
        server_params = StdioServerParameters(
            command=command,
            args=config.stdio.args,
            env=envs
        )
        try:
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self._read_stream, self._write_stream = stdio_transport
        except Exception as e:
            self._logger.error("Failed to initialize stdio client in server connector: %s", str(e))
            await self.cleanup()
            raise e

    async def _send(self, read_stream: MemoryObjectReceiveStream):
        """Reads requests from read_stream and sends them to the MCP server."""
        try:
            async with (
                read_stream,
                self._write_stream,
            ):
                async for message in read_stream:
                    self._last_activity = time.monotonic()
                    await self._write_stream.send(message)
        except Exception as e:
            error_msg = str(e)
            if "cancel scope" not in error_msg.lower() and "Attempted to exit" not in error_msg:
                self._logger.debug("Send stream closed: %s", error_msg)
            raise

    async def _receive(self, write_stream: MemoryObjectSendStream):
        """Reads responses from the MCP server and sends them to the output stream."""
        try:
            async with (
                write_stream,
                self._read_stream,
            ):
                async for message in self._read_stream:
                    self._last_activity = time.monotonic()
                    # stdio servers sometimes print non-JSON-RPC lines to stdout
                    # (startup banners, logs, warnings). The MCP stdio reader
                    # surfaces those as parse-error Exceptions on this stream.
                    # Forwarding them to the SSE client crashes the proxy and
                    # closes the connection, so drop them and keep the session
                    # alive (be liberal in what we accept). Real protocol errors
                    # arrive as valid JSON-RPC error responses, not Exceptions.
                    if isinstance(message, Exception):
                        self._logger.debug(
                            "Dropping non-JSON-RPC stdout from MCP server: %s", message
                        )
                        continue
                    await write_stream.send(message)
        except Exception as e:
            error_msg = str(e)
            if "cancel scope" not in error_msg.lower() and "Attempted to exit" not in error_msg:
                self._logger.debug("Receive stream closed: %s", error_msg)
            raise

    async def _idle_watchdog(self, tg: anyio.abc.TaskGroup, idle_timeout: float):
        """Cancel the task group if no message activity for idle_timeout seconds."""
        check_interval = min(30.0, idle_timeout / 2)
        while True:
            await anyio.sleep(check_interval)
            elapsed = time.monotonic() - self._last_activity
            if elapsed >= idle_timeout:
                self._logger.info(
                    "Connection idle for %.0f seconds (threshold: %.0f), closing",
                    elapsed, idle_timeout
                )
                self._idle_timed_out = True
                tg.cancel_scope.cancel()
                return

    async def run(
            self,
            read_stream: MemoryObjectReceiveStream,
            write_stream: MemoryObjectSendStream,
            idle_timeout: Optional[float] = None,
    ):
        """Redirect requests from read_stream to the MCP server and write responses to write_stream."""
        self._last_activity = time.monotonic()
        self._idle_timed_out = False
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self._send, read_stream)
                tg.start_soon(self._receive, write_stream)
                if idle_timeout is not None:
                    tg.start_soon(self._idle_watchdog, tg, idle_timeout)
        except Exception as e:
            # Check if it's a safe cleanup error
            if is_safe_cleanup_error(e):
                self._logger.debug("Task group closed (non-fatal): %s", str(e))
                raise ConnectionError("Connection closed") from e
            # Check ExceptionGroup
            if hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
                safe_errors = [exc for exc in e.exceptions if is_safe_cleanup_error(exc)]
                other_errors = [exc for exc in e.exceptions if not is_safe_cleanup_error(exc)]
                if not other_errors:
                    self._logger.debug("Task group closed (non-fatal): %d safe error(s)", len(safe_errors))
                    raise ConnectionError("Connection closed") from e
                if len(other_errors) == 1:
                    raise other_errors[0]
            raise

        if self._idle_timed_out:
            raise ConnectionError("Connection idle timeout")


class Gateway(metaclass=AutodocABCMeta):
    """
    High-performance gateway for MCP servers.
    
    Features:
    1. Connection pool management - 
       Tracks and manages the number of active connections per server 
       to support high concurrency scenarios (default: 10,000 connections).
    2. Request queue management -
       Uses semaphores to control concurrent request counts
       and prevent server overload.
    3. Server readiness waiting -
       Waits for servers to become fully ready
       before proceeding with further operations.
    4. Improved startup process -
       Includes more detailed logging and robust error handling.    
    """
    def __init__(
        self,
        mcp_manager: MCPManager,
        max_connections_per_server: int = 10000,  # High limit for high-concurrency training (soft limit with warnings)
        max_concurrent_requests: int = 200,  # limit concurrent requests
        idle_timeout: Optional[float] = 300.0,  # 5 minutes, None to disable
    ):
        self._mcp_manager = mcp_manager
        self._server_configs = mcp_manager.get_configs()
        self._processes = {}
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self._logger = get_logger(self.__class__.__name__)
        self._idle_timeout = idle_timeout

        # Connection pool management - track connection counts
        self._max_connections_per_server = max_connections_per_server
        self._active_connections: Dict[str, int] = defaultdict(int)
        self._connection_lock: Dict[str, asyncio.Lock] = {}
        self._connection_lock_init = asyncio.Lock()

        # Request queue management - limit concurrent requests
        self._max_concurrent_requests = max_concurrent_requests
        self._request_semaphore: Dict[str, asyncio.Semaphore] = {}
        self._semaphore_init_lock = asyncio.Lock()

    async def _get_connection_lock(self, server_name: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for the given server, using double-check locking."""
        if server_name not in self._connection_lock:
            async with self._connection_lock_init:
                if server_name not in self._connection_lock:
                    self._connection_lock[server_name] = asyncio.Lock()
        return self._connection_lock[server_name]

    async def _get_request_semaphore(self, server_name: str) -> asyncio.Semaphore:
        """Get or create an asyncio.Semaphore for the given server, using double-check locking."""
        if server_name not in self._request_semaphore:
            async with self._semaphore_init_lock:
                if server_name not in self._request_semaphore:
                    self._request_semaphore[server_name] = asyncio.Semaphore(
                        self._max_concurrent_requests
                    )
        return self._request_semaphore[server_name]

    def _terminate_process(self, name: str, process: multiprocessing.Process) -> None:
        """Terminate a single process safely."""
        # Check if process is alive
        try:
            is_alive = process.is_alive()
        except (AttributeError, ValueError, OSError) as check_error:
            self._logger.debug("Cannot check if process %s is alive: %s", name, str(check_error))
            return

        if not is_alive:
            return

        # Terminate the process
        try:
            process.terminate()
            process.join(timeout=2.0)
            # Force kill if still alive
            if process.is_alive():
                self._logger.warning("Server %s process did not terminate gracefully, killing it", name)
                process.kill()
                process.join(timeout=1.0)
        except (AttributeError, ValueError, OSError) as terminate_error:
            self._logger.debug("Error terminating process %s: %s", name, str(terminate_error))

    async def cleanup(self):
        """Clean up resources."""
        for name, p in self._processes.items():
            try:
                process = p.get("process", None)
                if process is None:
                    continue

                if not isinstance(process, multiprocessing.Process):
                    continue

                self._terminate_process(name, process)
            except Exception as e:
                self._logger.error("Error during cleanup of server %s: %s", name, str(e))

        self._processes = {}
        self._active_connections.clear()

    def _find_available_port(self, start_port=10000, end_port=65535) -> int:
        """Finds a free port number.

        Uses a linear scan instead of binding to port 0 (OS-assigned) so that
        the gateway can avoid ports already claimed by other servers in the
        same process and ensure deterministic, non-overlapping allocation.
        """
        used_ports = set(p["port"] for _, p in self._processes.items() if "port" in p)
        for port in range(start_port, end_port + 1):
            if port in used_ports:
                continue
            try:
                with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                    s.bind(("", port))
                    return port
            except Exception:
                continue
        return -1

    def init_sse_server(self, server_name: str):
        """Initializes an SSE server corresponding to the server name."""
        assert server_name in self._server_configs, f"Unknown server: {server_name}"
        if server_name in self._processes:
            return self._processes[server_name]

        config = copy.deepcopy(self._server_configs[server_name])
        if config.sse.command == "":
            raise RuntimeError(f"Server {server_name} does not support SSE")

        port = self._find_available_port()
        if port < 0:
            raise RuntimeError("Cannot find free port")
        config.render_template(params={"PORT": port})
        if config.list_unspecified_params():
            raise RuntimeError(f"Server {server_name} has unspecified parameters: "
                               f"{config.list_unspecified_params()}")

        process = multiprocessing.Process(target=run_server, args=(config.sse.command, config.sse.args))
        self._processes[server_name] = {
            "process": process,
            "port": port,
            "url": f"http://localhost:{port}/sse"
        }
        self._processes[server_name]["routes"] = self._build_sse_routes(server_name)

    def init_stdio_server(self, server_name: str):
        """Initializes a Stdio server corresponding to the server name."""
        assert server_name in self._server_configs, f"Unknown server: {server_name}"
        if server_name in self._processes:
            return self._processes[server_name]

        config = copy.deepcopy(self._server_configs[server_name])
        self._processes[server_name] = {
            "routes": self._build_stdio_routes(server_name, config)
        }

    def _wait_for_server_ready(self, server_name: str, port: int, timeout: float = 60.0) -> bool:
        """
        Wait for a server to be ready by checking if it's listening on the port.

        Uses a synchronous socket connect_ex check, which is sufficient to determine
        whether the server process has started accepting TCP connections.
        """
        start_time = time.time()
        check_interval = 0.5

        while time.time() - start_time < timeout:
            # Check if process is still alive first
            if server_name in self._processes:
                process = self._processes[server_name].get("process", None)
                if process and not process.is_alive():
                    exit_code = process.exitcode
                    self._logger.error(
                        "Server %s process died before becoming ready (exit code: %d)",
                        server_name, exit_code
                    )
                    return False

            # Check port connectivity via synchronous socket probe
            try:
                with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                    s.settimeout(1.0)
                    result = s.connect_ex(("localhost", port))
                    if result == 0:
                        self._logger.info("Server %s is ready on port %d", server_name, port)
                        return True
            except Exception:
                pass

            time.sleep(check_interval)

        self._logger.warning("Server %s did not become ready within %.1f seconds", server_name, timeout)
        return False

    def start_servers(
        self,
        join: bool = True,
        wait_for_ready: bool = True,
        ready_timeout: float = 60.0
    ):
        """
        Starts the initialized MCP servers.

        Args:
            join: Whether to do multiprocessing join.
            wait_for_ready: Whether to wait for servers to be ready before returning.
            ready_timeout: Maximum time to wait for servers to be ready in seconds (increased to 60s).
        """
        # Start all server processes first
        for name, p in self._processes.items():
            if "process" in p:
                self._logger.info("Starting the MCP server %s with port %d", name, p["port"])
                p["process"].start()
                # Give process a moment to start
                time.sleep(1.0)

                # Immediately check if process is still alive
                if not p["process"].is_alive():
                    exit_code = p["process"].exitcode
                    self._logger.error(
                        "Server %s process died immediately after start (exit code: %d). "
                        "This usually indicates a startup error. Please check server logs.",
                        name, exit_code
                    )
                    # Try to get any error output if possible
                    # Note: multiprocessing.Process doesn't capture output by default
                    # The error should be in the process's stderr, which goes to gateway's stderr

        if wait_for_ready:
            self._logger.info("Waiting for servers to be ready (timeout: %.1f seconds)...", ready_timeout)
            all_ready = True
            for name, p in self._processes.items():
                if "process" in p:
                    port = p["port"]
                    if not self._wait_for_server_ready(name, port, timeout=ready_timeout):
                        all_ready = False
                        self._logger.error(
                            "Server %s failed to become ready within %.1f seconds. "
                            "Clients may experience connection errors.",
                            name, ready_timeout
                        )
                        if not p["process"].is_alive():
                            exit_code = p["process"].exitcode
                            self._logger.error(
                                "Server %s process died with exit code %d. "
                                "Please check server logs for details.",
                                name, exit_code
                            )
                        else:
                            self._logger.warning(
                                "Server %s process is alive but not responding on port %d. "
                                "It may still be starting up.",
                                name, port
                            )

            if all_ready:
                self._logger.info("All servers are ready!")
            else:
                self._logger.warning(
                    "Some servers failed to become ready. "
                    "The gateway will continue running."
                )

        if join:
            for _, p in self._processes.items():
                if "process" in p:
                    p["process"].join()

    def _build_routes(self, server_name: str, connect_fn, pre_sse_connect=None, pre_sse_url=None) -> List:
        """
        Build Starlette routes with shared SSE transport, connection tracking,
        and error handling logic.

        Args:
            server_name: Name of the server.
            connect_fn: An async callable(connector) that establishes the upstream connection.
            pre_sse_connect: If provided, an async callable(connector) executed *before*
                entering the SSE context. Used by SSE transport to fail early.
            pre_sse_url: URL logged on pre-SSE connect failure (SSE transport only).
        """
        sse = SseServerTransport(f"/{server_name}/messages/")

        async def handle_sse(request):
            """Handle SSE connection requests."""
            conn_lock = await self._get_connection_lock(server_name)
            async with conn_lock:
                current_count = self._active_connections[server_name]
                if current_count >= self._max_connections_per_server:
                    self._logger.warning(
                        "High connection count for %s: %d", server_name, current_count
                    )
                elif current_count > 0 and current_count % 100 == 0:
                    self._logger.info("Active connections for %s: %d", server_name, current_count)

            connection_id = str(uuid.uuid4())[:8]
            connection_start_time = time.time()

            semaphore = await self._get_request_semaphore(server_name)
            async with semaphore:
                connector = ServerConnector()
                connection_count_incremented = False

                # Optional pre-SSE connect (used by SSE transport to fail early)
                if pre_sse_connect is not None:
                    try:
                        await pre_sse_connect(connector)
                    except Exception as e:
                        error_msg = str(e)
                        self._logger.error(
                            "Failed to connect to MCP server %s at %s: %s",
                            server_name, pre_sse_url or "unknown", error_msg
                        )
                        return JSONResponse(
                            status_code=503,
                            content={"error": f"Failed to connect to MCP server: {error_msg}"}
                        )

                try:
                    async with sse.connect_sse(
                            request.scope, request.receive, request._send
                    ) as streams:
                        # Increment connection count
                        conn_lock = await self._get_connection_lock(server_name)
                        async with conn_lock:
                            self._active_connections[server_name] += 1
                            connection_count_incremented = True

                        try:
                            await connect_fn(connector, streams)
                        except ConnectionError as ce:
                            self._logger.debug("SSE connection closed: %s", str(ce))
                            # Idle timeout must propagate so sse.connect_sse()
                            # exits with an exception instead of returning None
                            # (which causes Starlette NoneType error).
                            if connector._idle_timed_out:
                                raise
                        except Exception as e:
                            if is_safe_cleanup_error(e):
                                self._logger.debug("Safe error for %s: %s", server_name, str(e))
                            elif hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
                                if all(is_safe_cleanup_error(exc) for exc in e.exceptions):
                                    self._logger.debug("Safe ExceptionGroup for %s", server_name)
                                else:
                                    self._logger.warning("SSE error for %s: %s", server_name, e)
                            else:
                                self._logger.warning("SSE error for %s: %s", server_name, e)
                except Exception as e:
                    if is_safe_cleanup_error(e) or isinstance(e, ConnectionError):
                        self._logger.debug("SSE connection ended for %s: %s", server_name, str(e))
                    else:
                        self._logger.warning("SSE context error for %s: %s", server_name, e)
                    raise

                finally:
                    # Decrement connection count only if it was incremented
                    if connection_count_incremented:
                        conn_lock = await self._get_connection_lock(server_name)
                        async with conn_lock:
                            old_count = self._active_connections[server_name]
                            self._active_connections[server_name] = max(0, old_count - 1)
                            duration = time.time() - connection_start_time
                            self._logger.debug(
                                "Connection %s closed after %.1f seconds. "
                                "Active: %d → %d",
                                connection_id, duration, old_count, self._active_connections[server_name]
                            )

                    try:
                        await connector.cleanup()
                    except Exception as e:
                        if not is_safe_cleanup_error(e):
                            self._logger.debug("Cleanup warning: %s", e)

        routes = [
            Route(f"/{server_name}/sse", endpoint=handle_sse),
            Mount(f"/{server_name}/messages/", app=sse.handle_post_message),
        ]
        return routes

    def _build_sse_routes(self, server_name: str) -> List:
        """Builds Starlette routes for SSE transport."""
        if server_name not in self._processes:
            raise RuntimeError(f"Server {server_name} is not initialized.")
        server_url = self._processes[server_name]["url"]
        idle_timeout = self._idle_timeout

        async def connect_fn(connector, streams):
            await connector.run(streams[0], streams[1], idle_timeout=idle_timeout)

        async def pre_sse_connect(connector):
            await connector.connect_to_sse_server(server_url)

        return self._build_routes(
            server_name,
            connect_fn=connect_fn,
            pre_sse_connect=pre_sse_connect,
            pre_sse_url=server_url,
        )

    def _build_stdio_routes(self, server_name: str, config: ServerConfig) -> List:
        """Builds Starlette routes for Stdio transport."""
        idle_timeout = self._idle_timeout

        async def connect_fn(connector, streams):
            await connector.connect_to_stdio_server(config)
            await connector.run(streams[0], streams[1], idle_timeout=idle_timeout)

        return self._build_routes(server_name, connect_fn=connect_fn)

    def _build_control_proxy_routes(self) -> List:
        """Optionally reverse-proxy a path prefix to a sidecar control API.

        Generic single-entry-point routing: when ``GATEWAY_CONTROL_PROXY_URL``
        is set, the gateway forwards every request under
        ``GATEWAY_CONTROL_PROXY_PREFIX`` (default ``/control``) to that URL
        (prefix stripped), so a container that runs a separate control service
        alongside the MCP gateway is still reachable through the single
        published gateway port. This keeps the env-pool "one env = one address"
        model intact.

        Disabled by default: when the env var is unset (e.g. stateless RL
        envs) no route is registered and behaviour is unchanged.
        """
        control_url = os.environ.get("GATEWAY_CONTROL_PROXY_URL", "").strip().rstrip("/")
        if not control_url:
            return []
        prefix = os.environ.get("GATEWAY_CONTROL_PROXY_PREFIX", "/control").strip()
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        prefix = prefix.rstrip("/")
        timeout = float(os.environ.get("GATEWAY_CONTROL_PROXY_TIMEOUT", "960"))

        async def control_proxy(request):
            # Lazy import: httpx is only pulled in when the control proxy is enabled.
            import httpx  # pylint: disable=import-outside-toplevel
            sub_path = request.path_params.get("path", "")
            target = f"{control_url}/{sub_path}"
            if request.url.query:
                target = f"{target}?{request.url.query}"
            body = await request.body()
            fwd_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length")
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    upstream = await client.request(
                        request.method, target, content=body, headers=fwd_headers,
                    )
            except Exception as exc:  # surface as JSON so callers don't hit a decode error
                return JSONResponse(
                    {"ok": False, "error": f"control proxy error: {exc}"},
                    status_code=502,
                )
            hop_by_hop = {"content-length", "transfer-encoding", "connection"}
            out_headers = {
                k: v for k, v in upstream.headers.items()
                if k.lower() not in hop_by_hop
            }
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers=out_headers,
                media_type=upstream.headers.get("content-type"),
            )

        self._logger.info("Gateway control proxy enabled: %s/* -> %s", prefix, control_url)
        return [
            Route(
                f"{prefix}/{{path:path}}",
                endpoint=control_proxy,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
            )
        ]

    def build_starlette_app(
            self,
            mode: str = "stdio",
            servers: Optional[List[str]] = None,
            debug: bool = True
    ) -> Starlette:
        """Builds a Starlette app for the gateway."""
        assert mode in ["stdio", "sse"], "`mode` should be `stdio` or `sse`"

        if mode == "sse":
            for server_name, config in self._server_configs.items():
                if servers is not None and server_name not in servers:
                    continue
                if config.sse.command != "":
                    self.init_sse_server(server_name)
                else:
                    self.init_stdio_server(server_name)
            self.start_servers(join=False)
        else:
            for server_name, _ in self._server_configs.items():
                if servers is not None and server_name not in servers:
                    continue
                self.init_stdio_server(server_name)

        routes = []
        for server_name, process in self._processes.items():
            routes.extend(process["routes"])

        # Env-gated sidecar control proxy (no-op unless GATEWAY_CONTROL_PROXY_URL set)
        routes.extend(self._build_control_proxy_routes())

        @asynccontextmanager
        async def lifespan(_: Starlette):
            yield
            await self.cleanup()

        return Starlette(debug=debug, routes=routes, lifespan=lifespan)


def run_server(command, args):
    """
    Runs a shell command with improved error handling and logging.

    This function runs in a separate process, so errors here will cause the process to exit.
    The gateway does not currently implement automatic restart for failed server processes.
    """
    command = (
        shutil.which(command)
        if command in ["npx", "docker", "python", "python3"]
        else command
    )

    print(f"[MCP Server] Starting: {command} {' '.join(args)}", file=sys.stderr, flush=True)

    try:
        result = subprocess.run(
            [command] + args,
            shell=False,
            check=True,
            stdout=sys.stderr,  # Redirect stdout to stderr
            stderr=sys.stderr   # Keep stderr
        )
        return result
    except subprocess.CalledProcessError as e:
        # Log detailed error information
        print(f"[MCP Server] Process exited with code {e.returncode}", file=sys.stderr, flush=True)
        print(f"[MCP Server] Command: {e.cmd}", file=sys.stderr, flush=True)
        if e.stderr:
            print(f"[MCP Server] Stderr: {e.stderr}", file=sys.stderr, flush=True)
        if e.stdout:
            print(f"[MCP Server] Stdout: {e.stdout}", file=sys.stderr, flush=True)
        raise
    except KeyboardInterrupt:
        print("[MCP Server] Interrupted by user", file=sys.stderr, flush=True)
        raise
    except Exception as e:
        print(f"[MCP Server] Unexpected error: {e}", file=sys.stderr, flush=True)
        print(f"[MCP Server] Traceback:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        raise


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option("--config", default="", help="Server config file")
@click.option("--mode", default="stdio", help="Launch MCP clients via 'stdio' or 'sse'")
@click.option(
    "--servers",
    default=None,
    help="Comma-separated list of servers to use (empty string = no servers, omit = all servers)"
)
@click.option("--max-connections", default=10000, help="Max connections per server (default: 10000)")
@click.option("--max-concurrent-requests", default=200, help="Max concurrent requests per server (default: 200)")
@click.option("--idle-timeout", default=300, type=float,
              help="Idle timeout for SSE connections in seconds (default: 300, 0 to disable)")
def main(port: int, config: str, mode: str, servers: str, max_connections: int, max_concurrent_requests: int,
         idle_timeout: float):
    """Start the gateway server"""
    manager = MCPManager(config=config)
    gateway = Gateway(
        mcp_manager=manager,
        max_connections_per_server=max_connections,
        max_concurrent_requests=max_concurrent_requests,
        idle_timeout=idle_timeout if idle_timeout > 0 else None,
    )
    servers_list = [s.strip() for s in servers.split(",") if s.strip()] if servers is not None else None
    app = gateway.build_starlette_app(mode=mode, servers=servers_list)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
