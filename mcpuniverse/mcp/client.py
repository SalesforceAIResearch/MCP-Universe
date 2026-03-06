"""
This module provides a client implementation for interacting with MCP (Model Control Protocol) servers.

It includes the MCPClient class, which offers methods to connect to MCP servers using either
stdio or SSE transport, list available tools, and execute tools on the server.

This version of client.py enhances the original by adding several features,
primarily tailored for distributed reinforcement learning training and
improved support for SSE transport:
1. Improved error handling:
   - `is_safe_cleanup_error()`: Identifies ignorable cleanup errors.
   - `is_connection_error_type()`: Identifies connection error types.
   - More fine-grained error categorization and handling.

2. Safe management of SSE connections:
   - `safe_sse_client()`: A safe wrapper for the SSE client that ensures proper cleanup.
   - Controls the `httpx.AsyncClient` lifecycle to avoid common errors during cleanup.

3. Enhanced retry mechanisms:
   - `connect_to_stdio_server()` and `connect_to_sse_server()` support retries.
   - Implements an exponential backoff strategy.
   - Checks server availability before attempting connection.

4. Timeout control:
   - `call_timeout` parameter: Controls timeout for a single tool call.
   - `execute_tool()` leverages `asyncio.wait_for()` to enforce timeout.

5. Connection configuration management:
   - `_connection_config` attribute: Stores connection configuration for reconnects.
   - Optional connection health checks.

6. Logging and debugging improvements:
   - More detailed and informative logging.
   - Suppresses noisy logs from the MCP SDK.
   - Clearer diagnostic messages for errors.

7. Optimizations for Ray/async environments:
   - Handles cancel scope errors gracefully.
   - Manages cross-task cleanup error handling.
"""
# pylint: disable=broad-exception-caught,too-many-lines
import asyncio
import logging
import os
import shutil
import traceback
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any, Optional, Union, List, Dict

import aiohttp
import httpx as _httpx
from dotenv import load_dotenv
from pydantic import BaseModel

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent

from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.mcp.config import ServerConfig
from mcpuniverse.common.logger import get_logger
from mcpuniverse.callbacks.base import (
    BaseCallback,
    CallbackMessage,
    MessageType,
    Status,
    Event,
    send_message
)
from mcpuniverse.mcp.permission import ToolPermission, check_permissions

# Suppress noisy ERROR logs from MCP SDK's SSE reader during intentional connection close.
# When we force-close the httpx client in safe_sse_client cleanup, sse_reader gets a ReadError
# and the SDK logs it at ERROR level. This is expected behavior, not an actual error.
logging.getLogger("mcp.client.sse").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv()


# Used to identify common non-fatal errors during async cleanup, especially in Ray/async environments
def is_safe_cleanup_error(error: Exception) -> bool:
    """
    Check if an error is a safe cleanup error that can be ignored.

    These errors commonly occur in async cleanup scenarios, especially when:
    - Cleanup happens in a different task than creation (Ray/async environments)
    - SSE connections are closed during context manager exit
    - Generators are stopped during cleanup
    - Concurrent cleanup calls cancel each other

    Args:
        error: The exception to check.

    Returns:
        True if the error is safe to ignore, False otherwise.
    """
    # Handle CancelledError - common during concurrent cleanup
    if isinstance(error, asyncio.CancelledError):
        return True

    error_msg = str(error).lower()
    error_type = type(error).__name__

    # Define patterns that indicate safe cleanup errors
    safe_patterns = [
        "cancel scope",
        "attempted to exit",
        "different task",
        "asynchronous generator",
        "no running event loop",
        "generator didn't stop",
        "generator didn't yield",
        "broken resource",
    ]

    # Check for pattern matches
    if any(pattern in error_msg for pattern in safe_patterns):
        return True

    # Check for generator cleanup errors
    if "generator" in error_msg and ("stop" in error_msg or "running" in error_msg):
        return True

    # Check for GeneratorExit type
    if error_type == "GeneratorExit":
        return True

    # Check for TaskGroup errors that are just cleanup noise
    if "taskgroup" in error_msg and "unhandled" in error_msg:
        return True

    return False


