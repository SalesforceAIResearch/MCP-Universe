"""Search, reader, and summary providers for programmatic research."""
# pylint: disable=broad-exception-caught,global-statement

import asyncio
import fcntl
import hashlib
import json
import os
import random
import subprocess
import time
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote, urlsplit

import httpx


# Search backend (Serper)
SERPER_BASE_URL = os.getenv("SERPER_BASE_URL", "https://google.serper.dev")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_MAX_CONCURRENCY = max(1, int(os.getenv("SERPER_MAX_CONCURRENCY", "4")))
SERPER_MAX_ATTEMPTS = max(1, int(os.getenv("SERPER_MAX_ATTEMPTS", "7")))
SERPER_CONNECT_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("SERPER_CONNECT_TIMEOUT_SECONDS", "25"))
)
SERPER_READ_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("SERPER_READ_TIMEOUT_SECONDS", "60"))
)
SERPER_RETRY_BASE_SECONDS = max(
    0.0, float(os.getenv("SERPER_RETRY_BASE_SECONDS", "1.0"))
)
SERPER_RETRY_MAX_SECONDS = max(
    SERPER_RETRY_BASE_SECONDS,
    float(os.getenv("SERPER_RETRY_MAX_SECONDS", "16.0")),
)
SERPER_SLOT_POLL_SECONDS = max(
    0.01, float(os.getenv("SERPER_SLOT_POLL_SECONDS", "0.05"))
)
SERPER_SLOT_DIR = os.getenv(
    "SERPER_SLOT_DIR", f"/tmp/mcpuniverse-serper-slots-{os.getuid()}"
)
SERPER_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 522, 523, 524}

# Scrape backend (Jina reader)
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_BASE_URL = os.getenv("JINA_BASE_URL", "https://r.jina.ai")
JINA_FORCE_302_TARGET_ENCODING = os.getenv(
    "JINA_FORCE_302_TARGET_ENCODING", "0"
).lower() in {"1", "true", "yes", "on"}
JINA_MAX_CONCURRENCY = max(1, int(os.getenv("JINA_MAX_CONCURRENCY", "8")))
JINA_MAX_ATTEMPTS = max(1, int(os.getenv("JINA_MAX_ATTEMPTS", "3")))
JINA_CONNECT_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("JINA_CONNECT_TIMEOUT_SECONDS", "20"))
)
JINA_READ_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("JINA_READ_TIMEOUT_SECONDS", "150"))
)
JINA_RETRY_BASE_SECONDS = max(
    0.0, float(os.getenv("JINA_RETRY_BASE_SECONDS", "0.5"))
)
JINA_RETRY_MAX_SECONDS = max(
    JINA_RETRY_BASE_SECONDS,
    float(os.getenv("JINA_RETRY_MAX_SECONDS", "4.0")),
)
JINA_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 522, 523, 524}

# The production runner launches a fresh subprocess for each research program.
# A process-local semaphore alone therefore does not protect the upstream from
# aggregate bursts. Advisory lock files provide a lightweight host-wide limit,
# while the process-local AsyncClient preserves connections within one program.
_SERPER_CLIENT: Optional["httpx.AsyncClient"] = None
_SERPER_CLIENT_LOOP: Optional[asyncio.AbstractEventLoop] = None
_JINA_CLIENT: Optional["httpx.AsyncClient"] = None
_JINA_CLIENT_LOOP: Optional[asyncio.AbstractEventLoop] = None
_JINA_ADMISSION_GATE: Optional[asyncio.Semaphore] = None
_JINA_ADMISSION_LOOP: Optional[asyncio.AbstractEventLoop] = None

# Per-scrape telemetry (opt-in via JINA_SCRAPE_EVENT_LOG, set by the dispatcher
# when SCRAPE_TELEMETRY=1). Mirrors the schema emitted by the jina-scrape-llm-summary
# server so both agent families aggregate uniformly. Writing is best-effort and
# must NEVER change the tool's observable behavior.
SCRAPE_FAILURE_BODY_MAX_CHARS = 8000


