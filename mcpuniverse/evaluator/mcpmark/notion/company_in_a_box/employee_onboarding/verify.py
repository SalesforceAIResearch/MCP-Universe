import sys
from typing import Dict, Set
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def _check_db_schema(db_props: Dict[str, Dict], required: Dict[str, str]) -> bool:
    """Return True if every required property exists with the correct type."""
    for prop_name, expected_type in required.items():
        if prop_name not in db_props:
            print(
                f"Error: Property '{prop_name}' missing from database.", file=sys.stderr
            )
            return False
        actual_type = db_props[prop_name]["type"]
        if actual_type != expected_type:
            print(
                f"Error: Property '{prop_name}' has type '{actual_type}', expected '{expected_type}'.",
                file=sys.stderr,
            )
            return False
    return True


def verify(notion: Client, main_id: str | None = None) -> tuple[bool, str]:  # noqa: C901
    """Programmatically verify the onboarding system described in description.md."""

    DB_TITLE = "Employee Onboarding Checklist"
    HUB_PAGE_TITLE = "Onboarding Hub"
    DEPARTMENT_OPTIONS: Set[str] = {
        "Product",
        "Marketing",
        "Sales",
        "HR",
        "Engineering",
    }
    REQUIRED_DB_PROPERTIES = {
        "Employee Name": "title",
        "Start Date": "date",
        "Department": "select",
    }

    # 1. Locate onboarding database
    db_id = notion_utils.find_database(notion, DB_TITLE)
    if not db_id:
        print(f"Error: Database '{DB_TITLE}' not found.", file=sys.stderr)
        return False, f"Database '{DB_TITLE}' not found"

    try:
        db_obj = notion.databases.retrieve(database_id=db_id)
    except Exception as exc:
        print(f"Error retrieving database: {exc}", file=sys.stderr)
        return False, f"Error retrieving database: {exc}"

    db_props = db_obj.get("properties", {})
    if not _check_db_schema(db_props, REQUIRED_DB_PROPERTIES):
        return False, "Database schema validation failed"

    # Extra: validate select options
    dept_options = {opt["name"] for opt in db_props["Department"]["select"]["options"]}
    if not DEPARTMENT_OPTIONS.issubset(dept_options):
        print(
            f"Error: Department select options must include {sorted(DEPARTMENT_OPTIONS)}. Current: {sorted(dept_options)}",
            file=sys.stderr,
        )
        return False, f"Department select options must include {sorted(DEPARTMENT_OPTIONS)}. Current: {sorted(dept_options)}"

    # Check there are at least 3 entries in the database
    try:
        db_pages = notion.databases.query(database_id=db_id).get("results", [])
    except Exception as exc:
        print(f"Error querying database: {exc}", file=sys.stderr)
        return False, f"Error querying database: {exc}"
    if len(db_pages) < 3:
        print(
            "Error: Less than 3 onboarding entries found in the database.",
            file=sys.stderr,
        )
        return False, "Less than 3 onboarding entries found in the database"

    # 2. Locate Onboarding Hub page
    hub_page_id = notion_utils.find_page(notion, HUB_PAGE_TITLE)
    if not hub_page_id:
        print(f"Error: Page '{HUB_PAGE_TITLE}' not found.", file=sys.stderr)
        return False, f"Page '{HUB_PAGE_TITLE}' not found"

    # 3. Ensure the onboarding database is embedded in the hub page
    embedded_db_id = notion_utils.find_database_in_block(notion, hub_page_id, DB_TITLE)
    if embedded_db_id != db_id:
        print(
            "Error: The Employee Onboarding Checklist database is not embedded in the Onboarding Hub page.",
            file=sys.stderr,
        )
        return False, "The Employee Onboarding Checklist database is not embedded in the Onboarding Hub page"

    # 4. Analyse blocks within the hub page for linked mentions, timeline, and feedback form
    all_blocks = notion_utils.get_all_blocks_recursively(notion, hub_page_id)

    seen_link_targets: Set[str] = set()
    numbered_list_count = 0
    todo_count = 0

    for blk in all_blocks:
        blk_type = blk.get("type")

        # Direct link-to-page blocks
        if blk_type == "link_to_page":
            info = blk.get("link_to_page", {})
            target_id = info.get("page_id") or info.get("database_id")
            if target_id:
                seen_link_targets.add(target_id)
            continue

        # Rich-text mentions inside content blocks
        if blk_type in {
            "paragraph",
            "numbered_list_item",
            "bulleted_list_item",
            "to_do",
        }:
            content = blk.get(blk_type, {})
            for rt in content.get("rich_text", []):
                if rt.get("type") == "mention":
                    mention = rt.get("mention", {})
                    if mention.get("type") in {"page", "database"}:
                        target_id = mention.get("page", {}).get("id") or mention.get(
                            "database", {}
                        ).get("id")
                        if target_id:
                            seen_link_targets.add(target_id)

        # Count numbered list items
        if blk_type == "numbered_list_item":
            numbered_list_count += 1

        # Count to-do items in Feedback Form
        if blk_type == "to_do":
            todo_count += 1

    if len(seen_link_targets) < 3:
        print(
            "Error: Fewer than 3 linked mentions to benefit policy pages found in the Benefits Overview section.",
            file=sys.stderr,
        )
        return False, "Fewer than 3 linked mentions to benefit policy pages found in the Benefits Overview section"

    if numbered_list_count < 7:
        print(
            "Error: Numbered list contains fewer than 7 steps in the 30-Day Timeline section.",
            file=sys.stderr,
        )
        return False, "Numbered list contains fewer than 7 steps in the 30-Day Timeline section"

    if todo_count < 3:
        print(
            "Error: Feedback Form section contains fewer than 3 to-do items.",
            file=sys.stderr,
        )
        return False, "Feedback Form section contains fewer than 3 to-do items"

    print(
        "Success: Verified Employee Onboarding Checklist database, Onboarding Hub page, and all required sections."
    )
    return True, ""


def main():
    """Main verification function."""
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None
    success, error_msg = verify(notion, main_id)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
