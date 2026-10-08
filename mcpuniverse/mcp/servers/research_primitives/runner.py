"""Subprocess runner for a single research program.

Runs ONE user-supplied research program (a call to `run_research_program`)
in its own Python interpreter, bypassing the GIL of the MCP server process.

Input  (stdin, JSON): {"code": str, "timeout": int}
Output (stdout, JSON): {"success": bool, "error": str, "stdout": str}

Architecturally mirrors `docker/python_code_sandbox/sandbox_container_server.py`:
the MCP server's main event loop never executes user code, so 200+ concurrent
sessions cannot starve each other on the GIL.

Each invocation pays a small Python startup cost (~200-400 ms for the
interpreter + httpx import), but in exchange every program gets a fully
parallel CPU slice on the multi-core box.
"""

# pylint: disable=exec-used
import asyncio
import io
import json
import signal
import sys
import traceback
from contextlib import redirect_stdout

# Re-use the existing primitives + sanity-checker from server.py.
# (Importing server.py is cheap — module-level work is just env-var reads
#  and importing FastMCP; FastMCP itself never starts a server here.)
from mcpuniverse.mcp.servers.research_primitives.server import (
    _allow_asyncio_import,
    _check_program,
    _compile_plain_module,
    _make_globals,
    MAX_STDOUT_CHARS,
)


def _truncate_stdout(s: str) -> str:
    """Match the truncation behavior of the in-process implementation."""
    if len(s) <= MAX_STDOUT_CHARS:
        return s
    head = MAX_STDOUT_CHARS - 200
    return (
        s[:head]
        + "\n\n[...stdout truncated; "
        f"showed first {head}. Print less next time.]"
    )


class _BoundedOutput(io.StringIO):
    """Bound retained output while preserving the truncation signal."""

    def write(self, text: str) -> int:
        remaining = max(0, MAX_STDOUT_CHARS + 1 - self.tell())
        super().write(text[:remaining])
        return len(text)


def _emit(payload: dict) -> None:
    """Write the result JSON to fd 3 (or stdout fallback) and exit cleanly.

    We write to a dedicated fd (or use a sentinel marker on stdout) so that
    leftover bytes from user `print()` calls inside the redirect_stdout
    context can never bleed into the structured result.
    """
    # Write the result on a SENTINEL-marked stdout line so the parent can
    # locate it even if anything else slipped through. The user's prints
    # were redirected to a StringIO and are inside payload["stdout"], so in
    # practice no other lines appear after this — but the sentinel keeps
    # the parser robust.
    sys.stdout.write("\n__RP_RESULT__" + json.dumps(payload) + "\n")
    sys.stdout.flush()


class _ProgramTimeout(BaseException):
    """Raised by the SIGALRM handler; BaseException so user `except Exception`
    blocks cannot swallow the timeout."""


def _run_plain(compiled, timeout: int) -> None:
    """Run a sync-style program (no top-level await) unwrapped.

    Only reachable with RP_ALLOW_ASYNCIO_IMPORT=1. No event loop is running
    in this process yet, so the program's own ``asyncio.run(main())`` works.
    SIGALRM enforces the same in-process timeout (and message) the wrapper
    path gets from ``asyncio.wait_for``.
    """
    g = _make_globals()
    buf = _BoundedOutput()

    def _on_alarm(signum, frame):  # pylint: disable=unused-argument
        raise _ProgramTimeout()

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(timeout)
    try:
        with redirect_stdout(buf):
            exec(compiled, g)  # noqa: S102
    except _ProgramTimeout:
        _emit({
            "success": False,
            "error": f"program timed out after {timeout}s",
            "stdout": _truncate_stdout(buf.getvalue()),
        })
        return
    except Exception:  # pylint: disable=broad-except
        _emit({
            "success": False,
            "error": traceback.format_exc(limit=5),
            "stdout": _truncate_stdout(buf.getvalue()),
        })
        return
    finally:
        signal.alarm(0)
    _emit({
        "success": True,
        "error": "",
        "stdout": _truncate_stdout(buf.getvalue()),
    })


async def _run_wrapped(code: str, timeout: int) -> None:
    """Run the program inside the ``async def __program_main__()`` wrapper."""
    indented = "\n".join("    " + line for line in code.splitlines()) or "    pass"
    wrapper = "async def __program_main__():\n" + indented

    g = _make_globals()

    try:
        exec(compile(wrapper, "<research_program>", "exec"), g)  # noqa: S102
    except Exception as exc:  # pylint: disable=broad-except
        _emit({
            "success": False,
            "error": f"compile error: {exc}\n{traceback.format_exc(limit=3)}",
            "stdout": "",
        })
        return

    buf = _BoundedOutput()
    coro = g["__program_main__"]()
    try:
        with redirect_stdout(buf):
            await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        _emit({
            "success": False,
            "error": f"program timed out after {timeout}s",
            "stdout": _truncate_stdout(buf.getvalue()),
        })
        return
    except Exception:  # pylint: disable=broad-except
        _emit({
            "success": False,
            "error": traceback.format_exc(limit=5),
            "stdout": _truncate_stdout(buf.getvalue()),
        })
        return

    _emit({
        "success": True,
        "error": "",
        "stdout": _truncate_stdout(buf.getvalue()),
    })


def main() -> None:
    """Read one request, validate its program, and emit its result."""
    try:
        raw = sys.stdin.read()
    except Exception as e:  # pylint: disable=broad-except
        _emit({"success": False, "error": f"failed to read stdin: {e}", "stdout": ""})
        return

    try:
        req = json.loads(raw)
    except Exception as e:  # pylint: disable=broad-except
        _emit({"success": False, "error": f"failed to parse request JSON: {e}", "stdout": ""})
        return

    code = req.get("code", "")
    timeout = int(req.get("timeout", 240))

    try:
        _check_program(code)
    except ValueError as exc:
        _emit({"success": False, "error": str(exc), "stdout": ""})
        return

    if _allow_asyncio_import():
        plain = _compile_plain_module(code)
        if plain is not None:
            _run_plain(plain, timeout)
            return

    asyncio.run(_run_wrapped(code, timeout))


if __name__ == "__main__":
    main()
