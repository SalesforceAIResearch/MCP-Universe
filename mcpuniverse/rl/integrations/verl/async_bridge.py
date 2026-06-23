"""Async runtime bridge helpers for synchronous veRL call sites."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional

from .utils import _LazyLogger

logger = _LazyLogger()

# Mutable module-level singletons (lazily created, reassigned under the lock),
# not constants - lowercase is intentional.
_fallback_loop: Optional[asyncio.AbstractEventLoop] = None  # pylint: disable=invalid-name
_fallback_thread: Optional[threading.Thread] = None  # pylint: disable=invalid-name
_fallback_lock = threading.Lock()


def _quiet_handler(_loop, context):
    exc = context.get("exception")
    if exc:
        msg = str(exc)
        if "asynchronous generator" in msg or "aclose()" in msg:
            return
    logger.debug("Fallback loop async exception: {}", context.get("message", "unknown"))


def get_fallback_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent SelectorEventLoop running in a daemon thread.

    All synchronous veRL/Ray call sites submit async MCP work to this one loop.
    Reusing the loop keeps asyncio primitives such as locks and queues bound to
    a stable event loop across rollout calls.
    """
    global _fallback_loop, _fallback_thread  # pylint: disable=global-statement

    with _fallback_lock:
        if _fallback_loop is None or _fallback_loop.is_closed():
            loop = asyncio.SelectorEventLoop()
            loop.set_exception_handler(_quiet_handler)
            thread = threading.Thread(
                target=loop.run_forever,
                daemon=True,
                name="mcp-fallback-loop",
            )
            thread.start()
            _fallback_loop = loop
            _fallback_thread = thread
            logger.info("Created persistent fallback SelectorEventLoop in background thread")
        return _fallback_loop


def run_async_safely(
    coro,
    *,
    loop_factory: Callable[[], asyncio.AbstractEventLoop] = get_fallback_loop,
):
    """Run an async coroutine from a synchronous training call site."""
    fallback = loop_factory()
    future = asyncio.run_coroutine_threadsafe(coro, fallback)
    return future.result()
