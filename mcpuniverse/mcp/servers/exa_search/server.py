"""
An MCP server for Exa AI-powered web search.

Exa is a neural-embedding-based search engine that returns
full text, highlights, or LLM-generated summaries for each
result in a single API call.
"""
# pylint: disable=broad-exception-caught
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import click
from mcp.server.fastmcp import FastMCP

from mcpuniverse.common.logger import get_logger

EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
EXA_API_BASE = os.environ.get("EXA_API_BASE", "https://api.exa.ai")
INTEGRATION_NAME = "mcp-universe"

VALID_SEARCH_TYPES = {
    "auto", "neural", "fast", "deep-lite", "deep",
    "deep-reasoning", "instant",
}
VALID_CATEGORIES = {
    "company", "research paper", "news", "personal site",
    "financial report", "people",
}


@dataclass
class ExaSearchResult:
    """A single result from an Exa search response."""
    title: Optional[str] = None
    url: Optional[str] = None
    id: Optional[str] = None
    score: Optional[float] = None
    published_date: Optional[str] = None
    author: Optional[str] = None
    snippet: Optional[str] = None
    text: Optional[str] = None
    highlights: List[str] = field(default_factory=list)
    summary: Optional[str] = None


def _extract_snippet(text: Optional[str], highlights: List[str],
                     summary: Optional[str]) -> Optional[str]:
    """
    Pick the best short snippet across available content fields.

    Exa can return any combination of text, highlights, and summary
    depending on request options, so fall through in order of
    increasing length.
    """
    if highlights:
        return " ... ".join(h for h in highlights if h)
    if summary:
        return summary
    if text:
        return text[:500]
    return None


def _parse_result(raw: Dict[str, Any]) -> ExaSearchResult:
    highlights = raw.get("highlights") or []
    text = raw.get("text")
    summary = raw.get("summary")
    return ExaSearchResult(
        title=raw.get("title"),
        url=raw.get("url"),
        id=raw.get("id"),
        score=raw.get("score"),
        published_date=raw.get("publishedDate") or raw.get("published_date"),
        author=raw.get("author"),
        snippet=_extract_snippet(text, highlights, summary),
        text=text,
        highlights=list(highlights),
        summary=summary,
    )


def _build_contents(text: bool, highlights: bool, summary: bool,
                    text_max_characters: Optional[int],
                    highlights_per_url: Optional[int]) -> Optional[Dict[str, Any]]:
    """Build the nested `contents` payload for the Exa /search request."""
    if not any([text, highlights, summary]):
        return None
    contents: Dict[str, Any] = {}
    if text:
        if text_max_characters is not None:
            contents["text"] = {"max_characters": text_max_characters}
        else:
            contents["text"] = True
    if highlights:
        if highlights_per_url is not None:
            contents["highlights"] = {"num_sentences": highlights_per_url}
        else:
            contents["highlights"] = True
    if summary:
        contents["summary"] = True
    return contents


async def _exa_search(
    query: str,
    num_results: int = 10,
    search_type: str = "auto",
    category: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    include_text: Optional[List[str]] = None,
    exclude_text: Optional[List[str]] = None,
    start_published_date: Optional[str] = None,
    end_published_date: Optional[str] = None,
    user_location: Optional[str] = None,
    text: bool = False,
    highlights: bool = True,
    summary: bool = False,
    text_max_characters: Optional[int] = None,
    highlights_per_url: Optional[int] = None,
) -> Dict[str, Any]:
    """Call the Exa search API and return a normalized response."""
    from exa_py import AsyncExa  # local import so server imports cheaply

    client = AsyncExa(api_key=EXA_API_KEY, api_base=EXA_API_BASE)
    # Attribute API usage to this integration.
    client.headers["x-exa-integration"] = INTEGRATION_NAME

    kwargs: Dict[str, Any] = {"num_results": num_results, "type": search_type}
    contents = _build_contents(
        text=text,
        highlights=highlights,
        summary=summary,
        text_max_characters=text_max_characters,
        highlights_per_url=highlights_per_url,
    )
    if contents is not None:
        kwargs["contents"] = contents
    if category:
        kwargs["category"] = category
    if include_domains:
        kwargs["include_domains"] = include_domains
    if exclude_domains:
        kwargs["exclude_domains"] = exclude_domains
    if include_text:
        kwargs["include_text"] = include_text
    if exclude_text:
        kwargs["exclude_text"] = exclude_text
    if start_published_date:
        kwargs["start_published_date"] = start_published_date
    if end_published_date:
        kwargs["end_published_date"] = end_published_date
    if user_location:
        kwargs["user_location"] = user_location

    response = await client.search(query=query, **kwargs)

    parsed: List[ExaSearchResult] = []
    for item in getattr(response, "results", []) or []:
        raw = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        parsed.append(_parse_result(raw))

    return {
        "query": query,
        "results": [asdict(r) for r in parsed],
        "request_id": getattr(response, "request_id", None),
        "resolved_search_type": getattr(response, "resolved_search_type", None)
        or getattr(response, "search_type", None),
    }


