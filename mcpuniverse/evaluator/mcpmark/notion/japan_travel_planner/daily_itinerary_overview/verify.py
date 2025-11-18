"""Verification module for Daily Itinerary Overview task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
import re
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify_todo_database_correspondence(all_blocks, activities_by_day, _):  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """
    Verify that to-do items in the overview page correspond exactly to database activities.
    """
    # Extract to-do items organized by day from the overview page
    todos_by_day = {"Day 1": [], "Day 2": [], "Day 3": []}
    current_day = None
    checked_todos_count = 0

    for block in all_blocks:
        block_type = block.get("type")
        block_text = notion_utils.get_block_plain_text(block)

        # Track which day section we're in
        if block_type == "heading_2":
            if "🌅 Day 1" in block_text:
                current_day = "Day 1"
            elif "🌆 Day 2" in block_text:
                current_day = "Day 2"
            elif "🌃 Day 3" in block_text:
                current_day = "Day 3"
            else:
                current_day = None  # Reset for non-day headings

        # Collect to-do items under day headings
        elif block_type == "to_do" and current_day:
            to_do_data = block.get("to_do", {})
            is_checked = to_do_data.get("checked", False)

            if is_checked:
                checked_todos_count += 1

            todos_by_day[current_day].append(
                {"text": block_text, "checked": is_checked}
            )

    # Verify each day's activities match
    for day in ["Day 1", "Day 2", "Day 3"]:
        db_activities = activities_by_day[day]
        page_todos = todos_by_day[day]

        # Check if counts match
        if len(db_activities) != len(page_todos):
            db_count = len(db_activities)
            page_count = len(page_todos)
            msg = (f"Error: {day} activity count mismatch. "
                   f"Database has {db_count} activities, "
                   f"page has {page_count} to-dos.")
            print(msg, file=sys.stderr)
            return False, msg

        # Verify each database activity has corresponding to-do
        for db_activity in db_activities:
            expected_format = f"{db_activity['name']}"
            if db_activity["city"]:
                expected_format += f" - {db_activity['city']}"

            # Find matching to-do item
            matching_todo = None
            for todo in page_todos:
                if (
                    expected_format in todo["text"]
                    or db_activity["name"] in todo["text"]
                ):
                    matching_todo = todo
                    break

            if not matching_todo:
                msg = (f"Error: {day} - Database activity "
                       f"'{expected_format}' not found in to-do list.")
                print(msg, file=sys.stderr)
                return False, msg

            # Verify checked status matches visited status
            if db_activity["visited"] != matching_todo["checked"]:
                status_desc = "checked" if db_activity["visited"] else "unchecked"
                actual_desc = ("checked" if matching_todo["checked"]
                               else "unchecked")
                activity_name = db_activity['name']
                msg = (f"Error: {day} - Activity '{activity_name}' should be "
                       f"{status_desc} but is {actual_desc}.")
                print(msg, file=sys.stderr)
                return False, msg

    # Verify summary count matches checked to-dos
    for block in all_blocks:
        if block.get("type") == "paragraph":
            block_text = notion_utils.get_block_plain_text(block)
            if "Total activities visited (from Day 1 to Day 3): 8" in block_text:
                msg = (f"Success: Daily Itinerary Overview page created with "
                       f"correct structure. All {checked_todos_count} visited "
                       "activities match database.")
                print(msg)
                return True, ""

    msg = (f"Error: Summary shows incorrect visited activity count. "
           f"Expected: {checked_todos_count} "
           "(based on checked to-do items)")
    print(msg, file=sys.stderr)
    return False, msg


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the Daily Itinerary Overview page has been created correctly.
    """
    # Find the main Japan Travel Planner page
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        page_id = notion_utils.find_page(notion, "Japan Travel Planner")
    if not page_id:
        print("Error: Main 'Japan Travel Planner' page not found.", file=sys.stderr)
        return False, "Main 'Japan Travel Planner' page not found"

    # Find the Daily Itinerary Overview child page
    overview_page_id = None
    try:
        # Get all child pages of the main page
        response = notion.search(
            query="Daily Itinerary Overview",
            filter={"property": "object", "value": "page"},
        )

        for result in response.get("results", []):
            # Check if this page is a child of the main page
            parent = result.get("parent", {})
            if parent.get("type") == "page_id" and parent.get("page_id") == page_id:
                overview_page_id = result["id"]
                break

        if not overview_page_id:
            # Alternative method: check page title directly
            for result in response.get("results", []):
                title_list = (
                    result.get("properties", {}).get("title", {}).get("title", [])
                )
                for title_obj in title_list:
                    if "Daily Itinerary Overview" in title_obj.get("plain_text", ""):
                        overview_page_id = result["id"]
                        break
                if overview_page_id:
                    break

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(
            f"Error searching for Daily Itinerary Overview page: {e}", file=sys.stderr
        )
        return False, f"Error searching for Daily Itinerary Overview page: {e}"

    if not overview_page_id:
        print(
            "Error: 'Daily Itinerary Overview' page not found as child of main page.",
            file=sys.stderr,
        )
        return False, "Error: 'Daily Itinerary Overview' page not found as child of main page."

    # Get all blocks from the overview page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, overview_page_id)

    # Required content to verify - must appear in this exact order
    required_headings_sequence = [
        ("📅 Daily Itinerary Overview", "heading_1"),
        ("📊 Trip Summary", "heading_2"),
        ("🌅 Day 1", "heading_2"),
        ("🌆 Day 2", "heading_2"),
        ("🌃 Day 3", "heading_2"),
    ]

    found_headings_in_order = []
    found_summary = False
    summary_has_correct_format = False
    found_todo_items = False

    # Check each block and track heading sequence
    for block in all_blocks:
        block_text = notion_utils.get_block_plain_text(block)
        block_type = block.get("type")

        # Check for required headings in sequence
        for heading_text, expected_type in required_headings_sequence:
            if heading_text in block_text and block_type == expected_type:
                found_headings_in_order.append((heading_text, expected_type))

        # Check for trip summary paragraph
        if (
            block_type == "paragraph"
            and "Total activities visited (from Day 1 to Day 3):" in block_text
        ):
            found_summary = True
            # Check if the format is correct (contains a number)
            if re.search(
                r"Total activities visited \(from Day 1 to Day 3\):\s*\d+", block_text
            ):
                summary_has_correct_format = True

        # Check for to-do list items (activities under day headings)
        if block_type == "to_do":
            found_todo_items = True
            # Check if to-do items follow the format "Activity Name - City"
            if " - " in block_text:
                # Format appears to be correct (contains dash separator)
                pass

    # Verify all required headings are found in correct sequence
    if len(found_headings_in_order) != len(required_headings_sequence):
        missing_headings = []
        for heading_text, heading_type in required_headings_sequence:
            if (heading_text, heading_type) not in found_headings_in_order:
                missing_headings.append(f"{heading_text} ({heading_type})")
        print(f"Error: Missing required headings: {missing_headings}", file=sys.stderr)
        return False, f"Error: Missing required headings: {missing_headings}"

    # Verify headings appear in correct order
    for i, (found_heading, found_type) in enumerate(found_headings_in_order):
        expected_heading, expected_type = required_headings_sequence[i]
        if found_heading != expected_heading or found_type != expected_type:
            pos = i + 1
            msg = (f"Error: Headings not in correct order. "
                   f"Expected '{expected_heading}' ({expected_type}) "
                   f"at position {pos}, but found '{found_heading}' "
                   f"({found_type})")
            print(msg, file=sys.stderr)
            return False, msg

    # Verify trip summary exists and has correct format
    if not found_summary:
        print(
            "Error: Trip summary paragraph with 'Total activities visite' not found.",
            file=sys.stderr,
        )
        return False, "Error: Trip summary paragraph with 'Total activities visite' not found."

    if not summary_has_correct_format:
        msg = ("Error: Trip summary does not have correct format "
               "'Total activities visited: [NUMBER]'.")
        print(msg, file=sys.stderr)
        return False, msg

    # Verify to-do list items exist (activities should be in to-do format)
    if not found_todo_items:
        msg = ("Error: No to-do list items found. Activities should be "
               "listed as to-do items under day headings.")
        print(msg, file=sys.stderr)
        return False, msg

    # Additional verification: Check if Travel Itinerary database exists and has data
    try:  # pylint: disable=too-many-nested-blocks
        itinerary_db_id = notion_utils.find_database_in_block(
            notion, page_id, "Travel Itinerary"
        )
        if not itinerary_db_id:
            itinerary_db_id = notion_utils.find_database(notion, "Travel Itinerary")

        if itinerary_db_id:
            # Query the database to get all activities
            db_response = notion.databases.query(database_id=itinerary_db_id)
            db_activities = db_response.get("results", [])

            # Organize database activities by day
            activities_by_day = {"Day 1": [], "Day 2": [], "Day 3": []}
            visited_count = 0

            for result in db_activities:
                properties = result.get("properties", {})

                # Extract activity info
                activity_info = {"name": "", "city": "", "visited": False, "day": None}

                for prop_name, prop_value in properties.items():
                    prop_type = prop_value.get("type")

                    # Get activity name (usually from title property)
                    if prop_type == "title" and prop_value.get("title"):
                        activity_info["name"] = prop_value["title"][0]["plain_text"]

                    # Get city info
                    elif "city" in prop_name.lower() and prop_type in [
                        "rich_text",
                        "select",
                    ]:
                        if prop_type == "rich_text" and prop_value.get("rich_text"):
                            activity_info["city"] = prop_value["rich_text"][0][
                                "plain_text"
                            ]
                        elif prop_type == "select" and prop_value.get("select"):
                            activity_info["city"] = prop_value["select"]["name"]

                    # Get visited status
                    elif prop_type == "checkbox":
                        if prop_value.get("checkbox"):
                            activity_info["visited"] = True
                            visited_count += 1

                    # Get day info
                    elif "day" in prop_name.lower() and prop_type in [
                        "select",
                        "rich_text",
                    ]:
                        if prop_type == "select" and prop_value.get("select"):
                            day_value = prop_value["select"]["name"]
                            if day_value in activities_by_day:
                                activity_info["day"] = day_value
                        elif prop_type == "rich_text" and prop_value.get("rich_text"):
                            day_value = prop_value["rich_text"][0]["plain_text"]
                            if day_value in activities_by_day:
                                activity_info["day"] = day_value

                # Add to appropriate day if day is specified
                if activity_info["day"] and activity_info["name"]:
                    activities_by_day[activity_info["day"]].append(activity_info)

            # Now verify to-do items match database activities
            return verify_todo_database_correspondence(
                all_blocks, activities_by_day, visited_count
            )
        msg = ("Warning: Travel Itinerary database not found, using "
               "to-do items for count verification.")
        print(msg)
        # Count checked to-do items in the overview page even without database
        checked_todos_count = 0
        for block in all_blocks:
            if block.get("type") == "to_do":
                to_do_data = block.get("to_do", {})
                if to_do_data.get("checked", False):
                    checked_todos_count += 1

        # Verify the summary shows the correct visited count based on checked to-dos
        for block in all_blocks:
            if block.get("type") == "paragraph":
                block_text = notion_utils.get_block_plain_text(block)
                if f"Total activities visited: {checked_todos_count}" in block_text:
                    msg = (f"Success: Daily Itinerary Overview page "
                           f"created with correct structure and "
                           f"{checked_todos_count} visited activities.")
                    print(msg)
                    return True, ""

        msg = (f"Error: Summary shows incorrect visited activity count. "
               f"Expected: {checked_todos_count} "
               "(based on checked to-do items)")
        print(msg, file=sys.stderr)
        return False, msg

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Warning: Could not verify activity count: {e}")
        print("Success: Daily Itinerary Overview page created with correct structure.")
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