# Used to identify connection problems that require reconnection
def is_connection_error_type(error: Exception) -> bool:
    """
    Check if an error indicates a connection problem that requires reconnection.

    Args:
        error: The exception to check.

    Returns:
        True if this is a connection error, False otherwise.
    """
    error_msg = str(error).lower()
    error_type = type(error).__name__

    # Direct connection/timeout error types
    if error_type in ("ReadError", "ConnectError", "ConnectionError",
                      "ClosedResourceError", "BrokenPipeError",
                      "WriteTimeout", "ReadTimeout", "ConnectTimeout",
                      "TimeoutError", "WriteError"):
        return True

    # Error message patterns (including timeout patterns)
    connection_patterns = [
        "readerror", "connecterror", "connection closed", "connection reset",
        "broken pipe", "connection aborted", "connection lost", "closed",
        "writetimeout", "readtimeout", "connecttimeout", "timeout",
        "timed out", "write error", "network", "socket"
    ]

    return any(pattern in error_msg for pattern in connection_patterns)


# Used to check if the server URL is reachable before attempting SSE connection
async def _check_server_reachable(url: str, timeout: float = 5.0) -> bool:
    """
    Check if the server URL is reachable before attempting SSE connection.

    Args:
        url: Server URL to check (should be the full SSE endpoint URL)
        timeout: Timeout for the check

    Returns:
        True if server is reachable, False otherwise
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Directly check the SSE endpoint URL
            # For Gateway, the URL format is http://gateway:port/server_name/sse
            # We should check the actual SSE endpoint, not a base URL
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    # Accept 200 (OK) or other success status codes
                    # 404 means route doesn't exist, which is a real error
                    # But we'll be lenient and accept any non-5xx status
                    return response.status < 500
            except (aiohttp.ClientError, asyncio.TimeoutError):
                return False
    except Exception:
        # Any other error, assume server might be reachable to avoid false negatives
        return True


# Wrapper for sse_client that ensures proper cleanup of SSE connections
@asynccontextmanager
async def safe_sse_client(
    url: str,
    logger=None,
    timeout: float = 30.0,  # HTTP timeout for POST operations
    sse_read_timeout: float = 300.0  # SSE read timeout (5 minutes)
):
    """
    Wrapper for sse_client that ensures proper cleanup of SSE connections.

    Key design: creates and controls the httpx.AsyncClient lifecycle separately
    from the MCP SDK's sse_client generator. During cleanup:

    1. Force-close the httpx client FIRST → breaks the SSE HTTP stream
    2. The background sse_reader task gets a connection error and stops immediately
    3. The anyio TaskGroup inside sse_client can now exit cleanly
    4. Then close the sse_client generator (quick, since all I/O is dead)

    This prevents the common cleanup errors:
    - "generator didn't stop after athrow()" (from aconnect_sse trying to drain an infinite SSE stream)
    - "Attempted to exit cancel scope in a different task" (from dangling TaskGroup during GC)
    - "aclose(): asynchronous generator is already running" (from GC finalizer conflicts)

    Args:
        url: SSE server URL
        logger: Optional logger
        timeout: HTTP timeout for POST operations (default 30s, increased from MCP SDK default of 5s)
        sse_read_timeout: SSE read timeout (default 300s = 5 minutes)
    """

    # Create our own httpx client so we can forcefully close it during cleanup.
    # This is the key: by controlling the HTTP transport lifecycle, we can break
    # the SSE stream on demand, allowing the sse_reader background task to stop.
    _httpx_client = _httpx.AsyncClient(
        follow_redirects=True,
        timeout=_httpx.Timeout(timeout, read=sse_read_timeout),
    )

    @asynccontextmanager
    async def _controlled_factory(headers=None, timeout=None, auth=None, **kwargs):  # pylint: disable=unused-argument
        """Yield our pre-created httpx client. Does NOT close it on exit.

        sse_client's internal `async with httpx_client_factory(...) as client:` will
        use this factory. We intentionally skip closing here because we close the
        client ourselves in safe_sse_client's finally block (step 1 of cleanup).
        
        Note: We accept but ignore all parameters (headers, timeout, auth, etc.)
        because we've already created the httpx client with our desired configuration.
        """
        yield _httpx_client

    sse_gen = None

    try:
        sse_gen = sse_client(
            url=url,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
            httpx_client_factory=_controlled_factory,
        )
        transport = await sse_gen.__aenter__()
        yield transport
    except Exception as e:
        # Check if it's a safe error during entry
        if is_safe_cleanup_error(e):
            if logger:
                logger.debug("Safe error during SSE client entry: %s", str(e))
            # Still need to yield None or raise to avoid "generator didn't yield"
            raise
        if hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
            if all(is_safe_cleanup_error(exc) for exc in e.exceptions):
                if logger:
                    logger.debug("ExceptionGroup with safe errors during SSE client entry")
                raise
            raise
        raise
    finally:
        # Step 1: Force-close the httpx client.
        # This immediately breaks the SSE HTTP stream, causing the background
        # sse_reader task to get a connection error and exit. Without this step,
        # sse_reader would hang forever reading from the infinite SSE stream,
        # preventing the internal TaskGroup from exiting.
        try:
            await _httpx_client.aclose()
        except Exception:
            pass

        # Step 2: Close the sse_client generator.
        # Since the HTTP client is already dead, all pending I/O operations fail
        # immediately. The sse_reader stops, the TaskGroup exits, aconnect_sse
        # closes quickly, and the generator can be properly finalized.
        if sse_gen is not None:
            try:
                await sse_gen.__aexit__(None, None, None)
            except Exception as e:
                # All cleanup errors are non-fatal at this point.
                # The HTTP connection is already closed (step 1), so the server-side
                # resources are released regardless of whether the generator cleanup succeeds.
                if logger:
                    if is_safe_cleanup_error(e):
                        logger.debug("Safe cleanup error during SSE exit: %s", str(e))
                    else:
                        logger.debug("SSE generator cleanup error (non-fatal): %s", str(e))


class MCPClient(metaclass=AutodocABCMeta):
    """
    A client for interacting with MCP (Model Control Protocol) servers.

    This class provides methods to connect to MCP servers using either stdio or SSE transport,
    list available tools, and execute tools.
    """

    def __init__(self,
        name: str,
        permissions: Optional[List[Dict[str, str]]] = None,
        call_timeout: float = 60.0
    ):
        self._session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self._logger = get_logger(self.__class__.__name__)
        self._name = name
        self._call_timeout = call_timeout  # Timeout for individual tool calls (seconds)
        self._project_id = ""
        # Stdio context
        self._stdio_context: Union[Any, None] = None
        # Server parameters
        self._server_params = None
        # Connection config for reconnection
        # For stdio: ServerConfig
        # For SSE: {"url": str, "transport": "sse"}
        # For HTTP: {"url": str, "headers": dict, "transport": "http"}
        self._connection_config = None
        # Permissions
        self._permissions = None
        if permissions:
            self._permissions = [ToolPermission.model_validate(p) for p in permissions]

    async def _verify_connection(self, session: ClientSession, transport_type: str = "stdio"):
        """
        Verify connection by listing tools.

        Args:
            session: The ClientSession to verify
            transport_type: Type of transport ("stdio" or "sse") for logging purposes
        """
        try:
            await session.list_tools()
        except Exception as verify_error:
            # Ignore cancel scope errors during verification (these are non-fatal warnings)
            if "cancel scope" not in str(verify_error).lower():
                raise verify_error
            self._logger.debug(
                "Cancel scope warning during %s connection verification (safe to ignore)",
                transport_type
            )

    async def _cleanup_failed_attempt(self):
        """Clean up resources from a failed connection attempt."""
        await self.cleanup()
        self._exit_stack = AsyncExitStack()

    async def connect_to_stdio_server(
        self,
        config: ServerConfig,
        timeout: int = 20,
        retries: int = 3,
        retry_delay: float = 2.0
    ):
        """
        Initializes a connection to an MCP server using stdio transport.

        Args:
            config (ServerConfig): Configuration object containing server settings.
            timeout (int, optional): Connection timeout in seconds. Defaults to 20.
            retries (int, optional): Number of retry attempts. Defaults to 3.
            retry_delay (float, optional): Delay between retries in seconds. Defaults to 2.0.

        Raises:
            ValueError: If the command in the config is invalid.
            Exception: If the connection fails after all retries.

        Note:
            This method sets up the connection and initializes the client session.
        """
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

        # Retry mechanism: support multiple retry attempts for connection failures
        last_error = None
        for attempt in range(retries):
            try:
                # Clean up previous failed attempts
                if attempt > 0:
                    await self._cleanup_failed_attempt()

                stdio_transport = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read, write = stdio_transport
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout))
                )
                await session.initialize()

                # Connection verification: verify connection by listing tools
                await self._verify_connection(session, transport_type="stdio")

                self._session = session
                self._server_params = {
                    "command": server_params.command,
                    "args": server_params.args,
                    "env": envs
                }
                # Store connection config for reconnection
                self._connection_config = {"config": config, "transport": "stdio"}
                return  # Success
            except Exception as e:
                last_error = e
                self._logger.warning(
                    "Failed to initialize client %s (attempt %d/%d): %s",
                    self._name, attempt + 1, retries, str(e)
                )
                if attempt < retries - 1:
                    self._logger.info("Retrying in %.1f seconds...", retry_delay)
                    await asyncio.sleep(retry_delay)

        # All retries failed: error handling
        self._logger.error("Failed to initialize client %s after %d attempts: %s",
                          self._name, retries, str(last_error))
        await self.cleanup()
        raise last_error

    async def connect_to_sse_server(
        self,
        server_url: str,
        timeout: int = 20,
        retries: int = 5,
        retry_delay: float = 2.0
    ):
        """
        Connects to an MCP server using SSE (Server-Sent Events) transport.

        Args:
            server_url (str): The URL of the MCP server.
            timeout (int, optional): Connection timeout in seconds. Defaults to 20.
            retries (int, optional): Number of retry attempts. Defaults to 3.
            retry_delay (float, optional): Delay between retries in seconds. Defaults to 2.0.

        Raises:
            Exception: If the connection fails after all retries.

        Note:
            This method sets up the SSE connection and initializes the client session.
        """
        # Retry mechanism: support multiple retry attempts for connection failures
        last_error = None
        for attempt in range(retries):
            try:
                # Clean up previous failed attempts
                if attempt > 0:
                    await self._cleanup_failed_attempt()

                # Check if server is reachable before connecting (especially after failures)
                if attempt > 0:
                    # Exponential backoff: wait time increases gradually
                    wait_time = retry_delay * (1.5 ** attempt)  # Exponential backoff
                    self._logger.info(
                        "Waiting %.1f seconds before retry (attempt %d/%d)...",
                        wait_time, attempt + 1, retries
                    )
                    await asyncio.sleep(wait_time)

                    # Check if server is reachable
                    is_reachable = await _check_server_reachable(server_url, timeout=min(3.0, timeout))
                    if not is_reachable:
                        self._logger.warning(
                            "Server at %s is not reachable. "
                            "This usually means the MCP server process is not running or not ready. "
                            "Please check the gateway server status.",
                            server_url
                        )
                        # Continue retry anyway - server might become available

                # Use safe SSE client wrapper to handle cancel scope errors
                # Pass extended timeouts to avoid WriteTimeout errors under high concurrency
                sse_transport = await self._exit_stack.enter_async_context(
                    safe_sse_client(
                        server_url,
                        logger=self._logger,
                        timeout=max(30.0, float(timeout)),  # HTTP timeout for POST (at least 30s)
                        sse_read_timeout=max(300.0, float(timeout) * 10)  # SSE read timeout (at least 5 min)
                    )
                )
                read, write = sse_transport
                # Use longer timeout to match call_timeout
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timedelta(seconds=max(60, self._call_timeout)))
                )
                await session.initialize()

                # Connection verification: verify connection by listing tools
                await self._verify_connection(session, transport_type="sse")

                self._session = session
                self._server_params = {"type": "url", "url": server_url}
                # Store connection config for reconnection
                self._connection_config = {"url": server_url, "transport": "sse"}
                return  # Success
            except Exception as e:
                last_error = e
                error_msg = str(e)
                error_tb = traceback.format_exc()

                # Check if this is an ExceptionGroup with cancel scope errors
                is_cancel_scope_error = False
                if hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
                    # ExceptionGroup-like object
                    all_cancel_scope = all(
                        "cancel scope" in str(exc).lower() or
                        "Attempted to exit" in str(exc) or
                        "different task" in str(exc).lower()
                        for exc in e.exceptions
                    )
                    if all_cancel_scope:
                        is_cancel_scope_error = True
                elif ("cancel scope" in error_msg.lower() or
                      "Attempted to exit" in error_msg or
                      "different task" in error_msg.lower()):
                    is_cancel_scope_error = True

                # Ignore cancel scope errors - these are non-fatal warnings in Ray/async environments
                if is_cancel_scope_error:
                    self._logger.debug(
                        "Cancel scope warning during SSE connection (attempt %d/%d, safe to ignore): %s",
                        attempt + 1, retries, error_msg
                    )
                    if attempt < retries - 1:
                        await asyncio.sleep(retry_delay * 0.5)
                        continue
                    # Last attempt encountered cancel scope error - assume connection established
                    self._logger.debug(
                        "Cancel scope error on last attempt, assuming connection established: %s",
                        error_msg
                    )
                    try:
                        if self._session:
                            await self._session.list_tools()
                            return  # Success despite cancel scope error
                    except Exception:
                        pass  # Will fall through to raise error
                else:
                    # Check for TaskGroup errors (usually means server is not running)
                    is_taskgroup_error = (
                        "TaskGroup" in error_msg or
                        "unhandled errors" in error_msg.lower() or
                        "sub-exception" in error_msg.lower()
                    )

                    # Check for "Connection closed" errors (these are usually temporary)
                    is_connection_closed = (
                        "Connection closed" in error_msg or
                        isinstance(e, ConnectionError) or
                        (hasattr(e, '__class__') and 'Connection' in e.__class__.__name__)
                    )

                    # Provide more useful diagnostic information for TaskGroup errors
                    if is_taskgroup_error:
                        self._logger.warning(
                            "Failed to initialize SSE client %s (attempt %d/%d): %s\n"
                            "This usually indicates the MCP server process is not running or not responding. "
                            "Please check:\n"
                            "  1. Gateway server is running\n"
                            "  2. MCP server process is running\n"
                            "  3. Server port is accessible\n"
                            "Server URL: %s\n"
                            "The gateway will attempt to restart the server if it detects a failure.",
                            self._name, attempt + 1, retries, error_msg, server_url
                        )
                    elif is_connection_closed:
                        self._logger.warning(
                            "Connection closed for SSE client %s (attempt %d/%d): %s",
                            self._name, attempt + 1, retries, error_msg
                        )
                    else:
                        self._logger.warning(
                            "Failed to initialize SSE client %s (attempt %d/%d): %s\nTraceback:\n%s",
                            self._name, attempt + 1, retries, error_msg, error_tb[:1000]
                        )

                    if attempt < retries - 1:
                        # Use longer exponential backoff for TaskGroup errors
                        if is_taskgroup_error:
                            # TaskGroup errors usually mean server is not running
                            # Give gateway time to detect and restart the server
                            # Use longer backoff: 5s, 9s, 17s, 33s...
                            backoff_delay = retry_delay * (2 ** attempt) + 3.0  # Extra delay for server restart
                            self._logger.info(
                                "TaskGroup error detected (server may not be running "
                                "or may be restarting). Waiting %.1f seconds to allow "
                                "gateway to restart server before retry (attempt %d/%d)...",
                                backoff_delay, attempt + 1, retries
                            )
                            await asyncio.sleep(backoff_delay)
                        elif is_connection_closed:
                            backoff_delay = retry_delay * (2 ** attempt)  # Exponential backoff
                            self._logger.info(
                                "Connection closed, retrying in %.1f seconds "
                                "(exponential backoff)...",
                                backoff_delay
                            )
                            await asyncio.sleep(backoff_delay)
                        else:
                            self._logger.info("Retrying in %.1f seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)

        # All retries failed: error handling
        error_msg = str(last_error) if last_error else "Unknown error"
        is_taskgroup_error = (
            "TaskGroup" in error_msg or
            "unhandled errors" in error_msg.lower() or
            "sub-exception" in error_msg.lower()
        )

        if is_taskgroup_error:
            self._logger.error(
                "Failed to initialize SSE client %s after %d attempts: %s. "
                "This usually indicates the MCP server process is not running "
                "or not responding. Please check if the gateway server process "
                "is healthy.",
                self._name, retries, error_msg
            )
        else:
            self._logger.error("Failed to initialize SSE client %s after %d attempts: %s",
                              self._name, retries, error_msg)
        await self.cleanup()
        raise last_error

    async def connect_to_http_server(
        self,
        server_url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 20,
        retries: int = 5,
        retry_delay: float = 2.0
    ):
        """
        Connects to an MCP server using HTTP Streamable transport.

        Args:
            server_url (str): The URL of the MCP HTTP server.
            headers (dict, optional): HTTP headers to include (e.g., for authentication).
            timeout (int, optional): Connection timeout in seconds. Defaults to 20.
            retries (int, optional): Number of retry attempts. Defaults to 5.
            retry_delay (float, optional): Delay between retries in seconds. Defaults to 2.0.

        Raises:
            Exception: If the connection fails after all retries.

        Note:
            This method sets up the HTTP connection and initializes the client session.
            Headers can include authentication tokens, API keys, etc.
        """
        # Retry mechanism: support multiple retry attempts for connection failures
        last_error = None
        for attempt in range(retries):
            try:
                # Clean up previous failed attempts
                if attempt > 0:
                    await self._cleanup_failed_attempt()

                # Check if server is reachable before connecting (especially after failures)
                if attempt > 0:
                    # Exponential backoff: wait time increases gradually
                    wait_time = retry_delay * (1.5 ** attempt)  # Exponential backoff
                    self._logger.info(
                        "Waiting %.1f seconds before retry (attempt %d/%d)...",
                        wait_time, attempt + 1, retries
                    )
                    await asyncio.sleep(wait_time)

                    # Check if server is reachable
                    is_reachable = await _check_server_reachable(server_url, timeout=min(3.0, timeout))
                    if not is_reachable:
                        self._logger.warning(
                            "Server at %s is not reachable. "
                            "This usually means the MCP server process is not running or not ready.",
                            server_url
                        )
                        # Continue retry anyway - server might become available

                # Use streamablehttp_client for HTTP transport
                # Use exit_stack to manage the async context properly
                read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
                    streamablehttp_client(
                        url=server_url,
                        headers=headers or {},
                    )
                )

                session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()

                # Connection verification: verify connection by listing tools
                await self._verify_connection(session, transport_type="http")

                # Store the session and connection details
                self._session = session
                self._server_params = {"type": "http", "url": server_url, "headers": headers}
                # Store connection config for reconnection
                self._connection_config = {"url": server_url, "headers": headers, "transport": "http"}

                return  # Success
            except Exception as e:
                last_error = e
                error_msg = str(e)
                error_tb = traceback.format_exc()

                # Check if this is a safe cleanup error
                is_cancel_scope_error = False
                if hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
                    # ExceptionGroup-like object
                    all_cancel_scope = all(
                        "cancel scope" in str(exc).lower() or
                        "Attempted to exit" in str(exc) or
                        "different task" in str(exc).lower()
                        for exc in e.exceptions
                    )
                    if all_cancel_scope:
                        is_cancel_scope_error = True
                elif ("cancel scope" in error_msg.lower() or
                      "Attempted to exit" in error_msg or
                      "different task" in error_msg.lower()):
                    is_cancel_scope_error = True

                # Ignore cancel scope errors - these are non-fatal warnings
                if is_cancel_scope_error:
                    self._logger.debug(
                        "Cancel scope warning during HTTP connection (attempt %d/%d, safe to ignore): %s",
                        attempt + 1, retries, error_msg
                    )
                    if attempt < retries - 1:
                        await asyncio.sleep(retry_delay * 0.5)
                        continue
                    # Last attempt encountered cancel scope error - assume connection established
                    self._logger.debug(
                        "Cancel scope error on last attempt, assuming connection established: %s",
                        error_msg
                    )
                    try:
                        if self._session:
                            await self._session.list_tools()
                            return  # Success despite cancel scope error
                    except Exception:
                        pass  # Will fall through to raise error
                else:
                    # Log the error
                    self._logger.warning(
                        "Failed to initialize HTTP client %s (attempt %d/%d): %s\nTraceback:\n%s",
                        self._name, attempt + 1, retries, error_msg, error_tb[:1000]
                    )

                    if attempt < retries - 1:
                        self._logger.info("Retrying in %.1f seconds...", retry_delay)
                        await asyncio.sleep(retry_delay)

        # All retries failed: error handling
        error_msg = str(last_error) if last_error else "Unknown error"
        self._logger.error("Failed to initialize HTTP client %s after %d attempts: %s",
                          self._name, retries, error_msg)
        await self.cleanup()
        raise last_error

    async def list_tools(self) -> list[Any]:
        """
        Retrieves a list of available tools from the connected MCP server.

        Returns:
            list[Any]: A list of available tools.

        Raises:
            RuntimeError: If the client is not initialized.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        tools_response = await self._session.list_tools()
        tools = []
        for item in tools_response:
            if isinstance(item, tuple) and item[0] == "tools":
                for tool in item[1]:
                    tools.append(tool)
        return tools

    async def list_prompts(self) -> list[Any]:
        """
        Retrieves a list of available prompts from the connected MCP server.

        Returns:
            list[Any]: A list of available prompts.

        Raises:
            RuntimeError: If the client is not initialized.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        try:
            prompts_response = await self._session.list_prompts()
            prompts = []
            for item in prompts_response:
                if isinstance(item, tuple) and item[0] == "prompts":
                    for prompt in item[1]:
                        prompts.append(prompt)
            return prompts
        except Exception as e:
            self._logger.warning("Failed to list prompts: %s", str(e))
            return []

    async def get_prompt(self, name: str, arguments: Optional[dict] = None) -> Any:
        """
        Gets a specific prompt from the connected MCP server.

        Args:
            name (str): The name of the prompt to retrieve.
            arguments (dict, optional): Arguments for the prompt template.

        Returns:
            Any: The prompt result.

        Raises:
            RuntimeError: If the client is not initialized.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        return await self._session.get_prompt(name, arguments or {})

    async def list_resources(self) -> list[Any]:
        """
        Retrieves a list of available resources from the connected MCP server.

        Returns:
            list[Any]: A list of available resources.

        Raises:
            RuntimeError: If the client is not initialized.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        try:
            resources_response = await self._session.list_resources()
            resources = []
            for item in resources_response:
                if isinstance(item, tuple) and item[0] == "resources":
                    for resource in item[1]:
                        resources.append(resource)
            return resources
        except Exception as e:
            self._logger.warning("Failed to list resources: %s", str(e))
            return []

    async def read_resource(self, uri: str) -> Any:
        """
        Reads a specific resource from the connected MCP server.

        Args:
            uri (str): The URI of the resource to read.

        Returns:
            Any: The resource contents.

        Raises:
            RuntimeError: If the client is not initialized.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        return await self._session.read_resource(uri)

    async def execute_tool(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            retries: int = 5,
            delay: float = 1.0,
            callbacks: BaseCallback | List[BaseCallback] = None,
            enable_health_check: bool = False
    ) -> Any:
        """
        Executes a tool on the connected MCP server with a retry mechanism.

        Args:
            tool_name (str): The name of the tool to execute.
            arguments (dict[str, Any]): A dictionary of arguments for the tool.
            retries (int, optional): Number of retry attempts. Defaults to 5.
            delay (float, optional): Delay between retries in seconds. Defaults to 1.0.
            callbacks (BaseCallback | List[BaseCallback], optional):
                Callbacks for recording MCP call status and responses
            enable_health_check (bool, optional): Whether to check connection health before each call.
                Disabled by default since Gateway restarts handle connection issues.

        Returns:
            Any: The result of the tool execution.

        Raises:
            RuntimeError: If the client is not initialized or if all retry attempts fail.
        """
        if not self._session:
            raise RuntimeError(f"Client {self._name} not initialized")

        status = check_permissions(self._permissions, tool_name=tool_name, arguments=arguments)
        if not status.approved:
            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.ERROR, data=status.reason,
                project_id=self._project_id))
            return CallToolResult(content=[TextContent(text=status.reason)])

        send_message(callbacks, message=CallbackMessage(
            source=self.id, type=MessageType.EVENT, data=Event.BEFORE_CALL,
            metadata={"method": "execute_tool"}, project_id=self._project_id))
        send_message(callbacks, message=CallbackMessage(
            source=self.id, type=MessageType.STATUS, data=Status.RUNNING,
            project_id=self._project_id))

        attempt = 0
        last_error = None

        while attempt < retries:
            try:
                if not self._session:
                    raise RuntimeError(f"Client {self._name} session not initialized")

                # Optional health check (disabled by default)
                if (enable_health_check and self._connection_config and
                        self._connection_config.get("transport") == "sse"):
                    try:
                        await asyncio.wait_for(self._session.list_tools(), timeout=5.0)
                    except Exception as health_err:
                        if not is_safe_cleanup_error(health_err):
                            self._logger.warning("Health check failed: %s", str(health_err))
                            raise ConnectionError("Connection health check failed") from health_err

                self._logger.info("Executing %s...", tool_name)
                # Use asyncio.wait_for to control timeout for individual tool calls
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, arguments),
                    timeout=self._call_timeout
                )

                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.RESPONSE,
                    data=result.model_dump(mode="json") if isinstance(result, BaseModel) else result,
                    project_id=self._project_id))
                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.EVENT, data=Event.AFTER_CALL,
                    metadata={"method": "execute_tool"}, project_id=self._project_id))
                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.STATUS, data=Status.SUCCEEDED,
                    project_id=self._project_id))
                return result

            except Exception as e:
                attempt += 1
                last_error = e
                error_msg = str(e) if str(e) else repr(e)
                error_type = type(e).__name__

                # Check if this is a safe cleanup error (can be retried)
                if is_safe_cleanup_error(e):
                    self._logger.debug("Safe error during tool execution (retrying): %s", error_msg)
                    if attempt < retries:
                        await asyncio.sleep(delay * 0.5)
                        continue

                # Check if this is a connection error
                is_conn_error = is_connection_error_type(e)
                is_timeout = isinstance(e, asyncio.TimeoutError) or "timeout" in error_msg.lower()

                self._logger.warning(
                    "Failed to execute tool: %s (type: %s). Attempt %d of %d",
                    error_msg, error_type, attempt, retries
                )

                # For connection errors or timeouts, operation failed
                # Do not immediately clear session - it may still be valid for other calls
                if is_conn_error or is_timeout:
                    self._logger.warning(
                        "Connection error detected. Gateway restart will handle "
                        "reconnection."
                    )
                    # Return structured error instead of throwing exception,
                    # allowing trajectory to continue using other tools
                    raise RuntimeError(f"Connection lost: {error_msg}") from e

                # For other errors, check if session is still valid
                if not self._session:
                    raise RuntimeError(f"Session lost: {error_msg}") from e

                # Retry for temporary errors
                if attempt < retries:
                    self._logger.info("Retrying in %.1f seconds...", delay)
                    await asyncio.sleep(delay)
                else:
                    break

        # Max retries reached
        self._logger.error("Max retries reached")
        send_message(callbacks, message=CallbackMessage(
            source=self.id, type=MessageType.ERROR, data=str(last_error),
            project_id=self._project_id))
        send_message(callbacks, message=CallbackMessage(
            source=self.id, type=MessageType.EVENT, data=Event.AFTER_CALL,
            metadata={"method": "execute_tool"}, project_id=self._project_id))
        send_message(callbacks, message=CallbackMessage(
            source=self.id, type=MessageType.STATUS, data=Status.FAILED,
            project_id=self._project_id))
        raise last_error

    async def cleanup(self):
        """
        Cleans up client resources and closes the session.

        This method handles cancel scope errors that occur during cleanup.
        These errors typically occur when cleanup tasks are different from
        task creating the client (common in Ray/async environments).

        Note: In RL training scenarios where Gateway restarts,
        explicit cleanup may not be necessary as all connections are closed on restart.
        
        This method is idempotent - multiple concurrent calls are safe due to the lock.
        """
        # Check if already cleaned up (idempotent check before acquiring lock)
        if self._session is None and len(self._exit_stack._exit_callbacks) == 0:  # pylint: disable=protected-access
            return

        try:
            async with self._cleanup_lock:
                # Double-check after acquiring lock (another cleanup might have completed)
                if self._session is None and len(self._exit_stack._exit_callbacks) == 0:  # pylint: disable=protected-access
                    return

                try:
                    self._logger.debug("Closing exit stack for client %s", self._name)
                    await self._exit_stack.aclose()
                    self._logger.debug("Exit stack closed for client %s", self._name)
                except asyncio.CancelledError:
                    # CancelledError is expected during concurrent cleanup
                    # When multiple cleanups run concurrently, one may cancel the others
                    # This is safe - the first cleanup will succeed, others will be cancelled
                    self._logger.debug("Cleanup cancelled for %s (likely due to concurrent cleanup)", self._name)
                    # Don't re-raise - allow the cleanup to complete gracefully
                    # The session will still be cleared in the finally block
                except Exception as e:
                    # Check if this is a safe cleanup error
                    if is_safe_cleanup_error(e):
                        self._logger.debug("Safe cleanup error for %s: %s", self._name, str(e))
                    elif hasattr(e, 'exceptions') and isinstance(e.exceptions, tuple):
                        # Check if this is an ExceptionGroup with safe errors
                        safe_errors = [exc for exc in e.exceptions if is_safe_cleanup_error(exc)]
                        other_errors = [exc for exc in e.exceptions if not is_safe_cleanup_error(exc)]
                        if other_errors:
                            self._logger.error(
                                "Cleanup errors for %s: %d error(s)",
                                self._name, len(other_errors)
                            )
                        else:
                            self._logger.debug(
                                "Safe cleanup errors for %s: %d error(s)",
                                self._name, len(safe_errors)
                            )
                    else:
                        self._logger.error("Cleanup error for %s: %s", self._name, str(e))
                finally:
                    # Always clear session state, even if cleanup was cancelled or errored
                    self._session = None
                    self._stdio_context = None
        except asyncio.CancelledError:
            # If cancellation happens while acquiring the lock, that's also safe
            # Another cleanup call will handle the actual cleanup
            self._logger.debug("Cleanup cancelled while acquiring lock for %s", self._name)
            # Ensure session is cleared even if we were cancelled before getting the lock
            self._session = None
            self._stdio_context = None

    @property
    def project_id(self) -> str:
        """Return the ID of the project using this client."""
        return self._project_id

    @project_id.setter
    def project_id(self, value: str):
        """Set the ID of the project using this client."""
        self._project_id = value

    @property
    def id(self):
        """Return the ID of this client."""
        if self._project_id:
            return f"{self._project_id}:mcp:{self._name}"
        return f"mcp:{self._name}"

    def get_mcp_config(self) -> Dict[str, Any]:
        """Return the MCP configuration for this client."""
        return self._server_params