def _log_search_attempt(
    query: str,
    attempt: int,
    started: float,
    response: Optional["httpx.Response"] = None,
    error: Optional[Exception] = None,
    failure_kind: Optional[str] = None,
    message: str = "",
    queue_wait_ms: float = 0.0,
) -> None:
    """Append task-scoped Serper telemetry without changing tool output."""
    path = os.environ.get("SERPER_SEARCH_EVENT_LOG", "")
    if not path:
        return
    try:
        success = (
            error is None
            and failure_kind is None
            and response is not None
            and response.is_success
        )
        record = {
            "event": "serper_search_attempt" if success else "serper_search_failure",
            "timestamp_unix": time.time(),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "mcp_server": "research-primitives",
            "run_name": os.environ.get("MCPUNIVERSE_RUN_NAME", ""),
            "task_id": os.environ.get("MCPUNIVERSE_TASK_ID", ""),
            "query": query,
            "attempt": attempt,
            "success": success,
            "failure_kind": (
                None
                if success
                else failure_kind
                or ("request_error" if error is not None else "unknown_failure")
            ),
            "status_code": response.status_code if response is not None else None,
            "retry_after": (
                response.headers.get("retry-after") if response is not None else None
            ),
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error)[:1000] if error is not None else message[:1000],
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def _log_scrape_attempt(
    url: str,
    jina_url: str,
    attempt: int,
    started: float,
    response: Optional["httpx.Response"] = None,
    error: Optional[Exception] = None,
    failure_kind: Optional[str] = None,
    message: str = "",
    queue_wait_ms: float = 0.0,
    record_response_body: bool = True,
) -> None:
    """Append task-scoped scrape telemetry without changing the tool response."""
    path = os.environ.get("JINA_SCRAPE_EVENT_LOG", "")
    if not path:
        return
    try:
        success = (
            error is None
            and failure_kind is None
            and response is not None
            and response.is_success
        )
        response_body = (
            (response.text or "") if record_response_body and response is not None and not success else ""
        )
        record = {
            "event": "jina_scrape_attempt" if success else "jina_scrape_failure",
            "timestamp_unix": time.time(),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "mcp_server": "research-primitives",
            "run_name": os.environ.get("MCPUNIVERSE_RUN_NAME", ""),
            "task_id": os.environ.get("MCPUNIVERSE_TASK_ID", ""),
            "url": url,
            "jina_url": jina_url,
            "attempt": attempt,
            "success": success,
            "failure_kind": (
                None
                if success
                else failure_kind
                or ("request_error" if error is not None else "unknown_failure")
            ),
            "status_code": response.status_code if response is not None else None,
            "response_bytes": len(response.content) if response is not None else None,
            "response_body_preview": response_body[:SCRAPE_FAILURE_BODY_MAX_CHARS],
            "response_body_truncated": len(response_body) > SCRAPE_FAILURE_BODY_MAX_CHARS,
            "retry_after": (
                response.headers.get("retry-after") if response is not None else None
            ),
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error)[:1000] if error is not None else message[:1000],
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        # Telemetry must never affect the benchmark's observable tool behavior.
        pass


