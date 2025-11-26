"""Verification module for Faq Column Layout task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the FAQ toggle has been properly reorganized with a column list.
    """
    # Start from main_id if provided
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        # Try to find the Self Assessment page
        page_id = notion_utils.find_page(notion, "Self Assessment")

    if not page_id:
        print("Error: Self Assessment page not found.", file=sys.stderr)
        return False, "Error: Self Assessment page not found."

    # Get all blocks recursively from the page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    # Find the FAQ toggle block
    faq_toggle_block = None
    faq_toggle_id = None
    for block in all_blocks:
        if block.get("type") == "toggle":
            block_text = notion_utils.get_block_plain_text(block)
            if "FAQ" in block_text:
                faq_toggle_block = block
                faq_toggle_id = block.get("id")
                print(f"Found FAQ toggle block: {block_text}")
                break

    if not faq_toggle_block:
        print("Error: FAQ toggle block not found.", file=sys.stderr)
        return False, "Error: FAQ toggle block not found."

    # Find column_list inside the FAQ toggle
    column_list_block = None
    for block in all_blocks:
        if (
            block.get("type") == "column_list"
            and block.get("parent", {}).get("block_id") == faq_toggle_id
        ):
            column_list_block = block
            break

    if not column_list_block:
        print("Error: No column_list found inside FAQ toggle.", file=sys.stderr)
        return False, "Error: No column_list found inside FAQ toggle."

    # Check that there are no Q&A pairs directly under FAQ toggle (outside column_list)
    direct_faq_children = []
    for block in all_blocks:
        if block.get("parent", {}).get("block_id") == faq_toggle_id and block.get(
            "id"
        ) != column_list_block.get("id"):
            direct_faq_children.append(block)

    # Check if any of these are heading_3 or paragraph blocks (Q&A content)
    for block in direct_faq_children:
        if block.get("type") in ["heading_3", "paragraph"]:
            block_text = notion_utils.get_block_plain_text(block)[:50]
            msg = (f"Error: Found Q&A content outside column_list: "
                   f"{block_text}...")
            print(msg, file=sys.stderr)
            return False, msg

    # Find the two columns
    columns = []
    column_list_id = column_list_block.get("id")
    for block in all_blocks:
        if (
            block.get("type") == "column"
            and block.get("parent", {}).get("block_id") == column_list_id
        ):
            columns.append(block)

    if len(columns) != 2:
        print(f"Error: Expected 2 columns, found {len(columns)}.", file=sys.stderr)
        return False, f"Error: Expected 2 columns, found {len(columns)}."

    # Check each column has exactly 2 Q&A pairs
    for i, column in enumerate(columns):
        column_id = column.get("id")

        # Find blocks inside this column
        column_blocks = []
        for block in all_blocks:
            if block.get("parent", {}).get("block_id") == column_id:
                column_blocks.append(block)

        # Count Q&A pairs (should be heading_3 followed by paragraph)
        qa_pairs = 0
        j = 0
        while j < len(column_blocks):
            if (
                column_blocks[j].get("type") == "heading_3"
                and j + 1 < len(column_blocks)
                and column_blocks[j + 1].get("type") == "paragraph"
            ):
                qa_pairs += 1
                j += 2  # Skip both question and answer
            else:
                j += 1

        if qa_pairs != 2:
            print(
                f"Error: Column {i + 1} has {qa_pairs} Q&A pairs, expected 2.",
                file=sys.stderr,
            )
            return False, f"Error: Column {i + 1} has {qa_pairs} Q&A pairs, expected 2."

        print(f"Column {i + 1}: Found {qa_pairs} Q&A pairs ✓")

    print(
        "Success: FAQ toggle properly organized with 2 columns, each containing 2 Q&A pairs."
    )
    return True, ""


def main():
    """
    Executes the verification process and exits with a status code.
    """
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None
    success, _error_msg = verify(notion, main_id)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
