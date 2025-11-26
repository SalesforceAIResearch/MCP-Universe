"""Verification module for Restaurant Expenses Sync task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that restaurants from Day 1 of Travel Itinerary have corresponding expense entries.
    """
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
        print("Error: Page 'Japan Travel Planner' not found.", file=sys.stderr)
        return False, "Error: Page 'Japan Travel Planner' not found."

    # Find Travel Itinerary database
    itinerary_db_id = notion_utils.find_database_in_block(
        notion, page_id, "Travel Itinerary"
    )
    if not itinerary_db_id:
        print("Error: Database 'Travel Itinerary' not found.", file=sys.stderr)
        return False, "Error: Database 'Travel Itinerary' not found."

    # Find Expenses database
    expenses_db_id = notion_utils.find_database_in_block(notion, page_id, "Expenses")
    if not expenses_db_id:
        print("Error: Database 'Expenses' not found.", file=sys.stderr)
        return False, "Error: Database 'Expenses' not found."

    # Find Japan Places to Visit database
    places_db_id = notion_utils.find_database_in_block(
        notion, page_id, "Travel Itinerary"
    )
    if not places_db_id:
        print("Error: Database 'Japan Places to Visit' not found.", file=sys.stderr)
        return False, "Error: Database 'Japan Places to Visit' not found."

    # Query Day 1 restaurants from Travel Itinerary
    try:
        itinerary_results = notion.databases.query(
            database_id=itinerary_db_id,
            filter={
                "and": [
                    {"property": "Day", "select": {"equals": "Day 1"}},
                    {"property": "Type", "multi_select": {"contains": "Food"}},
                ]
            },
        ).get("results", [])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Travel Itinerary database: {e}", file=sys.stderr)
        return False, f"Error querying Travel Itinerary database: {e}"

    if not itinerary_results:
        print(
            "Error: No restaurants found for Day 1 in Travel Itinerary.",
            file=sys.stderr,
        )
        return False, "Error: No restaurants found for Day 1 in Travel Itinerary."

    # Extract restaurant names
    restaurant_names = []
    for entry in itinerary_results:
        props = entry.get("properties", {})
        name_prop = props.get("Name", {})
        name_text = "".join(t.get("plain_text", "") for t in name_prop.get("title", []))
        if name_text:
            restaurant_names.append(name_text.strip())

    if not restaurant_names:
        print("Error: No restaurant names found in Day 1 entries.", file=sys.stderr)
        return False, "Error: No restaurant names found in Day 1 entries."

    # Get descriptions from Japan Places to Visit database
    try:
        places_results = notion.databases.query(database_id=places_db_id).get(
            "results", []
        )
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Japan Places to Visit database: {e}", file=sys.stderr)
        return False, f"Error querying Japan Places to Visit database: {e}"

    # Create a map of restaurant names to descriptions
    restaurant_descriptions = {}
    for place in places_results:
        props = place.get("properties", {})
        name_prop = props.get("Name", {})
        name_text = "".join(t.get("plain_text", "") for t in name_prop.get("title", []))

        desc_prop = props.get("Description", {})
        desc_text = "".join(
            t.get("plain_text", "") for t in desc_prop.get("rich_text", [])
        )

        if name_text and desc_text:
            restaurant_descriptions[name_text.strip()] = desc_text.strip()

    # Query Expenses database
    try:
        expenses_results = notion.databases.query(database_id=expenses_db_id).get(
            "results", []
        )
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Expenses database: {e}", file=sys.stderr)
        return False, f"Error querying Expenses database: {e}"

    # Verify each restaurant has a corresponding expense entry
    verified_restaurants = []
    for restaurant_name in restaurant_names:
        found_matching_expense = False
        expected_description = restaurant_descriptions.get(restaurant_name, "")

        for expense in expenses_results:
            props = expense.get("properties", {})

            # Check Expense field (title)
            expense_prop = props.get("Expense", {})
            expense_text = "".join(
                t.get("plain_text", "") for t in expense_prop.get("title", [])
            )
            if expense_text.strip() != restaurant_name:
                continue

            # Check Date
            date_prop = props.get("Date", {})
            date_start = date_prop.get("date", {}).get("start")
            if date_start != "2025-01-01":
                continue

            # Check Transaction Amount
            amount_prop = props.get("Transaction Amount", {})
            amount = amount_prop.get("number")
            if amount != 120:
                continue

            # Check Category contains Dining
            category_prop = props.get("Category", {})
            categories = [c.get("name") for c in category_prop.get("multi_select", [])]
            if "Dining" not in categories:
                continue

            # Check Comment matches description (if description exists)
            if expected_description:
                comment_prop = props.get("Comment", {})
                comment_text = "".join(
                    t.get("plain_text", "") for t in comment_prop.get("rich_text", [])
                )
                if comment_text.strip().replace(
                    "\u202f", " "
                ) != expected_description.replace("\u202f", " "):
                    continue

            found_matching_expense = True
            verified_restaurants.append(restaurant_name)
            break

        if not found_matching_expense:
            print(
                f"Error: No matching expense entry found for restaurant '{restaurant_name}'.",
                file=sys.stderr,
            )
            msg = (f"Error: No matching expense entry found for restaurant "
                   f"'{restaurant_name}'.")
            return False, msg

    if len(verified_restaurants) == len(restaurant_names):
        total_count = len(restaurant_names)
        msg = (f"Success: Found matching expense entries for all "
               f"{total_count} Day 1 restaurants.")
        print(msg)
        return True, ""
    verified_count = len(verified_restaurants)
    total_count = len(restaurant_names)
    msg = (f"Error: Only {verified_count} out of {total_count} restaurants "
           "have matching expense entries.")
    print(msg, file=sys.stderr)
    return False, msg


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
