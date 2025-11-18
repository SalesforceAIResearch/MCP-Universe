"""Verification module for Remove Osaka Itinerary task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def get_page_title(page_result):
    """Extract title from a page result"""
    properties = page_result.get('properties', {})
    name_property = properties.get('Name', {})
    if name_property.get('type') == 'title':
        title_array = name_property.get('title', [])
        if title_array and len(title_array) > 0:
            return title_array[0].get('plain_text', '')
    return ''

def get_page_time(page_result):
    """Extract time from Notes field"""
    properties = page_result.get('properties', {})
    notes_property = properties.get('Notes', {})
    if notes_property.get('type') == 'rich_text':
        rich_text_array = notes_property.get('rich_text', [])
        if rich_text_array and len(rich_text_array) > 0:
            notes_text = rich_text_array[0].get('plain_text', '')
            return notes_text.strip()
    return ''

def get_page_group(page_result):
    """Extract group/location from page"""
    properties = page_result.get('properties', {})
    group_property = properties.get('Group', {})
    if group_property.get('type') == 'select':
        select = group_property.get('select')
        if select:
            return select.get('name', '')
    return ''

def get_page_day(page_result):
    """Extract day from page"""
    properties = page_result.get('properties', {})
    day_property = properties.get('Day', {})
    if day_property.get('type') == 'select':
        select = day_property.get('select')
        if select:
            return select.get('name', '')
    return ''

def parse_time_to_minutes(time_str):
    """Convert time string to minutes for comparison
    Returns None if time cannot be parsed"""
    if not time_str:
        return None

    # Clean the time string
    time_str = time_str.strip().upper()

    # Remove any text after the time (e.g., "7:30 PM\n" -> "7:30 PM")
    time_str = time_str.split('\n')[0].strip()

    # Extract time components
    try:
        if 'PM' in time_str:
            time_part = time_str.replace('PM', '').strip()
            if ':' in time_part:
                hours, minutes = time_part.split(':')
                hours = int(hours)
                minutes = int(minutes)
            else:
                hours = int(time_part)
                minutes = 0
            # Convert PM hours (add 12 for PM times except 12 PM)
            if hours != 12:
                hours += 12
            return hours * 60 + minutes
        if 'AM' in time_str:
            time_part = time_str.replace('AM', '').strip()
            if ':' in time_part:
                hours, minutes = time_part.split(':')
                hours = int(hours)
                minutes = int(minutes)
            else:
                hours = int(time_part)
                minutes = 0
            # Handle 12 AM (midnight)
            if hours == 12:
                hours = 0
            return hours * 60 + minutes
    except (ValueError, TypeError, AttributeError):
        return None

    return None

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """
    Verifies that all OSAKA events after 6PM have been removed from Day 1
    and Day 2 in the Japan Travel Planner.

    Expected items that should be deleted (all in OSAKA, after 6PM, on Day 1 or Day 2):
    1. Rikuro's Namba Main Branch - 7 PM (Day 1)
    2. Shin Sekai "New World" - 8 PM (Day 2)
    3. Katsudon Chiyomatsu - 7:30 PM (Day 2)
    4. Ebisubashi Bridge - 9 PM (Day 1)

    Note: Kuromon Ichiba Market at 6 PM should NOT be deleted (it's at 6PM, not after)
    Items after 6PM on other days (Day 3-8) should NOT be deleted
    """

    # Step 1: Find the main Japan Travel Planner page
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if not found_id or object_type != 'page':
            print("Error: Japan Travel Planner page not found.", file=sys.stderr)
            return False, "Error: Japan Travel Planner page not found."
    else:
        # Try to find the page by searching
        found_id = notion_utils.find_page(notion, "Japan Travel Planner")
        if not found_id:
            print("Error: Japan Travel Planner page not found.", file=sys.stderr)
            return False, "Error: Japan Travel Planner page not found."

    print(f"Found Japan Travel Planner page: {found_id}")

    # Step 2: Find the Travel Itinerary database
    all_blocks = notion_utils.get_all_blocks_recursively(notion, found_id)
    travel_itinerary_db_id = None

    for block in all_blocks:
        if block and block.get("type") == "child_database":
            title = block.get("child_database", {}).get("title", "")
            if "Travel Itinerary" in title:
                travel_itinerary_db_id = block.get("id")
                print(f"Found Travel Itinerary database: {travel_itinerary_db_id}")
                break

    if not travel_itinerary_db_id:
        print("Error: Travel Itinerary database not found", file=sys.stderr)
        return False, "Error: Travel Itinerary database not found"

    # Step 3: Query the database for OSAKA items on Day 1 and Day 2
    try:
        query_result = notion.databases.query(
            database_id=travel_itinerary_db_id,
            filter={
                "and": [
                    {"property": "Group", "select": {"equals": "Osaka"}},
                    {"or": [
                        {"property": "Day", "select": {"equals": "Day 1"}},
                        {"property": "Day", "select": {"equals": "Day 2"}}
                    ]}
                ]
            }
        )
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Travel Itinerary database: {e}", file=sys.stderr)
        return False, f"Error querying Travel Itinerary database: {e}"

    # Step 4: Check for items that should have been deleted
    six_pm_minutes = 18 * 60  # 6 PM in minutes (18:00)

    # Expected deleted items (4 specific items after 6 PM on Day 1 and Day 2)
    expected_deleted = {
        "Rikuro's Namba Main Branch": {"time": "7 PM", "day": "Day 1", "found": False},
        "Shin Sekai \"New World\"": {"time": "8 PM", "day": "Day 2", "found": False},
        "Katsudon Chiyomatsu": {"time": "7:30 PM", "day": "Day 2", "found": False},
        "Ebisubashi Bridge": {"time": "9 PM", "day": "Day 1", "found": False}
    }

    # Items that should remain (at or before 6 PM)
    expected_remaining = {
        "Kuromon Ichiba Market": {"time": "6 PM", "found": False}
    }

    osaka_items_after_6pm = []
    osaka_items_at_or_before_6pm = []

    # Debug: Show total query results
    results_count = len(query_result.get('results', []))
    msg = (f"Debug: Found {results_count} total OSAKA items on "
           "Day 1 and Day 2")
    print(msg)

    # Process all OSAKA items on Day 1 and Day 2
    for page in query_result.get('results', []):
        page_title = get_page_title(page).strip()
        page_time = get_page_time(page)
        page_group = get_page_group(page)
        page_day = get_page_day(page)

        if page_group != "Osaka":
            continue

        # Parse time to check if after 6 PM
        time_minutes = parse_time_to_minutes(page_time)

        if time_minutes is not None and time_minutes > six_pm_minutes:
            osaka_items_after_6pm.append({
                "title": page_title,
                "time": page_time,
                "day": page_day,
                "id": page.get('id')
            })

            # Check if this is one of the expected deleted items
            for expected_title, expected_info in expected_deleted.items():
                # Clean up the titles for comparison
                clean_page_title = page_title.strip().lower()
                clean_expected_title = expected_title.strip().lower()

                # Check for "Rikuro's" or "Rikuro's" (different apostrophe types)
                if "rikuro" in clean_page_title and "rikuro" in clean_expected_title:
                    title_match = True
                elif clean_page_title == clean_expected_title:
                    title_match = True
                elif (clean_expected_title in clean_page_title or
                      clean_page_title in clean_expected_title):
                    title_match = True
                else:
                    title_match = False

                if title_match and page_day == expected_info["day"]:
                    msg = (f"Debug: Found '{page_title}' on {page_day} at "
                           f"{page_time} - matches expected '{expected_title}'")
                    print(msg)
                    expected_deleted[expected_title]["found"] = True  # pylint: disable=unnecessary-dict-index-lookup

        elif time_minutes is not None and time_minutes <= six_pm_minutes:
            osaka_items_at_or_before_6pm.append({
                "title": page_title,
                "time": page_time,
                "day": page_day,
                "id": page.get('id')
            })

            # Check if this is one of the expected remaining items
            for expected_title, expected_info in expected_remaining.items():
                title_lower = page_title.lower()
                expected_lower = expected_title.lower()
                if title_lower in expected_lower or expected_lower in title_lower:
                    expected_info["found"] = True

    # Step 5: Verify results
    print("\nVerification Summary:")
    print("=" * 50)

    all_passed = True

    # Check that the 4 expected items after 6 PM have been deleted
    print("\n4 Items that should be deleted (after 6 PM on Day 1 and Day 2):")
    for item_name, item_info in expected_deleted.items():
        if item_info["found"]:
            # If found = True, it means the item still exists (was not deleted)
            msg = (f"✗ {item_name} ({item_info['day']}, {item_info['time']}) "
                   "- Still exists, should be deleted")
            print(msg, file=sys.stderr)
            all_passed = False
        else:
            # If found = False, it means the item was deleted correctly
            msg = (f"✓ {item_name} ({item_info['day']}, {item_info['time']}) "
                   "- Correctly deleted")
            print(msg)


    # Check that items at or before 6 PM remain
    print("\nItems that should remain (at or before 6 PM on Day 1 and Day 2):")
    for item_name, item_info in expected_remaining.items():
        if item_info["found"]:
            print(f"✓ {item_name} ({item_info['time']}) - Correctly retained")
        else:
            msg = (f"✗ {item_name} ({item_info['time']}) - Missing, "
                   "should not be deleted")
            print(msg, file=sys.stderr)
            all_passed = False

    # Report any items after 6 PM that still exist
    if osaka_items_after_6pm:
        items_count = len(osaka_items_after_6pm)
        msg = (f"\n✗ Found {items_count} OSAKA item(s) after 6 PM on "
               "Day 1/Day 2:")
        print(msg, file=sys.stderr)
        for item in osaka_items_after_6pm:
            print(f"  - {item['title']} at {item['time']} ({item['day']})",
                  file=sys.stderr)
    else:
        msg = ("\n✓ No OSAKA items found after 6 PM on Day 1/Day 2 "
               "(all correctly deleted)")
        print(msg)

    # Report count summary
    print("\nCount Summary:")
    after_6pm_count = len(osaka_items_after_6pm)
    print(f"- OSAKA items after 6 PM on Day 1/Day 2 found: {after_6pm_count} "
          "(should be 0)")
    at_or_before_count = len(osaka_items_at_or_before_6pm)
    print(f"- OSAKA items at/before 6 PM on Day 1/Day 2 found: "
          f"{at_or_before_count}")
    verified_count = sum(1 for item in expected_deleted.values()
                         if not item['found'])
    print(f"- Expected deletions verified: {verified_count}/4")

    return all_passed, ""

def main():
    """
    Executes the verification process and exits with a status code.
    """
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None

    success, _error_msg = verify(notion, main_id)
    if success:
        msg = ("\nVerification passed: All 4 required OSAKA events after "
               "6 PM on Day 1 and Day 2 have been removed")
        print(msg)
        sys.exit(0)
    else:
        msg = ("\nVerification failed: Some OSAKA events after 6 PM on "
               "Day 1/Day 2 still exist")
        print(msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
