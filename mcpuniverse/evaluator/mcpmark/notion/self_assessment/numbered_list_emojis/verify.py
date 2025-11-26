"""Verification module for Numbered List Emojis task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:
    """
    Verifies that numbered lists have been replaced with emoji numbers.
    """
    # Start from main_id if provided, otherwise search for the page
    self_assessment_page_id = main_id
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            self_assessment_page_id = found_id

    if not self_assessment_page_id:
        # Try to find by name
        self_assessment_page_id = notion_utils.find_page(notion, "Self Assessment")

    if not self_assessment_page_id:
        print("Error: Self Assessment page not found.", file=sys.stderr)
        return False, "Error: Self Assessment page not found."

    # Get all blocks recursively from the main page
    all_blocks = notion_utils.get_all_blocks_recursively(
        notion, self_assessment_page_id
    )

    # Find all numbered_list_item blocks
    numbered_list_items = []
    for block in all_blocks:
        if block.get("type") == "numbered_list_item":
            numbered_list_items.append(block)

    if len(numbered_list_items) > 0:
        items_count = len(numbered_list_items)
        msg = (f"Error: found {items_count} numbered list items that should "
               "be converted to emoji numbers")
        print(msg, file=sys.stderr)
        # return False, msg

    required_items = [
        "1️⃣ Record Each Hyperfocus Session:",
        "2️⃣ Review and Reflect:",
        "3️⃣ Adjust and Optimize:",
        '1️⃣ Harvard Business Review: "The Making of a Corporate Athlete"',
        ('2️⃣ "Hyperfocus: How to Be More Productive in a World of '
         'Distraction" by Chris Bailey'),
        ('3️⃣ "Attention Management: How to Create Success and Gain '
         'Productivity Every Day" by Maura Thomas'),
        ('4️⃣ "Deep Work: Rules for Focused Success in a Distracted World" '
         'by Cal Newport'),
        "1️⃣ Record Each Hyperfocus Session:",
        "2️⃣ Review and Reflect:",
        "3️⃣ Adjust and Optimize:",
        "1️⃣ What time of day do you feel most focused?",
        "2️⃣ Which environment helps you concentrate the most?",
        "3️⃣ What type of tasks do you find yourself getting lost in?",
    ]

    # Make a copy to track which items we've found
    remaining_items = required_items.copy()

    # Iterate through all blocks to find matching text
    for block in all_blocks:
        block_text = notion_utils.get_block_plain_text(block).strip()

        # Check if this block's text matches any of our required items
        if block_text in remaining_items:
            remaining_items.remove(block_text)
            print(f"Found: {block_text}")

    # Check if all required items were found
    if len(remaining_items) == 0:
        print("Success: All numbered lists have been converted to emoji numbers")
        return True, ""
    print(f"Error: Missing {len(remaining_items)} required items:", file=sys.stderr)
    for item in remaining_items:
        print(f"  - {item}", file=sys.stderr)
    return False, f"Error: Missing {len(remaining_items)} required items"


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
