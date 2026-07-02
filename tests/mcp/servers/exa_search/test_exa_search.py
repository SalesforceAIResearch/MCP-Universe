"""Unit tests for the exa_search MCP server.

These tests hit no network: the Exa SDK call is mocked out at the
AsyncExa source module, because ``exa_search.server._exa_search``
imports ``AsyncExa`` locally at call time.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcpuniverse.mcp.servers.exa_search.server import (
    ExaSearchResult,
    _build_contents,
    _extract_snippet,
    _parse_result,
    build_server,
)


def _fake_response(results):
    return SimpleNamespace(
        results=results,
        request_id="req_test_123",
        resolved_search_type="neural",
    )


class TestExaSearchHelpers(unittest.TestCase):

    def test_extract_snippet_prefers_highlights(self):
        snippet = _extract_snippet(
            text="long body text here",
            highlights=["first highlight", "second highlight"],
            summary="a concise summary",
        )
        self.assertIn("first highlight", snippet)
        self.assertIn("second highlight", snippet)

    def test_extract_snippet_falls_back_to_summary(self):
        snippet = _extract_snippet(
            text="long body text here",
            highlights=[],
            summary="a concise summary",
        )
        self.assertEqual(snippet, "a concise summary")

    def test_extract_snippet_falls_back_to_text(self):
        snippet = _extract_snippet(
            text="x" * 1000,
            highlights=[],
            summary=None,
        )
        self.assertEqual(len(snippet), 500)

    def test_extract_snippet_none_when_no_content(self):
        self.assertIsNone(_extract_snippet(None, [], None))

    def test_parse_result_with_highlights(self):
        raw = {
            "id": "abc",
            "title": "Example",
            "url": "https://example.com",
            "publishedDate": "2026-01-01",
            "author": "Jane Doe",
            "score": 0.87,
            "highlights": ["h1", "h2"],
        }
        result = _parse_result(raw)
        self.assertIsInstance(result, ExaSearchResult)
        self.assertEqual(result.title, "Example")
        self.assertEqual(result.published_date, "2026-01-01")
        self.assertEqual(result.highlights, ["h1", "h2"])
        self.assertIn("h1", result.snippet)

    def test_parse_result_summary_only(self):
        raw = {
            "title": "S",
            "url": "https://example.com/s",
            "summary": "just a summary",
        }
        result = _parse_result(raw)
        self.assertEqual(result.snippet, "just a summary")
        self.assertEqual(result.highlights, [])
        self.assertIsNone(result.text)

    def test_build_contents_none_when_all_off(self):
        self.assertIsNone(_build_contents(False, False, False, None, None))

    def test_build_contents_highlights_only(self):
        contents = _build_contents(False, True, False, None, None)
        self.assertEqual(contents, {"highlights": True})

    def test_build_contents_with_text_cap(self):
        contents = _build_contents(True, False, False, 2000, None)
        self.assertEqual(contents, {"text": {"max_characters": 2000}})


class TestExaSearchServer(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.server = build_server(port=12345)

    async def test_server_tools_registered(self):
        tools = await self.server.list_tools()
        self.assertIn("search", [tool.name for tool in tools])

    async def test_search_disabled_without_api_key(self):
        # Clear the env var to simulate missing key.
        with patch.dict(os.environ, {"EXA_API_KEY": ""}, clear=False):
            with patch(
                "mcpuniverse.mcp.servers.exa_search.server.EXA_API_KEY", ""
            ):
                result = await self.server.call_tool(
                    "search", arguments={"query": "anything"}
                )
        # FastMCP returns (content, structured) where structured is the dict.
        payload = self._unwrap(result)
        self.assertFalse(payload.get("success"))
        self.assertIn("EXA_API_KEY", payload.get("error", ""))

    async def test_search_rejects_empty_query(self):
        with patch(
            "mcpuniverse.mcp.servers.exa_search.server.EXA_API_KEY",
            "test-key",
        ):
            result = await self.server.call_tool(
                "search", arguments={"query": "   "}
            )
        payload = self._unwrap(result)
        self.assertFalse(payload.get("success"))
        self.assertIn("required", payload.get("error", ""))

    async def test_search_rejects_bad_search_type(self):
        with patch(
            "mcpuniverse.mcp.servers.exa_search.server.EXA_API_KEY",
            "test-key",
        ):
            result = await self.server.call_tool(
                "search",
                arguments={"query": "hello", "search_type": "keyword"},
            )
        payload = self._unwrap(result)
        self.assertFalse(payload.get("success"))
        self.assertIn("search_type", payload.get("error", ""))

    async def test_search_happy_path(self):
        fake_results = [
            {
                "id": "r1",
                "title": "First",
                "url": "https://a.example.com",
                "publishedDate": "2026-01-01",
                "author": "Ann",
                "score": 0.9,
                "highlights": ["hello world"],
            },
            {
                "id": "r2",
                "title": "Second",
                "url": "https://b.example.com",
                "summary": "summary only",
            },
        ]

        fake_client = SimpleNamespace(
            headers={},
            search=AsyncMock(return_value=_fake_response(fake_results)),
        )

        # The server does `from exa_py import AsyncExa` inside the search
        # function, so patching at the source module is the only mock that
        # actually intercepts the real class.
        with patch("exa_py.AsyncExa", return_value=fake_client), patch(
            "mcpuniverse.mcp.servers.exa_search.server.EXA_API_KEY",
            "test-key",
        ):
            result = await self.server.call_tool(
                "search",
                arguments={"query": "exa test", "num_results": 2},
            )

        payload = self._unwrap(result)
        self.assertEqual(payload["query"], "exa test")
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["title"], "First")
        self.assertIn("hello world", payload["results"][0]["snippet"])
        self.assertEqual(payload["results"][1]["snippet"], "summary only")
        self.assertEqual(payload["request_id"], "req_test_123")

        # Verify the integration tracking header was set on the client.
        self.assertEqual(
            fake_client.headers.get("x-exa-integration"), "mcp-universe"
        )

        # Verify contents payload wired correctly (highlights default=True).
        call_kwargs = fake_client.search.call_args.kwargs
        self.assertEqual(call_kwargs["query"], "exa test")
        self.assertEqual(call_kwargs["num_results"], 2)
        self.assertEqual(call_kwargs["contents"], {"highlights": True})

    async def test_search_passes_filters(self):
        fake_client = SimpleNamespace(
            headers={},
            search=AsyncMock(return_value=_fake_response([])),
        )
        with patch("exa_py.AsyncExa", return_value=fake_client), patch(
            "mcpuniverse.mcp.servers.exa_search.server.EXA_API_KEY",
            "test-key",
        ):
            await self.server.call_tool(
                "search",
                arguments={
                    "query": "q",
                    "num_results": 5,
                    "category": "research paper",
                    "include_domains": ["arxiv.org"],
                    "start_published_date": "2026-01-01",
                    "text": True,
                    "highlights": False,
                    "text_max_characters": 1500,
                },
            )

        call_kwargs = fake_client.search.call_args.kwargs
        self.assertEqual(call_kwargs["category"], "research paper")
        self.assertEqual(call_kwargs["include_domains"], ["arxiv.org"])
        self.assertEqual(call_kwargs["start_published_date"], "2026-01-01")
        self.assertEqual(
            call_kwargs["contents"], {"text": {"max_characters": 1500}}
        )

    @staticmethod
    def _unwrap(tool_result):
        """FastMCP call_tool returns (content_list, structured_output)."""
        if isinstance(tool_result, tuple) and len(tool_result) == 2:
            content, structured = tool_result
            if isinstance(structured, dict):
                # FastMCP wraps non-model returns under a 'result' key.
                if set(structured.keys()) == {"result"}:
                    return structured["result"]
                return structured
            if content and hasattr(content[0], "text"):
                return json.loads(content[0].text)
        return tool_result


if __name__ == "__main__":
    unittest.main()