class _SerperRequestSlot:
    """Fair host-wide Serper semaphore backed by ticket and lock files.

    Keeping the ticket until the request releases its slot prevents newly
    arriving searches from repeatedly overtaking older waiters.  This matters
    during 64-process evaluations, where the former opportunistic scan could
    starve one request for many minutes.
    """

    _queue_cache = {}
    _dead_ticket_checks = {}

    def __init__(self) -> None:
        self._fd: Optional[int] = None
        self._ticket_path: Optional[str] = None

    @staticmethod
    def _scope_dir() -> str:
        identity = hashlib.sha256(
            f"{SERPER_BASE_URL}\0{SERPER_API_KEY}".encode("utf-8")
        ).hexdigest()[:16]
        return os.path.join(SERPER_SLOT_DIR, identity)

    @staticmethod
    def _remove_dead_tickets(queue_dir: str) -> None:
        """Remove dead tickets, sharing a bounded scan rate across local waiters."""
        now = time.monotonic()
        previous = _SerperRequestSlot._dead_ticket_checks.get(queue_dir)
        if previous is not None and now - previous < 0.5:
            return
        _SerperRequestSlot._dead_ticket_checks[queue_dir] = now
        try:
            names = os.listdir(queue_dir)
        except FileNotFoundError:
            return
        for name in names:
            if not name.endswith(".ticket"):
                continue
            path = os.path.join(queue_dir, name)
            try:
                with open(path, "r", encoding="ascii") as handle:
                    owner = handle.read().strip()
                pid = int(owner or name.split("-", 2)[1])
                os.kill(pid, 0)
            except ProcessLookupError:
                try:
                    os.unlink(path)
                    _SerperRequestSlot._queue_cache.pop(queue_dir, None)
                except FileNotFoundError:
                    pass
            except (OSError, ValueError):
                # Permission errors indicate a live process owned by another
                # identity. Malformed tickets are left alone rather than
                # risking removal of an active waiter.
                continue

    @staticmethod
    def _queue_head(queue_dir: str):
        """Reuse the sorted queue head for at most one polling interval.

        Local ticket insertion and removal invalidate the view immediately.
        Other processes' removals can only delay the next eligible waiter by
        one poll; host-wide file locks continue to enforce request capacity.
        """
        now = time.monotonic()
        cached = _SerperRequestSlot._queue_cache.get(queue_dir)
        if cached is None or now - cached[0] >= SERPER_SLOT_POLL_SECONDS:
            head = sorted(
                name for name in os.listdir(queue_dir) if name.endswith(".ticket")
            )[:SERPER_MAX_CONCURRENCY]
            cached = (now, head)
            _SerperRequestSlot._queue_cache[queue_dir] = cached
        return cached[1]

    @staticmethod
    def _create_ticket(queue_dir: str) -> str:
        pid = os.getpid()
        while True:
            name = (
                f"{time.time_ns():020d}-{pid:010d}-"
                f"{random.getrandbits(64):016x}.ticket"
            )
            path = os.path.join(queue_dir, name)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            try:
                os.write(fd, str(pid).encode("ascii"))
            finally:
                os.close(fd)
            _SerperRequestSlot._queue_cache.pop(queue_dir, None)
            return path

    def _remove_ticket(self) -> None:
        if self._ticket_path is None:
            return
        try:
            os.unlink(self._ticket_path)
        except FileNotFoundError:
            pass
        _SerperRequestSlot._queue_cache.pop(os.path.dirname(self._ticket_path), None)
        self._ticket_path = None

    async def __aenter__(self) -> "_SerperRequestSlot":
        scope_dir = self._scope_dir()
        os.makedirs(scope_dir, mode=0o700, exist_ok=True)
        queue_dir = os.path.join(scope_dir, "queue")
        os.makedirs(queue_dir, mode=0o700, exist_ok=True)
        self._remove_dead_tickets(queue_dir)
        self._ticket_path = self._create_ticket(queue_dir)
        ticket_name = os.path.basename(self._ticket_path)
        start_slot = (os.getpid() + time.monotonic_ns()) % SERPER_MAX_CONCURRENCY
        try:
            while True:
                self._remove_dead_tickets(queue_dir)
                tickets = self._queue_head(queue_dir)
                if ticket_name in tickets[:SERPER_MAX_CONCURRENCY]:
                    for offset in range(SERPER_MAX_CONCURRENCY):
                        slot = (start_slot + offset) % SERPER_MAX_CONCURRENCY
                        path = os.path.join(scope_dir, f"slot-{slot:03d}.lock")
                        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            os.close(fd)
                            continue
                        self._fd = fd
                        return self
                jitter = random.uniform(0.75, 1.25)
                await asyncio.sleep(SERPER_SLOT_POLL_SECONDS * jitter)
        except BaseException:
            self._remove_ticket()
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        if self._fd is None:
            self._remove_ticket()
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
            self._remove_ticket()


async def _get_serper_client() -> "httpx.AsyncClient":
    """Return one keep-alive Serper client for the current program loop."""
    global _SERPER_CLIENT, _SERPER_CLIENT_LOOP
    loop = asyncio.get_running_loop()
    if (
        _SERPER_CLIENT is not None
        and not _SERPER_CLIENT.is_closed
        and _SERPER_CLIENT_LOOP is loop
    ):
        return _SERPER_CLIENT
    if _SERPER_CLIENT is not None and not _SERPER_CLIENT.is_closed:
        try:
            await _SERPER_CLIENT.aclose()
        except (RuntimeError, httpx.HTTPError):
            pass
    _SERPER_CLIENT = httpx.AsyncClient(
        timeout=httpx.Timeout(
            None,
            connect=SERPER_CONNECT_TIMEOUT_SECONDS,
            read=SERPER_READ_TIMEOUT_SECONDS,
        ),
        limits=httpx.Limits(
            max_connections=SERPER_MAX_CONCURRENCY,
            max_keepalive_connections=SERPER_MAX_CONCURRENCY,
            keepalive_expiry=60,
        ),
    )
    _SERPER_CLIENT_LOOP = loop
    return _SERPER_CLIENT


