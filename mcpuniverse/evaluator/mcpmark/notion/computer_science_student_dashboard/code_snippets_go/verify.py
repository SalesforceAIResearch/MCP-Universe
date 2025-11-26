"""Verification module for Code Snippets Go task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from typing import Optional
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

# Expected code blocks (language=go)
EXPECTED_CODE_BLOCKS = [
    {
        "caption": "Basic Go program",
        "code": (
            'package main\n\nimport "fmt"\n\nfunc main() {\n    fmt.Println("Hello, World!")\n}'
        ),
    },
    {
        "caption": "For loop in Go",
        "code": ("for i := 0; i < 5; i++ {\n    fmt.Println(i)\n}"),
    },
    {
        "caption": "Function definition in Go",
        "code": ("func add(a, b int) int {\n    return a + b\n}"),
    },
]

HEADER_TEXT = "Go"


def _normalize(text: str) -> str:
    """Remove trailing spaces on each line and strip leading/trailing blank lines."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _find_page(notion: Client, main_id: Optional[str]) -> Optional[str]:
    """Return a page_id to verify against or None if not found."""
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id
    if not page_id:
        page_id = notion_utils.find_page(notion, "Computer Science Student Dashboard")
    return page_id


def _has_bold_header_text(block, text: str) -> bool:
    """Generic bold header/paragraph check for a given text."""
    block_type = block.get("type")
    if block_type not in {"paragraph", "heading_1", "heading_2", "heading_3"}:
        return False
    rich_text_list = block.get(block_type, {}).get("rich_text", [])
    if not rich_text_list:
        return False
    plain = "".join(rt.get("plain_text", "") for rt in rich_text_list).strip()
    if plain != text:
        return False
    return any(rt.get("annotations", {}).get("bold", False) for rt in rich_text_list)


def _go_column_order_correct(notion: Client, page_id: str) -> bool:
    """Return True if there exists a column list where Python → Go → JavaScript order holds."""
    # Gather all blocks once (flat list) to locate column_list blocks
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)
    column_list_ids = [
        blk["id"] for blk in all_blocks if blk.get("type") == "column_list"
    ]

    for cl_id in column_list_ids:
        # Retrieve columns in explicit order
        columns = notion.blocks.children.list(block_id=cl_id).get("results", [])
        header_to_idx: dict[str, int] = {}
        for idx, col in enumerate(columns):
            # Recursively inspect blocks within this column
            col_blocks = notion_utils.get_all_blocks_recursively(notion, col["id"])
            for blk in col_blocks:
                if _has_bold_header_text(blk, "Python"):
                    header_to_idx.setdefault("Python", idx)
                elif _has_bold_header_text(blk, "Go"):
                    header_to_idx.setdefault("Go", idx)
                elif _has_bold_header_text(blk, "JavaScript"):
                    header_to_idx.setdefault("JavaScript", idx)
            # Short-circuit if all three found within current traversal
            if len(header_to_idx) == 3:
                break

        if (
            "Python" in header_to_idx
            and "Go" in header_to_idx
            and "JavaScript" in header_to_idx
            and header_to_idx["Python"]
            < header_to_idx["Go"]
            < header_to_idx["JavaScript"]
        ):
            return True
    return False


def _collect_code_blocks(blocks):
    """Return list of (code_content, caption) tuples for code blocks with language 'go'."""
    collected = []
    for block in blocks:
        if block.get("type") != "code":
            continue
        code_data = block.get("code", {})
        if code_data.get("language") != "go":
            continue
        code_plain = "".join(
            rt.get("plain_text", "") for rt in code_data.get("rich_text", [])
        )
        caption_plain = "".join(
            rt.get("plain_text", "") for rt in code_data.get("caption", [])
        )
        collected.append((code_plain, caption_plain))
    return collected


def verify(notion: Client, main_id: Optional[str] = None) -> tuple[bool, str]:
    """Verify that code snippets with Go language are correctly added."""
    page_id = _find_page(notion, main_id)
    if not page_id:
        print("Error: Target page not found.", file=sys.stderr)
        return False, "Target page not found"

    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    # Verify header
    header_ok = any(_has_bold_header_text(b, HEADER_TEXT) for b in all_blocks)
    if not header_ok:
        print("Failure: Bold header 'Go' not found.", file=sys.stderr)
        return False, "Bold header 'Go' not found"

    # Verify code blocks
    code_blocks_found = _collect_code_blocks(all_blocks)

    remaining = EXPECTED_CODE_BLOCKS.copy()
    for code, caption in code_blocks_found:
        norm_code = _normalize(code)
        for expected in list(remaining):  # Iterate through a copy
            if (
                _normalize(expected["code"]) == norm_code
                and expected["caption"] == caption
            ):
                remaining.remove(expected)
                break
    if remaining:
        missing = ", ".join(exp["caption"] for exp in remaining)
        print(
            f"Failure: Missing or incorrect Go code blocks: {missing}", file=sys.stderr
        )
        return False, f"Missing or incorrect Go code blocks: {missing}"

    # Verify column order Python → Go → JavaScript
    if not _go_column_order_correct(notion, page_id):
        print(
            "Failure: Go column is not positioned between Python and JavaScript.",
            file=sys.stderr,
        )
        return False, "Go column is not positioned between Python and JavaScript"

    print(
        "Success: Verified Go column with required code blocks and correct positioning."
    )
    return True, ""


def main():
    """Main verification function."""
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None
    success, _error_msg = verify(notion, main_id)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
