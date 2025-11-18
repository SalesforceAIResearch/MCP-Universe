"""Verification module for Change Color task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def get_page_title(page_result):
    """Extract title from a page result"""
    properties = page_result.get('properties', {})
    for prop_name in ['Name', 'Title', 'title']:
        if prop_name in properties:
            prop = properties[prop_name]
            if prop.get('type') == 'title':
                title_array = prop.get('title', [])
                if title_array and len(title_array) > 0:
                    return title_array[0].get('plain_text', '')
    return ''

def get_page_tags(page_result):
    """Extract tags from a page result"""
    properties = page_result.get('properties', {})
    tags_property = properties.get('Tags', {})
    if tags_property.get('type') == 'multi_select':
        tags = tags_property.get('multi_select', [])
        return [tag.get('name') for tag in tags]
    return []

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that all pink colors have been changed in the Toronto Guide page.

    Expected pink elements that should be changed:
    1. Callout: "Welcome to Toronto!" with red_background (originally should be pink)
    2. Activities database tags:
       - "Parks" tag (High Park, Evergreen Brickworks)
       - "Neighbourhood" tag (Ossington Strip, Chinatown, Little Italy,
         Kensington Market, Queen west, The beaches)
    3. Food database tags:
       - "Middle Eastern" (Byblos Downtown)
       - "Jamaican" (Crumbs Patties)
       - "Indian" (Leela Indian Food Bar)
    4. Cafes database tag:
       - "Food" (Cafe Landwer)

    These elements should exist with the same name/content but different colors.
    Tag distributions should remain the same.
    """
    # Step 1: Find the main Toronto Guide page
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if not found_id or object_type != 'page':
            print("Error: Toronto Guide page not found.", file=sys.stderr)
            return False
    else:
        # Try to find the page by searching
        found_id = notion_utils.find_page(notion, "Toronto Guide")
        if not found_id:
            print("Error: Toronto Guide page not found.", file=sys.stderr)
            return False

    print(f"Found Toronto Guide page: {found_id}")

    # Get all blocks from the page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, found_id)
    print(f"Found {len(all_blocks)} blocks")

    # Expected elements and their distributions
    expected_pink_elements = {
        "callout": {
            "text": "Welcome to Toronto!",
            "found": False,
            "has_pink": False,
            "exists": False
        },
        "activities_tags": {
            "Parks": {
                "found": False,
                "has_pink": False,
                "expected_items": ["High Park", "Evergreen Brickworks"],
                "actual_items": []
            },
            "Neighbourhood": {
                "found": False,
                "has_pink": False,
                "expected_items": [
                    "Ossington Strip",
                    "Chinatown",
                    "Little Italy",
                    "Kensington Market",
                    "Queen west",
                    "The beaches"
                ],
                "actual_items": []
            }
        },
        "food_tags": {
            "Middle Eastern": {
                "found": False,
                "has_pink": False,
                "expected_items": ["Byblos Downtown"],
                "actual_items": []
            },
            "Jamaican": {
                "found": False,
                "has_pink": False,
                "expected_items": ["Crumbs Patties"],
                "actual_items": []
            },
            "Indian": {
                "found": False,
                "has_pink": False,
                "expected_items": ["Leela Indian Food Bar"],
                "actual_items": []
            }
        },
        "cafes_tags": {
            "Food": {
                "found": False,
                "has_pink": False,
                "expected_items": ["Cafe Landwer"],
                "actual_items": []
            }
        }
    }

    # Database IDs
    activities_db_id = None
    food_db_id = None
    cafes_db_id = None

    # Step 2: Check all blocks for callouts and find databases
    for block in all_blocks:
        if block is None:
            continue

        block_type = block.get("type")

        # Check for the specific callout block
        if block_type == "callout":
            callout_text = notion_utils.get_block_plain_text(block)
            if "Welcome to Toronto!" in callout_text:
                expected_pink_elements["callout"]["exists"] = True
                expected_pink_elements["callout"]["found"] = True
                color = block.get("callout", {}).get("color", "")
                if "pink" in color.lower():
                    expected_pink_elements["callout"]["has_pink"] = True
                    print(f"✗ Callout 'Welcome to Toronto!' still has pink color: {color}")
                else:
                    print(f"✓ Callout 'Welcome to Toronto!' has non-pink color: {color}")

        # Find child databases
        elif block_type == "child_database":
            title = block.get("child_database", {}).get("title", "")
            block_id = block.get("id")

            if "Activities" in title:
                activities_db_id = block_id
                print(f"Found Activities database: {block_id}")
            elif "Food" in title:
                food_db_id = block_id
                print(f"Found Food database: {block_id}")
            elif "Cafes" in title or "Café" in title:
                cafes_db_id = block_id
                print(f"Found Cafes database: {block_id}")

    # Step 3: Check Activities database for specific tags and their distributions
    if activities_db_id:  # pylint: disable=too-many-nested-blocks
        try:
            # Get database properties
            db_info = notion.databases.retrieve(database_id=activities_db_id)
            tags_property = db_info.get("properties", {}).get("Tags", {})
            if tags_property.get("type") == "multi_select":
                options = tags_property.get("multi_select", {}).get("options", [])
                for option in options:
                    tag_name = option.get("name").strip()
                    tag_color = option.get("color")

                    if tag_name in expected_pink_elements["activities_tags"]:
                        expected_pink_elements["activities_tags"][tag_name]["found"] = True
                        if tag_color == "pink":
                            expected_pink_elements["activities_tags"][tag_name]["has_pink"] = True
                            print(f"✗ Activities tag '{tag_name}' still has pink color")
                        else:
                            print(f"✓ Activities tag '{tag_name}' changed to {tag_color}")

            # Query database to check tag distributions
            query_result = notion.databases.query(database_id=activities_db_id)
            for page in query_result.get('results', []):
                page_title = get_page_title(page).strip()
                page_tags = get_page_tags(page)

                for tag_name in expected_pink_elements["activities_tags"]:
                    if tag_name in page_tags:
                        tag_info = expected_pink_elements["activities_tags"][tag_name]
                        tag_info["actual_items"].append(page_title)

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error checking Activities database: {e}", file=sys.stderr)
            return False, f"Error checking Activities database: {e}"
    else:
        print("Error: Activities database not found", file=sys.stderr)
        return False, "Error: Activities database not found"

    # Step 4: Check Food database for specific tags and their distributions
    if food_db_id:  # pylint: disable=too-many-nested-blocks
        try:
            # Get database properties
            db_info = notion.databases.retrieve(database_id=food_db_id)
            tags_property = db_info.get("properties", {}).get("Tags", {})
            if tags_property.get("type") == "multi_select":
                options = tags_property.get("multi_select", {}).get("options", [])
                for option in options:
                    tag_name = option.get("name").strip()
                    tag_color = option.get("color")

                    if tag_name in expected_pink_elements["food_tags"]:
                        expected_pink_elements["food_tags"][tag_name]["found"] = True
                        if tag_color == "pink":
                            expected_pink_elements["food_tags"][tag_name]["has_pink"] = True
                            print(f"✗ Food tag '{tag_name}' still has pink color")
                        else:
                            print(f"✓ Food tag '{tag_name}' changed to {tag_color}")

            # Query database to check tag distributions
            query_result = notion.databases.query(database_id=food_db_id)
            for page in query_result.get('results', []):
                page_title = get_page_title(page).strip()
                page_tags = get_page_tags(page)

                for tag_name in expected_pink_elements["food_tags"]:
                    if tag_name in page_tags:
                        tag_info = expected_pink_elements["food_tags"][tag_name]
                        tag_info["actual_items"].append(page_title)

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error checking Food database: {e}", file=sys.stderr)
            return False, f"Error checking Food database: {e}"
    else:
        print("Error: Food database not found", file=sys.stderr)
        return False, "Error: Food database not found"

    # Step 5: Check Cafes database for specific tags and their distributions
    if cafes_db_id:  # pylint: disable=too-many-nested-blocks
        try:
            # Get database properties
            db_info = notion.databases.retrieve(database_id=cafes_db_id)
            tags_property = db_info.get("properties", {}).get("Tags", {})
            if tags_property.get("type") == "multi_select":
                options = tags_property.get("multi_select", {}).get("options", [])
                for option in options:
                    tag_name = option.get("name").strip()
                    tag_color = option.get("color")

                    if tag_name in expected_pink_elements["cafes_tags"]:
                        expected_pink_elements["cafes_tags"][tag_name]["found"] = True
                        if tag_color == "pink":
                            expected_pink_elements["cafes_tags"][tag_name]["has_pink"] = True
                            print(f"✗ Cafes tag '{tag_name}' still has pink color")
                        else:
                            print(f"✓ Cafes tag '{tag_name}' changed to {tag_color}")

            # Query database to check tag distributions
            query_result = notion.databases.query(database_id=cafes_db_id)
            for page in query_result.get('results', []):
                page_title = get_page_title(page).strip()
                page_tags = get_page_tags(page)

                for tag_name in expected_pink_elements["cafes_tags"]:
                    if tag_name in page_tags:
                        tag_info = expected_pink_elements["cafes_tags"][tag_name]
                        tag_info["actual_items"].append(page_title)

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error checking Cafes database: {e}", file=sys.stderr)
            return False, f"Error checking Cafes database: {e}"
    else:
        print("Error: Cafes database not found", file=sys.stderr)
        return False, "Error: Cafes database not found"

    # Step 6: Verify all requirements
    print("\nVerification Summary:")

    all_passed = True

    # Check callout
    if not expected_pink_elements["callout"]["exists"]:
        print("✗ 'Welcome to Toronto!' callout not found", file=sys.stderr)
        all_passed = False
    elif expected_pink_elements["callout"]["has_pink"]:
        print("✗ Callout still has pink background", file=sys.stderr)
        all_passed = False
    else:
        print("✓ Callout color changed from pink")

    # Check Activities tags
    print("\nActivities Database Tags:")
    for tag_name, tag_info in expected_pink_elements["activities_tags"].items():
        if not tag_info["found"]:
            msg = (f"✗ Activities tag '{tag_name}' not found "
                   "(may have been renamed)")
            print(msg, file=sys.stderr)
            # Don't fail if tag was renamed, as that's acceptable
        elif tag_info["has_pink"]:
            print(f"✗ Activities tag '{tag_name}' still has pink color", file=sys.stderr)
            all_passed = False
        else:
            print(f"✓ Activities tag '{tag_name}' color changed from pink")

        # Check distribution
        expected_set = set(tag_info["expected_items"])
        actual_set = set(tag_info["actual_items"])
        if tag_info["found"] and expected_set != actual_set:
            print(f"  ✗ Tag distribution mismatch for '{tag_name}':", file=sys.stderr)
            print(f"    Expected: {sorted(expected_set)}", file=sys.stderr)
            print(f"    Actual: {sorted(actual_set)}", file=sys.stderr)
            # Note: We don't fail on distribution mismatch if tag was renamed
            if not expected_set - actual_set:  # If all expected items are present
                print("    (Additional items found, but all expected items are present)")
        elif tag_info["found"]:
            print(f"  ✓ Tag distribution maintained for '{tag_name}'")

    # Check Food tags
    print("\nFood Database Tags:")
    for tag_name, tag_info in expected_pink_elements["food_tags"].items():
        if not tag_info["found"]:
            print(f"✗ Food tag '{tag_name}' not found (may have been renamed)", file=sys.stderr)
            # Don't fail if tag was renamed, as that's acceptable
        elif tag_info["has_pink"]:
            print(f"✗ Food tag '{tag_name}' still has pink color", file=sys.stderr)
            all_passed = False
        else:
            print(f"✓ Food tag '{tag_name}' color changed from pink")

        # Check distribution
        expected_set = set(tag_info["expected_items"])
        actual_set = set(tag_info["actual_items"])
        if tag_info["found"] and expected_set != actual_set:
            print(f"  ✗ Tag distribution mismatch for '{tag_name}':", file=sys.stderr)
            print(f"    Expected: {sorted(expected_set)}", file=sys.stderr)
            print(f"    Actual: {sorted(actual_set)}", file=sys.stderr)
        elif tag_info["found"]:
            print(f"  ✓ Tag distribution maintained for '{tag_name}'")

    # Check Cafes tags
    print("\nCafes Database Tags:")
    for tag_name, tag_info in expected_pink_elements["cafes_tags"].items():
        if not tag_info["found"]:
            print(f"✗ Cafes tag '{tag_name}' not found (may have been renamed)", file=sys.stderr)
            # Don't fail if tag was renamed, as that's acceptable
        elif tag_info["has_pink"]:
            print(f"✗ Cafes tag '{tag_name}' still has pink color", file=sys.stderr)
            all_passed = False
        else:
            print(f"✓ Cafes tag '{tag_name}' color changed from pink")

        # Check distribution
        expected_set = set(tag_info["expected_items"])
        actual_set = set(tag_info["actual_items"])
        if tag_info["found"] and expected_set != actual_set:
            print(f"  ✗ Tag distribution mismatch for '{tag_name}':", file=sys.stderr)
            print(f"    Expected: {sorted(expected_set)}", file=sys.stderr)
            print(f"    Actual: {sorted(actual_set)}", file=sys.stderr)
        elif tag_info["found"]:
            print(f"  ✓ Tag distribution maintained for '{tag_name}'")

    # Additional check: ensure no other pink elements exist
    print("\nChecking for any other pink elements...")
    other_pink_found = False

    # Check all callouts for pink
    for block in all_blocks:
        if block and block.get("type") == "callout":
            color = block.get("callout", {}).get("color", "")
            if "pink" in color.lower():
                callout_text = notion_utils.get_block_plain_text(block)[:50]
                if "Welcome to Toronto!" not in callout_text:
                    print(f"✗ Found unexpected pink callout: {callout_text}...", file=sys.stderr)
                    other_pink_found = True

    if other_pink_found:
        all_passed = False
    else:
        print("✓ No unexpected pink elements found")

    if all_passed:
        return True, ""
    return False, "Some pink colors still exist or elements are missing"

def main():
    """
    Executes the verification process and exits with a status code.
    """
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None

    success, _error_msg = verify(notion, main_id)
    if success:
        print("\nVerification passed: All expected pink colors have been changed")
        sys.exit(0)
    else:
        print("\nVerification failed: Some pink colors still exist or elements are missing")
        sys.exit(1)

if __name__ == "__main__":
    main()
