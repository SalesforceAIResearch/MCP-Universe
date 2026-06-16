"""Quick Notion configuration smoke test. Loads .env via dotenv; does not print secrets."""

import argparse
import asyncio
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_VERSION = "2022-06-28"


def _fail(message: str, code: int = 1) -> None:
    print(f"FAIL: {message}", flush=True)
    sys.exit(code)


def _page_id_from_root_page(value: str) -> str:
    """Turn NOTION_ROOT_PAGE (slug or UUID) into a Notion page UUID."""
    value = value.strip()
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    if uuid_pattern.match(value):
        return value

    hex_chars = re.sub(r"[^0-9a-f]", "", value.lower())
    if len(hex_chars) < 32:
        return value
    page_hex = hex_chars[-32:]
    return (
        f"{page_hex[:8]}-{page_hex[8:12]}-{page_hex[12:16]}"
        f"-{page_hex[16:20]}-{page_hex[20:]}"
    )


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(part.get("plain_text", "") for part in title_parts)
    # Fallback for workspace pages without title property shape we expect
    return page.get("url", page.get("id", "unknown"))


def check_env() -> tuple[str, str]:
    import os

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    root_page = os.getenv("NOTION_ROOT_PAGE", "").strip()

    if not api_key:
        _fail("NOTION_API_KEY is not set")
    if not root_page:
        _fail("NOTION_ROOT_PAGE is not set")

    print("Env OK (NOTION_API_KEY and NOTION_ROOT_PAGE present)", flush=True)
    print("Root page value:", root_page, flush=True)
    return api_key, root_page


def check_api(api_key: str, root_page: str) -> None:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
    }

    print("Calling Notion API (users/me)...", flush=True)
    me_response = requests.get(
        "https://api.notion.com/v1/users/me",
        headers=headers,
        timeout=30,
    )
    if me_response.status_code == 401:
        _fail("Invalid NOTION_API_KEY (401 unauthorized)")
    if me_response.status_code != 200:
        _fail(f"users/me returned HTTP {me_response.status_code}: {me_response.text[:200]}")

    bot = me_response.json()
    bot_name = bot.get("name") or bot.get("id", "integration")
    print(f"Integration OK: {bot_name}", flush=True)

    page_id = _page_id_from_root_page(root_page)
    print(f"Resolving parent page (id={page_id})...", flush=True)
    page_response = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=headers,
        timeout=30,
    )
    if page_response.status_code == 404:
        _fail(
            "Parent page not found. Check NOTION_ROOT_PAGE and share the page "
            "with your integration (Full access)."
        )
    if page_response.status_code == 403:
        _fail(
            "Permission denied on parent page. Connect your integration to the "
            "page via Notion Connections (Full access)."
        )
    if page_response.status_code != 200:
        _fail(
            f"pages.retrieve returned HTTP {page_response.status_code}: "
            f"{page_response.text[:200]}"
        )

    page = page_response.json()
    if page.get("in_trash"):
        _fail("Parent page is in trash — pick a different NOTION_ROOT_PAGE")

    title = _page_title(page)
    print(f"Parent page accessible: {title!r}", flush=True)


async def check_mcp(api_key: str) -> None:
    import os

    os.environ.setdefault("NOTION_API_KEY", api_key)
    from mcpuniverse.mcp.manager import MCPManager

    print("Starting Notion MCP server (requires Node.js/npx)...", flush=True)
    manager = MCPManager()
    client = await manager.build_client(server_name="notion")
    try:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools] if tools else []
        if not tool_names:
            _fail("Notion MCP server returned no tools")
        print(f"MCP OK ({len(tool_names)} tools available)", flush=True)
        result = await client.execute_tool("API-get-users", arguments={})
        if result is None:
            _fail("API-get-users returned no result")
        print("MCP API-get-users OK", flush=True)
    finally:
        await client.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test Notion benchmark configuration")
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Also start the Notion MCP server via npx (needs Node.js)",
    )
    args = parser.parse_args()

    api_key, root_page = check_env()
    check_api(api_key, root_page)

    if args.mcp:
        asyncio.run(check_mcp(api_key))

    print("SUCCESS - Notion looks configured for MCP-Universe benchmarks", flush=True)


if __name__ == "__main__":
    main()
