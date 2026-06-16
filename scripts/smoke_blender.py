"""Quick Blender benchmark configuration smoke test. Loads .env via dotenv."""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ADDON_PORT = 9876
BLEND_FILES_REL = Path("mcpuniverse/evaluator/blender/blend_files")


def _fail(message: str, code: int = 1) -> None:
    print(f"FAIL: {message}", flush=True)
    sys.exit(code)


def check_env() -> tuple[Path, Path]:
    blender_path = os.getenv("BLENDER_APP_PATH", "").strip().strip('"')
    repo_dir = os.getenv("MCPUniverse_DIR", "").strip().strip('"')

    if not blender_path:
        _fail("BLENDER_APP_PATH is not set")
    if not repo_dir:
        _fail("MCPUniverse_DIR is not set")

    blender = Path(blender_path)
    repo = Path(repo_dir)

    if not blender.is_file():
        _fail(
            f"Blender executable not found: {blender}. "
            "On Windows, use forward slashes in .env "
            '(e.g. C:/Program Files/.../blender.exe) because \\b in \\blender '
            "is read as a backspace escape."
        )
    if not repo.is_dir():
        _fail(f"MCPUniverse_DIR is not a directory: {repo}")

    blend_files = repo / BLEND_FILES_REL
    blend_files.mkdir(parents=True, exist_ok=True)

    print("Env OK (BLENDER_APP_PATH and MCPUniverse_DIR present)", flush=True)
    print("Blender:", blender, flush=True)
    print("Repo:", repo, flush=True)
    print("Blend output dir:", blend_files, flush=True)
    return blender, repo


def check_blender_executable(blender: Path) -> None:
    print("Running blender --version...", flush=True)
    try:
        result = subprocess.run(
            [str(blender), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError as exc:
        _fail(f"Could not run Blender: {exc}")

    if result.returncode != 0:
        _fail(f"blender --version failed: {result.stderr.strip() or result.stdout.strip()}")

    version_line = (result.stdout or result.stderr).strip().splitlines()[0]
    print(f"Blender OK: {version_line}", flush=True)


def check_addon_scene_query() -> None:
    """Ask the Blender addon for scene info over the socket (no MCP subprocess)."""
    import json

    print("Querying scene info via addon socket...", flush=True)
    command = json.dumps({"type": "get_scene_info", "params": {}}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    try:
        sock.connect(("localhost", ADDON_PORT))
        sock.sendall(command)
        chunks = []
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            try:
                json.loads(b"".join(chunks).decode("utf-8"))
                break
            except json.JSONDecodeError:
                continue
        response = json.loads(b"".join(chunks).decode("utf-8"))
    except (ConnectionRefusedError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        _fail(f"Addon scene query failed: {exc}")
    finally:
        sock.close()

    if response.get("status") == "error":
        _fail(f"Addon returned error: {response.get('message', response)}")

    result = response.get("result", {})
    object_count = len(result.get("objects", []))
    print(f"Addon scene query OK ({object_count} object(s) in scene)", flush=True)


def check_addon_socket() -> None:
    print(f"Checking Blender addon socket on localhost:{ADDON_PORT}...", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect(("localhost", ADDON_PORT))
    except (ConnectionRefusedError, TimeoutError, OSError):
        _fail(
            "Cannot connect to Blender addon on port 9876. "
            "Open Blender, enable the Blender MCP addon (blender_addon.py), "
            "and ensure the server is running (sidebar: BlenderMCP)."
        )
    finally:
        sock.close()
    print("Addon socket OK (port 9876 reachable)", flush=True)


async def check_mcp_scene() -> None:
    from mcpuniverse.mcp.manager import MCPManager

    print("Starting MCP-Universe Blender MCP server...", flush=True)
    manager = MCPManager()
    client = await manager.build_client(server_name="blender")
    try:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools] if tools else []
        if not tool_names:
            _fail("Blender MCP server returned no tools")
        print(f"MCP OK ({len(tool_names)} tools)", flush=True)

        result = await client.execute_tool("get_scene_info", arguments={})
        preview = str(result)[:300].replace("\n", " ")
        print(f"get_scene_info OK: {preview}...", flush=True)
    finally:
        await client.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test Blender benchmark setup")
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Also call get_scene_info via mcpuniverse.mcp.servers.blender",
    )
    args = parser.parse_args()

    blender, _repo = check_env()
    check_blender_executable(blender)
    check_addon_socket()
    check_addon_scene_query()

    if args.mcp:
        asyncio.run(check_mcp_scene())

    print("SUCCESS - Blender benchmark setup looks good", flush=True)
    if not args.mcp:
        print("Tip: add --mcp to also test mcpuniverse.mcp.servers.blender (needs venv)", flush=True)


if __name__ == "__main__":
    main()