def build_server(port: int) -> FastMCP:
    """
    Initialize the Exa search MCP server.

    :param port: Port for SSE.
    :return: The MCP server.
    """
    mcp = FastMCP("exa_search", port=port)

    @mcp.tool()
    async def search(
        query: str,
        num_results: int = 10,
        search_type: str = "auto",
        category: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        include_text: Optional[List[str]] = None,
        exclude_text: Optional[List[str]] = None,
        start_published_date: Optional[str] = None,
        end_published_date: Optional[str] = None,
        user_location: Optional[str] = None,
        text: bool = False,
        highlights: bool = True,
        summary: bool = False,
        text_max_characters: Optional[int] = None,
        highlights_per_url: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run an Exa AI-powered web search.

        Args:
            query: Search query string.
            num_results: Number of results to return (1-100, default 10).
            search_type: One of 'auto', 'neural', 'fast', 'deep-lite',
                'deep', 'deep-reasoning', 'instant' (default 'auto').
            category: Optional data-category filter. One of 'company',
                'research paper', 'news', 'personal site',
                'financial report', 'people'.
            include_domains: Restrict results to these domains.
            exclude_domains: Exclude results from these domains.
            include_text: Phrases that must appear in each page.
            exclude_text: Phrases that must not appear in each page.
            start_published_date: ISO 8601 minimum publication date.
            end_published_date: ISO 8601 maximum publication date.
            user_location: Two-letter ISO country code (e.g. 'US').
            text: Return the full page text for each result.
            highlights: Return highlighted snippets for each result
                (default True, very token-efficient).
            summary: Return an LLM-generated summary for each result.
            text_max_characters: Optional cap on full-text length.
            highlights_per_url: Optional number of highlight sentences.

        Returns:
            Dict with 'query', 'results' (list of typed result dicts
            with title, url, snippet, text, highlights, summary, etc.),
            'request_id', and 'resolved_search_type'.
        """
        if not EXA_API_KEY:
            return {
                "success": False,
                "error": "EXA_API_KEY environment variable not set",
                "results": [],
            }
        if not query or not query.strip():
            return {
                "success": False,
                "error": "Search query is required and cannot be empty",
                "results": [],
            }
        if search_type not in VALID_SEARCH_TYPES:
            return {
                "success": False,
                "error": (
                    f"Invalid search_type '{search_type}'. "
                    f"Must be one of: {sorted(VALID_SEARCH_TYPES)}"
                ),
                "results": [],
            }
        if category is not None and category not in VALID_CATEGORIES:
            return {
                "success": False,
                "error": (
                    f"Invalid category '{category}'. "
                    f"Must be one of: {sorted(VALID_CATEGORIES)}"
                ),
                "results": [],
            }
        try:
            return await _exa_search(
                query=query.strip(),
                num_results=num_results,
                search_type=search_type,
                category=category,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                include_text=include_text,
                exclude_text=exclude_text,
                start_published_date=start_published_date,
                end_published_date=end_published_date,
                user_location=user_location,
                text=text,
                highlights=highlights,
                summary=summary,
                text_max_characters=text_max_characters,
                highlights_per_url=highlights_per_url,
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Exa search failed: {str(e)}",
                "results": [],
            }

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
    """
    Starts the initialized MCP server.

    :param port: Port for SSE.
    :param transport: The transport type, e.g., `stdio` or `sse`.
    """
    print(f"Starting the MCP server on port {port} with transport {transport}")
    assert transport.lower() in ["stdio", "sse"], \
        "Transport should be `stdio` or `sse`"
    logger = get_logger("Service:exa_search")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())
