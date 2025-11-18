#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Verification module for Weekend Adventure Planner task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the Perfect Weekend Adventure page has been created correctly.
    """
    # Find the main Toronto Guide page
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        page_id = notion_utils.find_page(notion, "Toronto Guide")
    if not page_id:
        print("Error: Main 'Toronto Guide' page not found.", file=sys.stderr)
        return False, "Error: Main 'Toronto Guide' page not found."

    # Find the Perfect Weekend Adventure child page
    adventure_page_id = None
    try:
        response = notion.search(
            query="Perfect Weekend Adventure",
            filter={"property": "object", "value": "page"}
        )

        for result in response.get("results", []):
            parent = result.get("parent", {})
            if parent.get("type") == "page_id" and parent.get("page_id") == page_id:
                adventure_page_id = result["id"]
                break

        if not adventure_page_id:
            for result in response.get("results", []):
                title_list = result.get("properties", {}).get("title", {}).get("title", [])
                for title_obj in title_list:
                    if "Perfect Weekend Adventure" in title_obj.get("plain_text", ""):
                        adventure_page_id = result["id"]
                        break
                if adventure_page_id:
                    break

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error searching for Perfect Weekend Adventure page: {e}", file=sys.stderr)
        return False, f"Error searching for Perfect Weekend Adventure page: {e}"

    if not adventure_page_id:
        msg = ("Error: 'Perfect Weekend Adventure' page not found as child "
               "of main page.")
        print(msg, file=sys.stderr)
        return False, msg

    # Get all blocks from the adventure page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, adventure_page_id)

    # Get databases from the main Toronto Guide page
    activities_db_id = None
    food_db_id = None
    cafes_db_id = None

    main_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)
    for block in main_blocks:
        if block.get("type") == "child_database":
            title = block.get("child_database", {}).get("title", "")
            if "Activities" in title:
                activities_db_id = block.get("id")
            elif "Food" in title:
                food_db_id = block.get("id")
            elif "Cafes" in title or "Caf�" in title:
                cafes_db_id = block.get("id")

    # Query databases to get expected data
    beach_activities = []
    cultural_restaurants = []
    cafes_list = []

    if activities_db_id:  # pylint: disable=too-many-nested-blocks
        try:
            db_response = notion.databases.query(database_id=activities_db_id)
            for page in db_response.get("results", []):
                properties = page.get("properties", {})
                tags_prop = properties.get("Tags", {})
                if tags_prop.get("type") == "multi_select":
                    tags = [tag.get("name") for tag in tags_prop.get("multi_select", [])]
                    if "Beaches" in tags:
                        name_prop = properties.get("Name", {})
                        if name_prop.get("type") == "title" and name_prop.get("title"):
                            name = name_prop["title"][0]["plain_text"]
                            url_prop = properties.get("Google Maps Link", {})
                            url = url_prop.get("url", "") if url_prop.get("type") == "url" else ""
                            beach_activities.append({"name": name, "url": url})
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error querying Activities database: {e}", file=sys.stderr)
            return False, f"Error querying Activities database: {e}"

    if food_db_id:  # pylint: disable=too-many-nested-blocks
        try:
            db_response = notion.databases.query(database_id=food_db_id)
            for page in db_response.get("results", []):
                properties = page.get("properties", {})
                tags_prop = properties.get("Tags", {})
                if tags_prop.get("type") == "multi_select":
                    tags = [tag.get("name") for tag in tags_prop.get("multi_select", [])]
                    for tag in tags:
                        if tag in ["Turkish", "Hakka"]:
                            name_prop = properties.get("Name", {})
                            if name_prop.get("type") == "title" and name_prop.get("title"):
                                name = name_prop["title"][0]["plain_text"]
                                cultural_restaurants.append({"name": name, "tag": tag})
                                break
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error querying Food database: {e}", file=sys.stderr)
            return False, f"Error querying Food database: {e}"

    if cafes_db_id:
        try:
            db_response = notion.databases.query(database_id=cafes_db_id)
            for page in db_response.get("results", []):
                properties = page.get("properties", {})
                name_prop = properties.get("Name", {})
                if name_prop.get("type") == "title" and name_prop.get("title"):
                    name = name_prop["title"][0]["plain_text"]
                    cafes_list.append(name)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Error querying Cafes database: {e}", file=sys.stderr)
            return False, f"Error querying Cafes database: {e}"

    # Required headings and their types
    required_headings = [
        ("🎒 Perfect Weekend Adventure", "heading_1"),
        ("🏖️ Beach Activities", "heading_2"),
        ("🍽️ Cultural Dining Experience", "heading_2"),
        ("☕ Coffee Break Spots", "heading_2"),
        ("📊 Weekend Summary", "heading_2")
    ]

    # Track verification results
    found_headings = set()
    found_beach_list = False
    found_restaurant_list = False
    found_toggle_with_cafes = False
    found_summary = False
    found_divider = False
    found_callout = False

    # Variables to track counts
    beach_count = 0
    restaurant_count = 0
    cafe_count = 0

    current_section = None
    is_in_toggle = False

    for block in all_blocks:
        block_type = block.get("type")
        block_text = notion_utils.get_block_plain_text(block)

        # Check headings
        for heading_text, expected_type in required_headings:
            if heading_text in block_text and block_type == expected_type:
                found_headings.add(heading_text)
                current_section = heading_text

        # Check Beach Activities section
        if current_section == "🏖️ Beach Activities" and block_type == "bulleted_list_item":
            found_beach_list = True
            beach_count += 1
            # Verify format includes name and potentially URL
            for activity in beach_activities:
                if activity["name"] in block_text:
                    if activity["url"] and activity["url"] not in block_text:
                        msg = f"Warning: Beach activity '{activity['name']}' missing URL"
                        print(msg, file=sys.stderr)

        # Check Cultural Dining section
        elif (current_section == "🍽️ Cultural Dining Experience" and
              block_type == "numbered_list_item"):
            found_restaurant_list = True
            restaurant_count += 1
            # Check format: Restaurant Name (Tag: [tag])
            for restaurant in cultural_restaurants:
                tag_text = f"Tag: {restaurant['tag']}"
                if restaurant["name"] in block_text and tag_text in block_text:
                    pass  # Format is correct

        # Check Coffee Break Spots section
        elif current_section == "☕ Coffee Break Spots":
            if block_type == "toggle" and "Top Cafes to Visit" in block_text:
                is_in_toggle = True
                found_toggle_with_cafes = True
            elif is_in_toggle and block_type == "to_do":
                cafe_count += 1
                # Verify unchecked status
                to_do_data = block.get("to_do", {})
                if to_do_data.get("checked", False):
                    msg = f"Error: Cafe to-do item should be unchecked: {block_text}"
                    print(msg, file=sys.stderr)
                    return False, msg
            elif block_type in ["heading_1", "heading_2", "heading_3"]:
                is_in_toggle = False

        # Check Weekend Summary section
        elif current_section == "📊 Weekend Summary" and block_type == "paragraph":
            beach_count_val = len(beach_activities)
            restaurant_count_val = len(cultural_restaurants)
            cafe_count_val = len(cafes_list)
            expected_text = (f"This weekend includes {beach_count_val} beach "
                             f"activities, {restaurant_count_val} cultural "
                             f"dining options, and {cafe_count_val} coffee "
                             f"spots to explore!")
            if expected_text in block_text:
                found_summary = True

        # Check for divider after summary
        if block_type == "divider":
            found_divider = True

        # Check for callout with pro tip
        if block_type == "callout":
            callout_data = block.get("callout", {})
            icon = callout_data.get("icon", {})
            if icon.get("type") == "emoji" and icon.get("emoji") == "💡":
                pro_tip_text = ("Pro tip: Check the Seasons database for the "
                                "best time to enjoy outdoor activities!")
                if pro_tip_text in block_text:
                    found_callout = True

    # Verify all required elements
    all_passed = True

    # Check all headings are present
    for heading_text, _ in required_headings:
        if heading_text not in found_headings:
            print(f"Error: Missing required heading: {heading_text}", file=sys.stderr)
            all_passed = False

    # Check beach activities list
    if not found_beach_list:
        print("Error: Beach activities bulleted list not found", file=sys.stderr)
        all_passed = False
    elif beach_count != len(beach_activities):
        msg = (f"Error: Expected {len(beach_activities)} beach activities, "
               f"found {beach_count}")
        print(msg, file=sys.stderr)
        all_passed = False

    # Check restaurant list
    if not found_restaurant_list:
        print("Error: Cultural dining numbered list not found", file=sys.stderr)
        all_passed = False
    elif restaurant_count != len(cultural_restaurants):
        msg = (f"Error: Expected {len(cultural_restaurants)} cultural "
               f"restaurants, found {restaurant_count}")
        print(msg, file=sys.stderr)
        all_passed = False

    # Check cafes toggle
    if not found_toggle_with_cafes:
        print("Error: Toggle block 'Top Cafes to Visit' not found", file=sys.stderr)
        all_passed = False
    elif cafe_count != len(cafes_list):
        print(f"Error: Expected {len(cafes_list)} cafes, found {cafe_count}", file=sys.stderr)
        all_passed = False

    # Check summary
    if not found_summary:
        print("Error: Weekend summary with correct counts not found", file=sys.stderr)
        all_passed = False

    # Check divider
    if not found_divider:
        print("Error: Divider block not found after summary", file=sys.stderr)
        all_passed = False

    # Check callout
    if not found_callout:
        print("Error: Callout with pro tip not found", file=sys.stderr)
        all_passed = False

    if all_passed:
        msg = "Success: Perfect Weekend Adventure page created with all required elements."
        print(msg)
        print(f"- {len(beach_activities)} beach activities")
        print(f"- {len(cultural_restaurants)} cultural dining options")
        print(f"- {len(cafes_list)} coffee spots")
        return True, ""
    return False, "Perfect Weekend Adventure page verification failed"


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
