"""MCP runtime for composing search, scraping, and summarization in Python."""
# pylint: disable=broad-exception-caught
import ast
import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

import click
from mcp.server.fastmcp import FastMCP

from mcpuniverse.common.logger import get_logger
from .backends import (
    _api_search, _api_scrape, _api_llm_summary,
    _effective_program_timeout, DEFAULT_TIMEOUT, MAX_STDOUT_CHARS,
)

# ------------------------------------------------------------------
# AST sanity check + restricted exec
# ------------------------------------------------------------------

FORBIDDEN_NAMES = {
    "__import__", "__builtins__", "open", "exec", "eval", "compile",
    "globals", "locals", "vars", "input", "exit", "quit", "breakpoint",
    "memoryview", "help",
}


def _allow_asyncio_import() -> bool:
    """RP_ALLOW_ASYNCIO_IMPORT=1 relaxes the sandbox for `asyncio` ONLY.

    Programs may then `import asyncio` / `from asyncio import ...` (the module
    is already injected as a global, so this adds no capability), `__name__`
    is defined as "__main__", and sync-style scripts that drive their own
    event loop via `asyncio.run(main())` execute unwrapped. Default off: the
    sandbox stays byte-for-byte identical to the historical behavior.
    """
    return os.environ.get("RP_ALLOW_ASYNCIO_IMPORT", "0") == "1"