async def _close_serper_client() -> None:
    global _SERPER_CLIENT, _SERPER_CLIENT_LOOP
    client = _SERPER_CLIENT
    _SERPER_CLIENT = None
    _SERPER_CLIENT_LOOP = None
    if client is not None and not client.is_closed:
        try:
            await client.aclose()
        except RuntimeError:
            pass


def _get_jina_admission_gate() -> asyncio.Semaphore:
    """Keep waiters outside HTTPX's connection-assignment queue.

    The existing per-process HTTP connection limit remains unchanged. Large
    asyncio.gather calls wait on this cheap semaphore, so connection-pool
    bookkeeping and cancellation stay bounded by the connection limit.
    """
    global _JINA_ADMISSION_GATE, _JINA_ADMISSION_LOOP
    loop = asyncio.get_running_loop()
    if _JINA_ADMISSION_GATE is None or _JINA_ADMISSION_LOOP is not loop:
        _JINA_ADMISSION_GATE = asyncio.Semaphore(JINA_MAX_CONCURRENCY)
        _JINA_ADMISSION_LOOP = loop
    return _JINA_ADMISSION_GATE


async def _get_jina_client() -> "httpx.AsyncClient":
    """Return one keep-alive client for the current program event loop."""
    global _JINA_CLIENT, _JINA_CLIENT_LOOP
    loop = asyncio.get_running_loop()
    if (
        _JINA_CLIENT is not None
        and not _JINA_CLIENT.is_closed
        and _JINA_CLIENT_LOOP is loop
    ):
        return _JINA_CLIENT
    if _JINA_CLIENT is not None and not _JINA_CLIENT.is_closed:
        try:
            await _JINA_CLIENT.aclose()
        except (RuntimeError, httpx.HTTPError):
            # A previous asyncio.run() loop may already be closed. The runner
            # subprocess exits after one program, so dropping that stale pool
            # is safe and its sockets are reclaimed by process teardown.
            pass
    _JINA_CLIENT = httpx.AsyncClient(
        timeout=httpx.Timeout(
            None,
            connect=JINA_CONNECT_TIMEOUT_SECONDS,
            read=JINA_READ_TIMEOUT_SECONDS,
        ),
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=JINA_MAX_CONCURRENCY,
            max_keepalive_connections=JINA_MAX_CONCURRENCY,
            keepalive_expiry=60,
        ),
    )
    _JINA_CLIENT_LOOP = loop
    return _JINA_CLIENT


async def _close_jina_client() -> None:
    """Close the current program's connection pool (primarily for tests)."""
    global _JINA_CLIENT, _JINA_CLIENT_LOOP
    client = _JINA_CLIENT
    _JINA_CLIENT = None
    _JINA_CLIENT_LOOP = None
    if client is not None and not client.is_closed:
        try:
            await client.aclose()
        except RuntimeError:
            pass


async def _sleep_before_jina_retry(attempt: int) -> None:
    delay = min(
        JINA_RETRY_MAX_SECONDS,
        JINA_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1)),
    )
    if delay:
        await asyncio.sleep(random.uniform(delay * 0.5, delay * 1.5))


async def _sleep_before_serper_retry(attempt: int) -> None:
    delay = min(
        SERPER_RETRY_MAX_SECONDS,
        SERPER_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1)),
    )
    if delay:
        await asyncio.sleep(random.uniform(delay * 0.5, delay * 1.5))

# Summary LLM
SUMMARY_LLM_BASE_URL = os.environ.get("SUMMARY_LLM_BASE_URL")
SUMMARY_LLM_MODEL_NAME = os.environ.get("SUMMARY_LLM_MODEL_NAME")
SUMMARY_LLM_API_KEY = os.environ.get("SUMMARY_LLM_API_KEY")
SUMMARY_LLM_REASONING_EFFORT = os.environ.get(
    "SUMMARY_LLM_REASONING_EFFORT", "none"
)

