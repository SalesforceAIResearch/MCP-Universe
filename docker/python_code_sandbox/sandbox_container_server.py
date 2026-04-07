#!/usr/bin/env python3
"""
HTTP server that runs inside the Docker container to execute Python code.
This server creates temporary directories for each execution and cleans them up.
"""

import asyncio
import hmac
import os
import secrets
import subprocess
import tempfile
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any
from aiohttp import web

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory for temporary execution directories
BASE_TEMP_DIR = os.environ.get("SANDBOX_TEMP_DIR", "/tmp/sandbox_executions")

# Thread pool executor for running subprocess operations
_executor = ThreadPoolExecutor(max_workers=10)

# API key for authenticating requests.
# MUST be set via environment variable; server refuses to start without it.
SANDBOX_API_KEY = os.environ.get("SANDBOX_API_KEY", "")

# Paths that do NOT require authentication
_PUBLIC_PATHS = frozenset({"/health"})


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Verify Bearer token on every request except health checks."""
    if request.path in _PUBLIC_PATHS:
        return await handler(request)

    if not SANDBOX_API_KEY:
        logger.error("SANDBOX_API_KEY is not configured – rejecting request")
        return web.json_response(
            {"error": "Server misconfigured: API key not set"},
            status=403,
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing or malformed Authorization header"}, status=401)

    token = auth_header[len("Bearer "):]
    if not hmac.compare_digest(token, SANDBOX_API_KEY):
        return web.json_response({"error": "Invalid API key"}, status=401)

    return await handler(request)


def _run_subprocess_sync(_code_file: str, temp_dir: str, timeout: int) -> Dict[str, Any]:
    """
    Synchronous helper function to run subprocess.
    This runs in a thread pool to avoid blocking the event loop.
    """
    try:
        with subprocess.Popen(
            ["python", "-u", "code.py"],
            cwd=temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        ) as process:
            try:
                # Wait for process with timeout
                stdout, _ = process.communicate(timeout=timeout)
                exit_code = process.returncode

                return {
                    "success": exit_code == 0,
                    "exit_code": exit_code,
                    "output": stdout or "",
                    "error": None if exit_code == 0 else stdout
                }
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return {
                    "success": False,
                    "exit_code": -1,
                    "output": "",
                    "error": f"Execution timeout after {timeout} seconds"
                }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error in subprocess execution: %s", e)
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": f"Execution error: {str(e)}"
        }


async def execute_python_code(code: str, timeout: int = 300) -> Dict[str, Any]:
    """
    Execute Python code in a temporary directory.
    Each execution runs in its own process and thread, allowing concurrent requests.
    
    Args:
        code: Python code to execute
        timeout: Maximum execution time in seconds
        
    Returns:
        Dictionary with success, exit_code, output, and error fields
    """
    temp_dir = None
    try:
        # Create a unique temporary directory for this execution
        os.makedirs(BASE_TEMP_DIR, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="exec_", dir=BASE_TEMP_DIR)
        logger.info("Created temporary directory: %s", temp_dir)

        # Write code to a file in the temp directory
        code_file = os.path.join(temp_dir, "code.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Run subprocess in thread pool to avoid blocking the event loop
        # This allows multiple requests to be processed concurrently
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_subprocess_sync,
            code_file,
            temp_dir,
            timeout
        )

        return result

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error executing code: %s", e)
        return {
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": f"Execution error: {str(e)}"
        }
    finally:
        # Always clean up the temporary directory
        if temp_dir and os.path.exists(temp_dir):
            try:
                # Run cleanup in executor to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(_executor, shutil.rmtree, temp_dir)
                logger.info("Cleaned up temporary directory: %s", temp_dir)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to clean up %s: %s", temp_dir, e)


async def handle_execute(request: web.Request) -> web.Response:
    """Handle code execution requests"""
    try:
        data = await request.json()
        code = data.get("code", "")
        timeout = data.get("timeout", 300)

        if not code.strip():
            return web.json_response({
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": "No code provided"
            }, status=400)

        result = await execute_python_code(code, timeout)
        return web.json_response(result)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error handling request: %s", e)
        return web.json_response({
            "success": False,
            "exit_code": -1,
            "output": "",
            "error": f"Server error: {str(e)}"
        }, status=500)


async def handle_health(_request: web.Request) -> web.Response:
    """Health check endpoint"""
    return web.json_response({"status": "ok"})


def create_app():
    """Create the aiohttp application"""
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/execute", handle_execute)
    app.router.add_get("/health", handle_health)
    return app


async def main():
    """Main entry point"""
    global SANDBOX_API_KEY  # pylint: disable=global-statement
    # Re-read at startup so env changes are picked up
    SANDBOX_API_KEY = os.environ.get("SANDBOX_API_KEY", "")

    if not SANDBOX_API_KEY:
        logger.warning(
            "SANDBOX_API_KEY is not set. Generating a random key – "
            "set the env var for production use."
        )
        SANDBOX_API_KEY = secrets.token_urlsafe(32)
        logger.info("Generated SANDBOX_API_KEY: %s", SANDBOX_API_KEY)

    port = int(os.environ.get("SANDBOX_PORT", "8080"))
    bind_address = os.environ.get("SANDBOX_BIND_ADDRESS", "127.0.0.1")
    logger.info("Starting sandbox HTTP server on %s:%s", bind_address, port)

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, bind_address, port)
    await site.start()

    logger.info("Sandbox server ready on %s:%s", bind_address, port)

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        await runner.cleanup()
        _executor.shutdown(wait=True)
        logger.info("Thread pool executor shut down")


if __name__ == "__main__":
    asyncio.run(main())