class _Sanitizer(ast.NodeVisitor):
    """Reject imports, forbidden builtins, and dunder attribute access."""
    # AST visitor method names are defined by the standard library.
    # pylint: disable=invalid-name

    def visit_Import(self, node):
        """Allow only the optional asyncio import."""
        if _allow_asyncio_import() and all(
            alias.name.split(".")[0] == "asyncio" for alias in node.names
        ):
            return
        raise ValueError("imports are not allowed; use the predefined functions only")

    def visit_ImportFrom(self, node):
        """Reject relative and non-asyncio imports."""
        if (
            _allow_asyncio_import()
            and node.level == 0
            and (node.module or "").split(".")[0] == "asyncio"
        ):
            return
        raise ValueError("imports are not allowed; use the predefined functions only")

    def visit_Attribute(self, node):
        """Reject dunder attributes."""
        if isinstance(node.attr, str) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise ValueError(f"dunder attribute access ({node.attr}) is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node):
        """Reject unsafe builtin names."""
        if node.id in FORBIDDEN_NAMES:
            raise ValueError(f"name '{node.id}' is not allowed")
        self.generic_visit(node)


def _check_program(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc}") from exc
    _Sanitizer().visit(tree)


def _asyncio_only_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Restricted ``__import__`` handed to sandboxed programs (asyncio only).

    The sanitizer already rejects non-asyncio import statements; this is the
    runtime backstop that makes the allowed ones actually resolve (the safe
    builtins otherwise have no ``__import__`` at all).
    """
    # pylint: disable=redefined-builtin
    if level == 0 and name.split(".")[0] == "asyncio":
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"import of '{name}' is not allowed; use the predefined functions only")


def _compile_plain_module(code: str):
    """Compile ``code`` as an ordinary module, or None if it needs the wrapper.

    Programs using top-level ``await`` only compile inside the
    ``async def __program_main__()`` wrapper; everything else (notably the
    ``async def main(): ...`` + ``asyncio.run(main())`` script style) compiles
    plainly and can run unwrapped, driving its own event loop.
    """
    try:
        return compile(code, "<research_program>", "exec")
    except SyntaxError:
        return None


SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "print": print, "len": len, "range": range, "list": list, "dict": dict,
    "set": set, "tuple": tuple, "frozenset": frozenset, "str": str, "int": int,
    "float": float, "bool": bool, "bytes": bytes,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "sorted": sorted, "reversed": reversed, "min": min, "max": max,
    "sum": sum, "any": any, "all": all, "abs": abs, "round": round,
    "isinstance": isinstance, "issubclass": issubclass, "type": type,
    "repr": repr, "format": format, "hash": hash, "id": id,
    "ValueError": ValueError, "KeyError": KeyError, "TypeError": TypeError,
    "IndexError": IndexError, "Exception": Exception,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "AssertionError": AssertionError, "ZeroDivisionError": ZeroDivisionError,
    "next": next, "iter": iter, "slice": slice, "divmod": divmod, "pow": pow,
    "hex": hex, "oct": oct, "bin": bin, "chr": chr, "ord": ord,
}


def _make_globals() -> Dict[str, Any]:
    g = {
        "__builtins__": dict(SAFE_BUILTINS),
        # primitives only
        "search": _api_search,
        "scrape": _api_scrape,
        "llm_summary": _api_llm_summary,
        # convenience
        "json": json,
        "asyncio": asyncio,
    }
    if _allow_asyncio_import():
        # `import asyncio` needs a working __import__ to resolve; also define
        # __name__ so `if __name__ == "__main__":` script guards execute.
        g["__builtins__"]["__import__"] = _asyncio_only_import
        g["__name__"] = "__main__"
    return g


# ------------------------------------------------------------------
# Subprocess-pool implementation (production)
#
# Each call to `run_research_program` is dispatched to a fresh Python
# subprocess via `python -m mcpuniverse.mcp.servers.research_primitives.runner`.
# Mirrors the pattern in `docker/python_code_sandbox/sandbox_container_server.py`:
# the MCP server's event loop never executes user code, so 200+ concurrent
# sessions can run truly in parallel on a multi-core box (1 core per running
# program rather than 1 core shared across all of them).
#
# RP_RUNNER_WORKERS env var controls max in-flight subprocesses (default 32).
# RP_SUBPROCESS_OVERHEAD_S env var = extra wall-clock budget for startup + IO.
# ------------------------------------------------------------------

_RUNNER_WORKERS = int(os.environ.get("RP_RUNNER_WORKERS", "32"))
_SUBPROCESS_OVERHEAD_S = int(os.environ.get("RP_SUBPROCESS_OVERHEAD_S", "30"))
_subprocess_executor = ThreadPoolExecutor(
    max_workers=_RUNNER_WORKERS,
    thread_name_prefix="rp-runner",
)

# Sentinel used by runner.py to mark its result line on stdout. Defined here
# (not imported from runner.py) so this module can be loaded without forcing
# the runner subprocess code to import.
_RP_RESULT_SENTINEL = "__RP_RESULT__"


def _run_subprocess_sync(code: str, timeout: int) -> Dict[str, Any]:
    """Spawn a fresh Python subprocess to execute one research program.

    Synchronous (runs inside a ThreadPoolExecutor worker thread). The outer
    `_run_program` wraps this with `run_in_executor` so the MCP event loop
    stays responsive.
    """
    payload = json.dumps({"code": code, "timeout": timeout})
    # Wall-clock budget for the subprocess = user timeout + startup/IO slack.
    wall = timeout + _SUBPROCESS_OVERHEAD_S
    try:
        proc = subprocess.run(  # pylint: disable=subprocess-run-check
            [
                sys.executable,
                "-u",
                "-m",
                "mcpuniverse.mcp.servers.research_primitives.runner",
            ],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=wall,
        )
    except subprocess.TimeoutExpired as exc:
        # Subprocess wall-clock exceeded — kill it and report.
        return {
            "success": False,
            "error": f"runner subprocess exceeded wall budget {wall}s "
                     f"(user timeout {timeout}s + {_SUBPROCESS_OVERHEAD_S}s slack)",
            "stdout": (exc.stdout or b"").decode("utf-8", "replace")[:MAX_STDOUT_CHARS],
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"failed to spawn runner subprocess: {exc}",
            "stdout": "",
        }

    raw_stdout = proc.stdout.decode("utf-8", "replace")
    raw_stderr = proc.stderr.decode("utf-8", "replace")

    # Locate the sentinel-marked result line emitted by runner._emit().
    idx = raw_stdout.rfind(_RP_RESULT_SENTINEL)
    if idx >= 0:
        line_end = raw_stdout.find("\n", idx)
        json_line = raw_stdout[idx + len(_RP_RESULT_SENTINEL):
                               (line_end if line_end >= 0 else None)]
        try:
            return json.loads(json_line)
        except Exception:
            pass

    # Fallback: no parseable result. Surface as much detail as possible.
    if proc.returncode != 0:
        return {
            "success": False,
            "error": (
                f"runner subprocess exit={proc.returncode} (no parseable result). "
                f"stderr: {raw_stderr[:500]}"
            ),
            "stdout": raw_stdout[:MAX_STDOUT_CHARS],
        }
    return {
        "success": False,
        "error": "runner produced no result sentinel; suspect output corruption",
        "stdout": raw_stdout[:MAX_STDOUT_CHARS],
    }


async def _run_program(code: str, timeout: int) -> Dict[str, Any]:
    """Production code path: run the user's research program in a subprocess.

    A bounded ThreadPoolExecutor caps the number of in-flight subprocesses
    (RP_RUNNER_WORKERS, default 32). Extra calls queue inside the executor
    without blocking the MCP event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _subprocess_executor,
        _run_subprocess_sync,
        code,
        timeout,
    )