DEFAULT_TIMEOUT = 240
# Hard cap on a single program's wall budget. Deployments that raise it must
# also configure the MCP client's per-call timeout above this value. Override
# with RP_MAX_PROGRAM_TIMEOUT.
_MAX_PROGRAM_TIMEOUT = int(os.environ.get("RP_MAX_PROGRAM_TIMEOUT", "240"))
_STANDARD_PROGRAM_TIMEOUT_FLOOR = int(
    os.environ.get("RP_STANDARD_PROGRAM_TIMEOUT_FLOOR", "0")
)
MAX_STDOUT_CHARS = 16000
SCRAPE_MAX_CHARS = 102400 * 4  # 409,600
SUMMARY_CONTENT_CAP = 200000


def _effective_program_timeout(timeout: int) -> int:
    """Apply an opt-in operational floor without changing the tool schema.

    The model-visible default remains 240 seconds, matching training.  Large
    production fan-outs can opt into a longer internal floor so time spent in
    host-wide upstream queues does not abort otherwise valid programs.
    """
    requested = max(1, int(timeout))
    effective = min(requested, _MAX_PROGRAM_TIMEOUT)
    if _STANDARD_PROGRAM_TIMEOUT_FLOOR > 0:
        effective = max(
            effective,
            min(_STANDARD_PROGRAM_TIMEOUT_FLOOR, _MAX_PROGRAM_TIMEOUT),
        )
    return effective


EXTRACT_INFO_PROMPT = (
    "You are given a piece of content and the requirement of "
    "information to extract. Your task is to extract the information "
    "specifically requested. Be precise and focus exclusively on the "
    "requested information.\n\n"
    "    INFORMATION TO EXTRACT:\n"
    "    {}\n\n"
    "    INSTRUCTIONS:\n"
    "    1. Extract the information relevant to the focus above.\n"
    "    2. If the exact information is not found, extract the most "
    "closely related details.\n"
    "    3. Be specific and include exact details when available.\n"
    "    4. Clearly organize the extracted information for easy "
    "understanding.\n"
    "    5. Do not include general summaries or unrelated content.\n\n"
    "    CONTENT TO ANALYZE:\n"
    "    {}\n\n"
    "    EXTRACTED INFORMATION:"
)


def _is_hf_dataset_or_space(url: str) -> bool:
    """Original GCP/September 14 literal URL filter (legacy_minimal)."""
    if not url:
        return False
    return "huggingface.co/datasets" in url or "huggingface.co/spaces" in url


# ------------------------------------------------------------------
# Primitives
# ------------------------------------------------------------------

