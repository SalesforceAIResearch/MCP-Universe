"""Verification module for Asset Retirement Migration task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
import re
from typing import Dict, Set, Optional
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def _get_database(root_page_id: str, notion: Client, name: str) -> Optional[str]:
    """Helper that finds a child database by title inside a page."""
    return notion_utils.find_database_in_block(notion, root_page_id, name)


def _check_property(props: Dict, name: str, expected_type: str) -> bool:
    if name not in props:
        print(f"Error: Property '{name}' missing in database.", file=sys.stderr)
        return False
    if props[name]["type"] != expected_type:
        found_type = props[name]['type']
        msg = (f"Error: Property '{name}' expected type '{expected_type}', "
               f"found '{found_type}'.")
        print(msg, file=sys.stderr)
        return False
    return True


def verify(notion: Client, main_id: Optional[str] = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """Verifies that the IT Asset Retirement Queue was created and populated correctly."""

    # -------------------------------------------------------------------------
    # Resolve the root IT Trouble Shooting Hub page
    # -------------------------------------------------------------------------
    root_page_id = None
    if main_id:
        found_id, obj_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if found_id and obj_type == "page":
            root_page_id = found_id

    if not root_page_id:
        root_page_id = notion_utils.find_page(notion, "IT Trouble Shooting Hub")
    if not root_page_id:
        print(
            "Error: Could not locate the 'IT Trouble Shooting Hub' page.",
            file=sys.stderr,
        )
        return False, "Could not locate the 'IT Trouble Shooting Hub' page"

    # -------------------------------------------------------------------------
    # Locate the original and new databases
    # -------------------------------------------------------------------------
    inventory_db_id = _get_database(root_page_id, notion, "IT Inventory")
    if not inventory_db_id:
        print("Error: 'IT Inventory' database not found.", file=sys.stderr)
        return False, "'IT Inventory' database not found"

    retirement_db_id = _get_database(root_page_id, notion, "IT Asset Retirement Queue")
    if not retirement_db_id:
        print("Error: 'IT Asset Retirement Queue' database not found.", file=sys.stderr)
        return False, "'IT Asset Retirement Queue' database not found"

    # -------------------------------------------------------------------------
    # Validate schema of the retirement queue database
    # -------------------------------------------------------------------------
    retirement_db = notion.databases.retrieve(database_id=retirement_db_id)
    r_props = retirement_db["properties"]

    required_schema = {
        "Serial": "title",
        "Tags": "multi_select",
        "Status": "select",
        "Vendor": "select",
        "Expiration date": "date",
        "Retirement Reason": "select",
    }

    for pname, ptype in required_schema.items():
        if not _check_property(r_props, pname, ptype):
            return False, f"Property '{pname}' validation failed"

    # Check Retirement Reason options
    expected_reason_options: Set[str] = {
        "Expired License",
        "Hardware Obsolete",
        "Security Risk",
        "User Offboarding",
    }
    actual_options = {
        opt["name"] for opt in r_props["Retirement Reason"]["select"]["options"]
    }
    if actual_options != expected_reason_options:
        print(
            "Error: 'Retirement Reason' select options mismatch.\n"
            f"Expected: {sorted(expected_reason_options)}\n"
            f"Found: {sorted(actual_options)}",
            file=sys.stderr,
        )
        expected_sorted = sorted(expected_reason_options)
        actual_sorted = sorted(actual_options)
        msg = (f"'Retirement Reason' select options mismatch. "
               f"Expected: {expected_sorted}, Found: {actual_sorted}")
        return False, msg

    # ---------------------------------------------------------------
    # Validate database description starts with required phrase
    # ---------------------------------------------------------------
    desc_rich = retirement_db.get("description", [])
    desc_text = "".join([t.get("plain_text", "") for t in desc_rich])
    required_desc = "AUTO-GENERATED MIGRATION COMPLETED"
    if desc_text.strip() != required_desc:
        print(
            f"Error: Retirement database description must be exactly '{required_desc}'.",
            file=sys.stderr,
        )
        return False, f"Retirement database description must be exactly '{required_desc}'"

    # -------------------------------------------------------------------------
    # Validate that inventory items are moved & archived
    # -------------------------------------------------------------------------
    expired_filter = {
        "property": "Status",
        "select": {"equals": "Expired"},
    }
    to_return_filter = {
        "property": "Status",
        "select": {"equals": "To be returned"},
    }
    compound_filter = {"or": [expired_filter, to_return_filter]}

    # Query for any *active* items that still match these statuses
    remaining_items = notion.databases.query(
        database_id=inventory_db_id,
        filter=compound_filter,
        archived=False,
    ).get("results", [])

    if remaining_items:
        items_count = len(remaining_items)
        msg = (f"Error: {items_count} 'Expired' / 'To be returned' items "
               "still present in IT Inventory.")
        print(msg, file=sys.stderr)
        return False, msg

    # There should be at least one entry in the retirement queue
    retirement_pages = notion.databases.query(database_id=retirement_db_id).get(
        "results", []
    )
    expected_serials = {"65XYQ/GB", "36x10PIQ"}
    if len(retirement_pages) != len(expected_serials):
        expected_count = len(expected_serials)
        found_count = len(retirement_pages)
        msg = (f"Error: Expected {expected_count} retirement pages, "
               f"found {found_count}.")
        print(msg, file=sys.stderr)
        return False, msg

    # Each retirement page must have a Retirement Reason
    serials_seen = set()
    for page in retirement_pages:
        props = page["properties"]
        reason = props.get("Retirement Reason", {}).get("select", {})
        if not reason or reason.get("name") not in expected_reason_options:
            print(
                f"Error: Page {page['id']} missing valid 'Retirement Reason'.",
                file=sys.stderr,
            )
            return False, f"Page {page['id']} missing valid 'Retirement Reason'"

        # Collect Serial title
        title_rich = props.get("Serial", {}).get("title", [])
        serial_val = "".join([t.get("plain_text", "") for t in title_rich]).strip()
        serials_seen.add(serial_val)

    if serials_seen != expected_serials:
        expected_sorted = sorted(expected_serials)
        seen_sorted = sorted(serials_seen)
        msg = (f"Error: Serial values mismatch. Expected {expected_sorted}, "
               f"found {seen_sorted}.")
        print(msg, file=sys.stderr)
        return False, msg

    # -----------------------------------------------------------------
    # Verify the migration log page and callout block contents
    # -----------------------------------------------------------------
    log_page_title = "Retirement Migration Log"
    log_page_id = notion_utils.find_page(notion, log_page_title)
    if not log_page_id:
        print(f"Error: Page '{log_page_title}' not found.", file=sys.stderr)
        return False, f"Page '{log_page_title}' not found"

    # Search for a callout block with required pattern
    callout_pattern = re.compile(
        r"Successfully migrated (\d+) assets to the retirement queue "
        r"on 2025-03-24\."
    )
    blocks = notion_utils.get_all_blocks_recursively(notion, log_page_id)
    match_found = False
    for blk in blocks:
        if blk.get("type") == "callout":
            text = notion_utils.get_block_plain_text(blk)
            m = callout_pattern.search(text)
            if m:
                migrated_num = int(m.group(1))
                if migrated_num == len(expected_serials):
                    match_found = True
                else:
                    pages_count = len(retirement_pages)
                    msg = (f"Error: Callout reports {migrated_num} assets, "
                           f"but {pages_count} retirement pages found.")
                    print(msg, file=sys.stderr)
                    return False, msg
                break
    if not match_found:
        print(
            "Error: Required callout block not found in migration log page.",
            file=sys.stderr,
        )
        return False, "Required callout block not found in migration log page"

    print("Success: All verification criteria satisfied.")
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