# ------------------------------------------------------------------
# MCP server
# ------------------------------------------------------------------

def build_server(port: int) -> FastMCP:
    """Initialize the MCP server."""
    mcp = FastMCP("research_primitives", port=port)

    @mcp.tool()
    async def run_research_program(code: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """Run an async Python script that orchestrates web research in ONE tool call.

        You compose three primitives. There are no batched helpers — chain
        them with ``asyncio.gather`` so independent calls run in parallel,
        and use ordinary Python (filter / dedupe / slice / regex) to
        decide what is worth fetching or summarizing next.

        Primitives (all coroutines — `await` them):

          search(q, num=10, gl="us", hl="en", location=None, tbs=None)
              -> list[{title, link, snippet}]. ONE query.

          scrape(url, max_chars=409600) -> str
              ONE URL, raw markdown. No LLM. (`max_chars` truncates the
              returned string but the network fetch is the same.)

          llm_summary(content, question, max_tokens=4096) -> str
              ONE LLM extraction over arbitrary text. `content` can be
              one scrape, several scrapes concatenated, snippets, etc.

        Convenience: `json` and `asyncio` are available. NO other imports.

        Output contract:
          * Whatever you `print()` is returned under "stdout".
          * stdout is capped at 16000 chars — print only distilled findings.
          * Plain `return` is discarded; only stdout is read back.
          * On error: {"success": False, "error": "...", "stdout": "..."}.

        Args:
            code: Python source. Top-level `await` is allowed; the body is
                  wrapped in `async def __program_main__(): ...` for you.
                  No `import` statements; only the predefined names.
            timeout: Max wall-clock seconds for the whole script. Default 240.

        Returns:
            {"success": bool, "error": str, "stdout": str}

        ---
        CHAINING PATTERNS — read these before writing your script.

        1) PARALLEL SEARCH FAN-OUT, dedupe URLs, then ONE pooled summary.
           Cheaper than per-URL summaries when the same question covers all docs.

            queries = [
                "Python 3 license terms",
                "PostgreSQL license terms",
                "Apache Spark license terms",
            ]
            hit_lists = await asyncio.gather(*[search(q, num=5) for q in queries])
            urls = []
            seen = set()
            for hits in hit_lists:
                for h in hits[:3]:
                    if h["link"] not in seen:
                        seen.add(h["link"])
                        urls.append(h["link"])
            texts = await asyncio.gather(*[scrape(u, max_chars=8000) for u in urls])
            combined = "\\n\\n---\\n\\n".join(
                f"[Source {i}: {u}]\\n{t}" for i, (u, t) in enumerate(zip(urls, texts))
            )
            print(await llm_summary(
                combined,
                "For each project, list the commercial-use restrictions. "
                "Cite the source index used.",
            ))

        2) PARALLEL PIPELINE — one scrape→summary chain per URL, all in flight at once.
           Use when you want a separate answer per source.

            async def per_url(url, q):
                text = await scrape(url, max_chars=12000)
                if text.startswith("[error"):
                    return f"[skip: {url}: {text}]"
                return await llm_summary(text, q)

            urls = ["https://a", "https://b", "https://c"]
            answers = await asyncio.gather(*[
                per_url(u, "Headline result and methodology in <=80 words.") for u in urls
            ])
            for u, a in zip(urls, answers):
                print(f"### {u}\\n{a}\\n")

        3) FILTER BEFORE PAYING — keyword-prune scraped pages, summarize only matches.

            hits = await search("ICLR 2025 best paper award", num=15)
            urls = [h["link"] for h in hits if any(d in h["link"]
                    for d in ["openreview.net", "iclr.cc", "ar5iv", "arxiv.org"])][:8]
            texts = await asyncio.gather(*[scrape(u, max_chars=8000) for u in urls])
            kept = [(u, t) for u, t in zip(urls, texts)
                    if "best paper" in t.lower() and "iclr" in t.lower()]
            if not kept:
                print("no strong-match pages; falling back to top 3 by snippet")
                kept = list(zip(urls, texts))[:3]
            answer = await llm_summary(
                "\\n\\n---\\n\\n".join(f"[{u}]\\n{t[:6000]}" for u, t in kept),
                "Which paper(s) won the ICLR 2025 Best Paper award? Cite each URL.",
            )
            print(answer)

        4) TWO-WAVE SEARCH — let snippets steer the second wave.

            wave1 = await search("RoPE long-context extrapolation", num=10)
            terms = set()
            for h in wave1[:8]:
                snip = (h.get("snippet") or "").lower()
                for k in ("yarn", "ntk", "linear scaling", "self-extend"):
                    if k in snip:
                        terms.add(k)
            wave2_qs = [f"{t} method paper arxiv" for t in sorted(terms)]
            wave2 = await asyncio.gather(*[search(q, num=5) for q in wave2_qs])
            picks = []
            for q, hits in zip(wave2_qs, wave2):
                if hits:
                    picks.append((q, hits[0]["link"]))
            texts = await asyncio.gather(*[scrape(u, max_chars=8000) for _, u in picks])
            answers = await asyncio.gather(*[
                llm_summary(t, f"One-sentence description of the method for: {q}")
                for (q, _), t in zip(picks, texts)
            ])
            for (q, u), a in zip(picks, answers):
                print(f"- {q} -> {u}\\n  {a}")

        5) SNIPPET-ONLY PASS — sometimes you do not need to scrape at all.

            hits = await asyncio.gather(*[
                search(f"{name} CEO 2025", num=3)
                for name in ["Anthropic", "OpenAI", "Mistral AI"]
            ])
            blob = "\\n".join(
                f"[{name}] " + " | ".join(f"{h['title']} :: {h['snippet']}" for h in lst[:3])
                for name, lst in zip(["Anthropic", "OpenAI", "Mistral AI"], hits)
            )
            print(await llm_summary(blob, "Current CEO of each company, with confidence."))

        ---
        Guidance:
          * Always `asyncio.gather` independent calls; never `for` + `await` in series.
          * Pass small `max_chars` to scrape when you will summarize many pages.
          * Prefer ONE pooled `llm_summary` over N small ones when the question is the
            same across documents and the combined text fits in ~150K chars.
          * Filter / dedupe in plain Python before deciding what to scrape or summarize.
          * Print only what your next reasoning step needs.
        """
        # Clamp the program wall budget so a single tool call can never run
        # longer than the MCP client's per-call read-timeout (300s). Without
        # this, a program requesting e.g. timeout=300 would still be running
        # when the client gives up, and its response would be discarded.
        timeout = _effective_program_timeout(timeout)

        return await _run_program(code, timeout=timeout)

    return mcp


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
@click.option("--port", default="8000", help="Port to listen on for SSE")
def main(transport: str, port: str):
    """Start the research-primitives MCP server."""
    assert transport.lower() in ["stdio", "sse"], \
        "Transport should be `stdio` or `sse`"
    logger = get_logger("Service:research_primitives")
    logger.info("Starting the MCP server on port %s with transport %s", port, transport)
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