async def _api_search(
    q: str,
    num: int = 10,
    gl: str = "us",
    hl: str = "en",
    location: Optional[str] = None,
    tbs: Optional[str] = None,
):
    """Run ONE Google search; returns [{title, link, snippet}, ...].

    Use ``await asyncio.gather(*[search(q) for q in queries])`` for
    parallel multi-query search.
    """
    if not SERPER_API_KEY:
        return [{"error": "SERPER_API_KEY not set"}]
    if not q or not q.strip():
        return []
    payload: Dict[str, Any] = {"q": q.strip(), "gl": gl, "hl": hl, "num": num}
    if location:
        payload["location"] = location
    if tbs:
        payload["tbs"] = tbs
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    last_error = "unknown Serper error"
    data: Dict[str, Any] = {}
    for attempt in range(1, SERPER_MAX_ATTEMPTS + 1):
        queued_at = time.monotonic()
        request_started = queued_at
        queue_wait_ms = 0.0
        resp = None
        try:
            async with _SerperRequestSlot():
                request_started = time.monotonic()
                queue_wait_ms = (request_started - queued_at) * 1000
                client = await _get_serper_client()
                resp = await client.post(
                    f"{SERPER_BASE_URL}/search",
                    json=payload,
                    headers=headers,
                )
            if (
                resp.status_code in SERPER_RETRYABLE_STATUS_CODES
                and attempt < SERPER_MAX_ATTEMPTS
            ):
                _log_search_attempt(
                    q,
                    attempt,
                    request_started,
                    response=resp,
                    failure_kind="retryable_http_status",
                    message=f"retryable HTTP {resp.status_code}",
                    queue_wait_ms=queue_wait_ms,
                )
                await _sleep_before_serper_retry(attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            _log_search_attempt(
                q,
                attempt,
                request_started,
                response=resp,
                error=exc,
                queue_wait_ms=queue_wait_ms,
            )
            last_error = str(exc)
            if attempt < SERPER_MAX_ATTEMPTS and isinstance(exc, httpx.TransportError):
                await _sleep_before_serper_retry(attempt)
                continue
            return [{"error": f"search failed: {exc}"}]
        _log_search_attempt(
            q,
            attempt,
            request_started,
            response=resp,
            queue_wait_ms=queue_wait_ms,
        )
        break
    else:
        return [{"error": f"search failed: {last_error}"}]

    out = []
    for item in data.get("organic", []) or []:
        link = item.get("link", "")
        if _is_hf_dataset_or_space(link):
            continue
        out.append({
            "title": item.get("title", ""),
            "link": link,
            "snippet": item.get("snippet", ""),
        })
    return out


def _jina_reader_url(url: str) -> str:
    """Build a reader URL without leaking target query args to 302.ai.

    The 302.ai gateway parses query parameters before forwarding the request.
    A target such as ``...?page=Unlambda`` is therefore mistaken for its own
    integer ``page`` option and rejected. Double encoding survives the
    gateway's first decode and lets Jina receive the original target URL.

    Search results occasionally point at an already wrapped official Jina
    Reader URL. Unwrap it before routing through the configured reader;
    otherwise the upstream rejects the request as a circular ``r.jina.ai``
    target.
    """
    parsed_target = urlsplit(url)
    if (parsed_target.hostname or "").lower() == "r.jina.ai":
        nested_target = unquote(parsed_target.path.lstrip("/"))
        if parsed_target.query:
            nested_target = f"{nested_target}?{parsed_target.query}"
        if nested_target.startswith(("http://", "https://")):
            url = nested_target

    host = (urlsplit(JINA_BASE_URL).hostname or "").lower()
    encode_for_302 = host.endswith("302.ai") or JINA_FORCE_302_TARGET_ENCODING
    target = quote(quote(url, safe=":/"), safe=":/") if encode_for_302 else url
    return f"{JINA_BASE_URL.rstrip('/')}/{target}"


async def _api_scrape(url: str, max_chars: int = SCRAPE_MAX_CHARS) -> str:
    """Scrape ONE URL via Jina Reader; returns raw markdown text.

    No LLM call. Use ``await asyncio.gather(*[scrape(u) for u in urls])``
    for parallel multi-URL scraping.
    """
    if not JINA_API_KEY:
        return "[error: JINA_API_KEY not set]"
    if _is_hf_dataset_or_space(url):
        return "[error: HF dataset/space URLs are not allowed]"
    jina_url = _jina_reader_url(url)
    headers = {"Authorization": f"Bearer {JINA_API_KEY}"}
    last_error = "unknown Jina error"
    for attempt in range(1, JINA_MAX_ATTEMPTS + 1):
        request_started = time.monotonic()
        resp = None
        try:
            async with _get_jina_admission_gate():
                client = await _get_jina_client()
                resp = await client.get(jina_url, headers=headers)

            if (
                resp.status_code in JINA_RETRYABLE_STATUS_CODES
                and attempt < JINA_MAX_ATTEMPTS
            ):
                _log_scrape_attempt(
                    url,
                    jina_url,
                    attempt,
                    request_started,
                    response=resp,
                    failure_kind="retryable_http_status",
                    message=f"retryable HTTP {resp.status_code}",
                    queue_wait_ms=0.0,
                )
                await _sleep_before_jina_retry(attempt)
                continue
            resp.raise_for_status()
        except Exception as exc:
            # resp is set on HTTP-status errors (captures status_code), None otherwise.
            _log_scrape_attempt(
                url,
                jina_url,
                attempt,
                request_started,
                response=resp,
                error=exc,
                queue_wait_ms=0.0,
            )
            last_error = str(exc)
            if attempt < JINA_MAX_ATTEMPTS and isinstance(exc, httpx.TransportError):
                await _sleep_before_jina_retry(attempt)
                continue
            return f"[error scraping {url}: {exc}]"

        text = resp.text or ""
        try:
            as_dict = json.loads(text)
            if (
                isinstance(as_dict, dict)
                and as_dict.get("name") == "InsufficientBalanceError"
            ):
                _log_scrape_attempt(
                    url,
                    jina_url,
                    attempt,
                    request_started,
                    response=resp,
                    failure_kind="insufficient_balance",
                    message="Jina insufficient balance",
                    queue_wait_ms=0.0,
                )
                return "[error: Jina insufficient balance]"
        except json.JSONDecodeError:
            pass
        _log_scrape_attempt(
            url,
            jina_url,
            attempt,
            request_started,
            response=resp,
            queue_wait_ms=0.0,
        )
        return text[:max_chars]
    return f"[error scraping {url}: {last_error}]"


def _summary_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not SUMMARY_LLM_API_KEY:
        return headers
    base = SUMMARY_LLM_BASE_URL or ""
    if "generativelanguage.googleapis" in base:
        headers["x-goog-api-key"] = SUMMARY_LLM_API_KEY
    elif "gemini" in (SUMMARY_LLM_MODEL_NAME or "") and "openrouter" not in base \
            and "requesty" not in base:
        # Optionally read a refreshed Vertex access token from a local file.
        token_file = os.environ.get("SUMMARY_LLM_TOKEN_FILE")
        if token_file and os.path.isfile(token_file):
            with open(token_file, encoding="utf-8") as f:
                token = f.read().strip()
        else:
            token = subprocess.check_output(
                ["gcloud", "auth", "application-default", "print-access-token"]
            ).decode().strip()
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["Authorization"] = f"Bearer {SUMMARY_LLM_API_KEY}"
    return headers


def _summary_payload(prompt: str, max_tokens: int) -> Dict[str, Any]:
    model = SUMMARY_LLM_MODEL_NAME or ""
    base = SUMMARY_LLM_BASE_URL or ""
    if "gpt" in model:
        payload: Dict[str, Any] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if "gpt-5-mini" in model:
            payload["reasoning_effort"] = "minimal"
        elif "gpt-5.4-mini" in model:
            payload["reasoning_effort"] = "none"
        return payload
    if "gemini" in model and "openrouter" not in base and "requesty" not in base:
        return {
            "contents": {"role": "user", "parts": [{"text": prompt}]},
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
    if "gemini" in model:
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            # Requesty maps reasoning_effort onto Vertex Gemini thinking.
            # Keep the historical default (none), while allowing rollout
            # launchers to opt into low reasoning for newer Gemini summaries.
            "reasoning_effort": SUMMARY_LLM_REASONING_EFFORT,
        }
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.0,
    }


