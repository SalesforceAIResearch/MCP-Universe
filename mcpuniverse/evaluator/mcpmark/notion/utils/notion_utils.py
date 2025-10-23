import os
from notion_client import Client
import sys
from dotenv import load_dotenv


def get_notion_client():
    # Construct the absolute path to the .env file in the project root
    load_dotenv(dotenv_path=".mcp_env")
    api_key = os.getenv("EVAL_NOTION_API_KEY")
    if not api_key:
        print(
            "Error: EVAL_NOTION_API_KEY not found in environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)
    return Client(auth=api_key)


def _find_object(notion: Client, title: str, object_type: str):
    """Generic helper to find a Notion page or database by title.

    Args:
        notion: Authenticated Notion Client.
        title: Title (or partial title) to search for.
        object_type: Either "page" or "database".

    Returns:
        The ID string if found, otherwise None.
    """
    search_results = (
        notion.search(
            query=title, filter={"property": "object", "value": object_type}
        ).get("results")
        or []
    )

    if not search_results:
        return None

    # Shortcut when there is only one match
    if len(search_results) == 1:
        return search_results[0]["id"]

    # Attempt to find a case-insensitive match on the title field
    for result in search_results:
        if object_type == "page":
            # Pages store their title inside the "properties.title.title" rich text list
            title_rich_texts = (
                result.get("properties", {}).get("title", {}).get("title", [])
            )
        else:  # database
            title_rich_texts = result.get("title", [])

        for text_obj in title_rich_texts:
            if title.lower() in text_obj.get("plain_text", "").lower():
                return result["id"]

    # Fallback: return the first result
    return search_results[0]["id"]


def find_page(notion: Client, page_title: str):
    """Finds a page by title. Wrapper around _find_object with object_type='page'."""
    return _find_object(notion, page_title, "page")


def get_page_by_id(notion: Client, page_id: str):
    """Gets a page by its ID. Returns the page object if found, None otherwise."""
    try:
        return notion.pages.retrieve(page_id=page_id)
    except Exception:
        return None


def find_page_by_id(notion: Client, page_id: str):
    """Finds a page by its ID and returns the ID if it exists, None otherwise."""
    try:
        notion.pages.retrieve(page_id=page_id)
        return page_id
    except Exception:
        return None


def find_database_by_id(notion: Client, database_id: str):
    """Finds a database by its ID and returns the ID if it exists, None otherwise."""
    try:
        notion.databases.retrieve(database_id=database_id)
        return database_id
    except Exception:
        return None


def find_page_or_database_by_id(notion: Client, object_id: str):
    """
    Finds either a page or database by ID. Returns a tuple (object_id, object_type)
    where object_type is either 'page' or 'database', or (None, None) if not found.
    """
    # Try as page first
    try:
        notion.pages.retrieve(page_id=object_id)
        return (object_id, "page")
    except Exception:
        pass

    # Try as database
    try:
        notion.databases.retrieve(database_id=object_id)
        return (object_id, "database")
    except Exception:
        pass

    return (None, None)


def find_database(notion: Client, db_title: str):
    """Finds a database by title. Wrapper around _find_object with object_type='database'."""
    return _find_object(notion, db_title, "database")


def find_database_in_block(notion: Client, block_id: str, db_title: str):
    """
    Recursively find a database by title within a block.
    """
    blocks = notion.blocks.children.list(block_id=block_id).get("results")
    for block in blocks:
        if (
            block.get("type") == "child_database"
            and block.get("child_database", {}).get("title") == db_title
        ):
            return block["id"]
        if block.get("has_children"):
            db_id = find_database_in_block(notion, block["id"], db_title)
            if db_id:
                return db_id
    return None


def get_all_blocks_recursively(notion: Client, block_id: str):
    """
    Recursively fetches all blocks from a starting block ID and its children,
    returning a single flat list of block objects.
    """
    all_blocks = []
    try:
        direct_children = notion.blocks.children.list(block_id=block_id).get(
            "results", []
        )
    except Exception:
        return []

    for block in direct_children:
        all_blocks.append(block)
        if block.get("has_children"):
            all_blocks.extend(get_all_blocks_recursively(notion, block["id"]))

    return all_blocks


def get_block_plain_text(block):
    """
    Safely extract plain_text from a block (paragraph, heading, etc.).
    """
    block_type = block.get("type")
    if not block_type:
        return ""

    block_content = block.get(block_type)
    if not block_content:
        return ""

    rich_text_list = block_content.get("rich_text", [])
    plain_text = "".join([rt.get("plain_text", "") for rt in rich_text_list])

    return plain_text
