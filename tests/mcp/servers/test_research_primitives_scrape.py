import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from mcpuniverse.mcp.servers.research_primitives import backends as server


class _NoopSlot:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb


class TestResearchPrimitivesScrapeReliability(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await server._close_serper_client()
        await server._close_jina_client()

    async def asyncTearDown(self):
        await server._close_serper_client()
        await server._close_jina_client()

    async def test_keepalive_client_is_reused_on_one_event_loop(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.is_closed = False
        with patch.object(server.httpx, "AsyncClient", return_value=client) as factory:
            first = await server._get_jina_client()
            second = await server._get_jina_client()

        self.assertIs(first, client)
        self.assertIs(second, client)
        factory.assert_called_once()

    async def test_client_uses_configurable_connect_and_read_timeouts(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.is_closed = False
        with (
            patch.object(server, "JINA_CONNECT_TIMEOUT_SECONDS", 37.0),
            patch.object(server, "JINA_READ_TIMEOUT_SECONDS", 181.0),
            patch.object(server.httpx, "AsyncClient", return_value=client) as factory,
        ):
            await server._get_jina_client()

        configured = factory.call_args.kwargs["timeout"]
        self.assertEqual(configured.connect, 37.0)
        self.assertEqual(configured.read, 181.0)

    def test_standard_timeout_floor_applies_to_short_explicit_timeouts(self):
        with (
            patch.object(server, "_MAX_PROGRAM_TIMEOUT", 1800),
            patch.object(server, "_STANDARD_PROGRAM_TIMEOUT_FLOOR", 1800),
        ):
            self.assertEqual(server._effective_program_timeout(120), 1800)
            self.assertEqual(server._effective_program_timeout(240), 1800)
            self.assertEqual(server._effective_program_timeout(600), 1800)
            self.assertEqual(server._effective_program_timeout(2400), 1800)

    def test_302_reader_double_encodes_target_query(self):
        target = (
            "https://en.wikipedia.org/w/api.php?action=parse&page=Unlambda"
            "&prop=wikitext&format=json&formatversion=2"
        )
        with patch.object(server, "JINA_BASE_URL", "https://api.302.ai/jina/reader"):
            result = server._jina_reader_url(target)

        self.assertEqual(
            result,
            "https://api.302.ai/jina/reader/https://en.wikipedia.org/w/api.php"
            "%253Faction%253Dparse%2526page%253DUnlambda%2526prop%253Dwikitext"
            "%2526format%253Djson%2526formatversion%253D2",
        )

    def test_standard_reader_keeps_target_query_unchanged(self):
        target = "https://example.com/path?q=one&page=two"
        with patch.object(server, "JINA_BASE_URL", "https://r.jina.ai/"):
            result = server._jina_reader_url(target)

        self.assertEqual(result, f"https://r.jina.ai/{target}")

    def test_relay_can_force_302_target_encoding(self):
        target = "https://example.com/path?q=one&page=two"
        with (
            patch.object(server, "JINA_BASE_URL", "http://relay.internal:19080"),
            patch.object(server, "JINA_FORCE_302_TARGET_ENCODING", True),
        ):
            result = server._jina_reader_url(target)

        self.assertEqual(
            result,
            "http://relay.internal:19080/https://example.com/path"
            "%253Fq%253Done%2526page%253Dtwo",
        )

    def test_reader_unwraps_existing_jina_url(self):
        target = "https://r.jina.ai/http://api.example.com/notes?q=one&page=two"
        with patch.object(server, "JINA_BASE_URL", "https://api.302.ai/jina/reader"):
            result = server._jina_reader_url(target)

        self.assertEqual(
            result,
            "https://api.302.ai/jina/reader/http://api.example.com/notes"
            "%253Fq%253Done%2526page%253Dtwo",
        )

    def test_reader_unwraps_encoded_existing_jina_url(self):
        target = "https://r.jina.ai/https%3A%2F%2Fexample.com%2Fpage"
        with patch.object(server, "JINA_BASE_URL", "https://r.jina.ai"):
            result = server._jina_reader_url(target)

        self.assertEqual(result, "https://r.jina.ai/https://example.com/page")

    async def test_serper_connect_timeout_is_retried_with_telemetry(self):
        request = httpx.Request("POST", "https://google.serper.dev/search")
        response = httpx.Response(
            200,
            request=request,
            json={
                "organic": [
                    {
                        "title": "Recovered",
                        "link": "https://example.com/page",
                        "snippet": "result",
                    }
                ]
            },
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = [
            httpx.ConnectTimeout("connect timed out", request=request),
            response,
        ]

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "search.jsonl"
            with (
                patch.dict(
                    "os.environ",
                    {"SERPER_SEARCH_EVENT_LOG": str(log_path)},
                    clear=False,
                ),
                patch.object(server, "SERPER_API_KEY", "test-key"),
                patch.object(server, "SERPER_BASE_URL", "https://google.serper.dev"),
                patch.object(server, "SERPER_MAX_ATTEMPTS", 3),
                patch.object(server, "_SerperRequestSlot", return_value=_NoopSlot()),
                patch.object(
                    server, "_get_serper_client", new=AsyncMock(return_value=client)
                ),
                patch.object(
                    server,
                    "_sleep_before_serper_retry",
                    new=AsyncMock(),
                ) as retry_sleep,
            ):
                result = await server._api_search("recovery test")

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result[0]["title"], "Recovered")
        self.assertEqual(client.post.await_count, 2)
        retry_sleep.assert_awaited_once_with(1)
        self.assertEqual([record["attempt"] for record in records], [1, 2])
        self.assertEqual(records[0]["event"], "serper_search_failure")
        self.assertEqual(records[1]["event"], "serper_search_attempt")

    async def test_connect_timeout_is_retried_and_telemetry_records_attempts(self):
        request = httpx.Request(
            "GET", "https://r.jina.ai/https://example.com/page"
        )
        response = httpx.Response(200, request=request, text="# recovered")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.ConnectTimeout("connect timed out", request=request),
            response,
        ]

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "scrape.jsonl"
            with (
                patch.dict(
                    "os.environ",
                    {"JINA_SCRAPE_EVENT_LOG": str(log_path)},
                    clear=False,
                ),
                patch.object(server, "JINA_API_KEY", "test-key"),
                patch.object(server, "JINA_BASE_URL", "https://r.jina.ai"),
                patch.object(server, "JINA_MAX_ATTEMPTS", 3),
                patch.object(
                    server, "_get_jina_client", new=AsyncMock(return_value=client)
                ),
                patch.object(
                    server,
                    "_sleep_before_jina_retry",
                    new=AsyncMock(),
                ) as retry_sleep,
            ):
                result = await server._api_scrape("https://example.com/page")

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result, "# recovered")
        self.assertEqual(client.get.await_count, 2)
        retry_sleep.assert_awaited_once_with(1)
        self.assertEqual([record["attempt"] for record in records], [1, 2])
        self.assertEqual(records[0]["event"], "jina_scrape_failure")
        self.assertEqual(records[0]["error_type"], "ConnectTimeout")
        self.assertEqual(records[1]["event"], "jina_scrape_attempt")
        self.assertIn("queue_wait_ms", records[0])

    async def test_retryable_gateway_status_is_retried(self):
        request = httpx.Request(
            "GET", "https://r.jina.ai/https://example.com/page"
        )
        overloaded = httpx.Response(524, request=request, text="gateway timeout")
        recovered = httpx.Response(200, request=request, text="recovered")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [overloaded, recovered]

        with (
            patch.object(server, "JINA_API_KEY", "test-key"),
            patch.object(server, "JINA_MAX_ATTEMPTS", 3),
            patch.object(
                server, "_get_jina_client", new=AsyncMock(return_value=client)
            ),
            patch.object(
                server,
                "_sleep_before_jina_retry",
                new=AsyncMock(),
            ) as retry_sleep,
        ):
            result = await server._api_scrape("https://example.com/page")

        self.assertEqual(result, "recovered")
        self.assertEqual(client.get.await_count, 2)
        retry_sleep.assert_awaited_once_with(1)

    async def test_nonretryable_http_status_returns_immediately(self):
        request = httpx.Request(
            "GET", "https://r.jina.ai/https://example.com/page"
        )
        response = httpx.Response(401, request=request, text="unauthorized")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = response

        with (
            patch.object(server, "JINA_API_KEY", "test-key"),
            patch.object(server, "JINA_MAX_ATTEMPTS", 3),
            patch.object(
                server, "_get_jina_client", new=AsyncMock(return_value=client)
            ),
            patch.object(
                server,
                "_sleep_before_jina_retry",
                new=AsyncMock(),
            ) as retry_sleep,
        ):
            result = await server._api_scrape("https://example.com/page")

        self.assertIn("401 Unauthorized", result)
        self.assertEqual(client.get.await_count, 1)
        retry_sleep.assert_not_awaited()

    async def test_serper_file_slots_preserve_waiter_order(self):
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        order = []

        async def enter(index, hold=False):
            async with server._SerperRequestSlot():
                order.append(index)
                if hold:
                    first_entered.set()
                    await release_first.wait()

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(server, "SERPER_SLOT_DIR", tmp),
                patch.object(server, "SERPER_MAX_CONCURRENCY", 1),
                patch.object(server, "SERPER_SLOT_POLL_SECONDS", 0.005),
            ):
                first = asyncio.create_task(enter(0, hold=True))
                await first_entered.wait()
                second = asyncio.create_task(enter(1))
                await asyncio.sleep(0.03)
                third = asyncio.create_task(enter(2))
                await asyncio.sleep(0.03)
                release_first.set()
                await asyncio.wait_for(
                    asyncio.gather(first, second, third), timeout=2
                )

            self.assertFalse(list(Path(tmp).rglob("*.ticket")))

        self.assertEqual(order, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