def _parse_summary_response(data: Dict[str, Any]) -> str:
    if "choices" in data and data["choices"]:
        return data["choices"][0]["message"]["content"]
    if "candidates" in data and data["candidates"]:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    if "error" in data:
        return f"[summary error: {data['error']}]"
    return f"[summary: no parse path for response: {str(data)[:200]}]"


async def _api_llm_summary(
    content: str,
    question: str,
    max_tokens: int = 4096,
) -> str:
    """Run ONE LLM extraction over `content` for `question`.

    Returns the extracted text. NOT bound to any URL — pass any string,
    including content concatenated from multiple scrapes.

    For per-document extraction, gather scrapes first then
    ``await asyncio.gather(*[llm_summary(t, q) for t in texts])``.
    For one combined answer over many docs, concatenate the texts (with
    clear source separators) and call `llm_summary` ONCE.
    """
    if not SUMMARY_LLM_BASE_URL or not SUMMARY_LLM_BASE_URL.strip():
        return "[error: SUMMARY_LLM_BASE_URL not set]"
    if not content or not content.strip():
        return "[error: content is empty]"
    capped = content[:SUMMARY_CONTENT_CAP]
    prompt = EXTRACT_INFO_PROMPT.format(question, capped)
    payload = _summary_payload(prompt, max_tokens)
    headers = _summary_headers()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SUMMARY_LLM_BASE_URL,
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(None, connect=30, read=300),
            )
            resp.raise_for_status()
            return _parse_summary_response(resp.json())
    except Exception as exc:
        return f"[summary error: {exc}]"
