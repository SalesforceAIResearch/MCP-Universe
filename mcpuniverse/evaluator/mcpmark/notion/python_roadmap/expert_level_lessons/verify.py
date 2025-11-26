"""Verification module for Expert Level Lessons task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the Expert Level chapter and its lessons have been created
    correctly with complex prerequisites.
    """
    # Step 1: Find the main page and get database IDs
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if not found_id or object_type != 'page':
            print("Error: Main page not found.", file=sys.stderr)
            return False, "Main page not found"
    else:
        # Try to find the main page by searching
        found_id = notion_utils.find_page(notion, "Python Roadmap")
        if not found_id:
            print("Error: Main page not found.", file=sys.stderr)
            return False, "Main page not found"

    print(f"Found main page: {found_id}")

    # Get all blocks from the page to find database references
    all_blocks = notion_utils.get_all_blocks_recursively(notion, found_id)
    print(f"Found {len(all_blocks)} blocks")

    # Find database IDs from the page
    chapters_db_id = None
    steps_db_id = None

    for block in all_blocks:
        if block and block.get("type") == "child_database":
            db_title = block.get("child_database", {}).get("title", "")
            if "Chapters" in db_title:
                chapters_db_id = block["id"]
                print(f"Found Chapters database: {chapters_db_id}")
            elif "Steps" in db_title:
                steps_db_id = block["id"]
                print(f"Found Steps database: {steps_db_id}")

    if not chapters_db_id:
        print("Error: Chapters database not found.", file=sys.stderr)
        return False, "Chapters database not found"

    if not steps_db_id:
        print("Error: Steps database not found.", file=sys.stderr)
        return False, "Steps database not found"

    print("Starting verification...")

    # Step 2: Verify the Expert Level chapter exists
    print("2. Checking for Expert Level chapter...")
    expert_chapter_id = None

    try:
        chapters_response = notion.databases.query(
            database_id=chapters_db_id,
            filter={
                "property": "Name",
                "title": {
                    "equals": "Expert Level"
                }
            }
        )

        if not chapters_response.get("results"):
            print("Error: Expert Level chapter not found in Chapters database.", file=sys.stderr)
            return False, "Expert Level chapter not found in Chapters database"

        expert_chapter = chapters_response["results"][0]
        expert_chapter_id = expert_chapter["id"]

        # Check chapter icon (purple circle)
        chapter_icon = expert_chapter.get("icon")
        icon_type_ok = chapter_icon and chapter_icon.get("type") == "emoji"
        icon_emoji_ok = chapter_icon and chapter_icon.get("emoji") == "🟣"
        if not icon_type_ok or not icon_emoji_ok:
            msg = ("Error: Expert Level chapter does not have the correct "
                   "purple circle emoji icon.")
            print(msg, file=sys.stderr)
            return False, msg

        print("✓ Expert Level chapter found with correct icon: 🟣")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Chapters database: {e}", file=sys.stderr)
        return False, f"Error querying Chapters database: {e}"

    # Step 3: Find Control Flow lesson (In Progress status)
    print("3. Finding Control Flow lesson...")
    control_flow_id = None

    try:
        control_flow_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "and": [
                    {
                        "property": "Lessons",
                        "title": {
                            "contains": "Control"
                        }
                    },
                    {
                        "property": "Status",
                        "status": {
                            "equals": "Done"  # Should be updated to Done
                        }
                    }
                ]
            }
        )

        if control_flow_response.get("results"):
            control_flow_lesson = control_flow_response["results"][0]
            control_flow_id = control_flow_lesson["id"]
            print("✓ Found Control Flow lesson with status 'Done'")
        else:
            print("Error: Control Flow lesson not found with status 'Done'.", file=sys.stderr)
            return False, "Control Flow lesson not found with status 'Done'"

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error finding Control Flow lesson: {e}", file=sys.stderr)
        return False, f"Error finding Control Flow lesson: {e}"

    # Step 4: Find prerequisite lessons
    print("4. Finding prerequisite lessons...")

    decorators_id = None
    calling_api_id = None
    regex_id = None

    try:
        # Find Decorators (should be Done)
        decorators_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "contains": "Decorators"
                }
            }
        )

        if decorators_response.get("results"):
            decorators_lesson = decorators_response["results"][0]
            decorators_id = decorators_lesson["id"]
            # Check status is Done
            if decorators_lesson["properties"]["Status"]["status"]["name"] != "Done":
                print("Error: Decorators lesson should have status 'Done'.", file=sys.stderr)
                return False, "Decorators lesson should have status 'Done'"
            print("✓ Found Decorators lesson with status 'Done'")
        else:
            print("Error: Decorators lesson not found.", file=sys.stderr)
            return False, "Decorators lesson not found"

        # Find Calling API
        calling_api_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "equals": "Calling API"
                }
            }
        )

        if calling_api_response.get("results"):
            calling_api_lesson = calling_api_response["results"][0]
            calling_api_id = calling_api_lesson["id"]
            print("✓ Found Calling API lesson")
        else:
            print("Error: Calling API lesson not found.", file=sys.stderr)
            return False, "Calling API lesson not found"

        # Find Regular Expressions
        regex_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "contains": "Regular Expressions"
                }
            }
        )

        if regex_response.get("results"):
            regex_lesson = regex_response["results"][0]
            regex_id = regex_lesson["id"]
            print("✓ Found Regular Expressions lesson")
        else:
            print("Error: Regular Expressions lesson not found.", file=sys.stderr)
            return False, "Regular Expressions lesson not found"

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error finding prerequisite lessons: {e}", file=sys.stderr)
        return False, f"Error finding prerequisite lessons: {e}"

    # Step 5: Verify Advanced Foundations Review bridge lesson
    print("5. Checking Advanced Foundations Review bridge lesson...")
    bridge_id = None

    try:
        bridge_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "equals": "Advanced Foundations Review"
                }
            }
        )

        if not bridge_response.get("results"):
            print("Error: Advanced Foundations Review lesson not found.", file=sys.stderr)
            return False, "Advanced Foundations Review lesson not found"

        bridge_lesson = bridge_response["results"][0]
        bridge_id = bridge_lesson["id"]

        # Check status is Done
        if bridge_lesson["properties"]["Status"]["status"]["name"] != "Done":
            print("Error: Advanced Foundations Review should have status 'Done'.", file=sys.stderr)
            return False, "Advanced Foundations Review should have status 'Done'"

        # Check linked to Expert Level chapter
        bridge_chapters = bridge_lesson["properties"]["Chapters"]["relation"]
        if not any(rel["id"] == expert_chapter_id for rel in bridge_chapters):
            msg = ("Error: Advanced Foundations Review not linked to "
                   "Expert Level chapter.")
            print(msg, file=sys.stderr)
            return False, msg

        # Check Parent item is Control Flow
        bridge_parent = bridge_lesson["properties"]["Parent item"]["relation"]
        if not bridge_parent or bridge_parent[0]["id"] != control_flow_id:
            msg = ("Error: Advanced Foundations Review should have Control "
                   "Flow as Parent item.")
            print(msg, file=sys.stderr)
            return False, msg

        # Check Sub-items (should have at least 3 specific lessons plus
        # any that reference it as parent)
        bridge_subitems = bridge_lesson["properties"]["Sub-item"]["relation"]
        required_subitems = {decorators_id, calling_api_id, regex_id}
        actual_subitems = {item["id"] for item in bridge_subitems}

        if not required_subitems.issubset(actual_subitems):
            msg = ("Error: Advanced Foundations Review should have at least "
                   "these 3 sub-items: Decorators, Calling API, "
                   "Regular Expressions.")
            print(msg, file=sys.stderr)
            return False, msg

        # Due to bidirectional relations, lessons that have this as parent
        # will also appear as sub-items
        # We expect at least 5: 3 initial + 2 that reference it as parent
        # (Metaprogramming and Memory Management)
        if len(bridge_subitems) < 5:
            msg = (f"Error: Advanced Foundations Review should have at least "
                   f"5 sub-items (3 initial + 2 from parent relations), "
                   f"found {len(bridge_subitems)}.")
            print(msg, file=sys.stderr)
            return False, msg

        subitems_count = len(bridge_subitems)
        msg = (f"✓ Advanced Foundations Review has {subitems_count} "
               "sub-items, including the 3 required ones")
        print(msg)

        print("✓ Advanced Foundations Review found with correct properties")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error checking bridge lesson: {e}", file=sys.stderr)
        return False, f"Error checking bridge lesson: {e}"

    # Step 6: Verify the 4 expert lessons
    print("6. Checking the 4 expert lessons...")

    # Note: Async Concurrency Patterns will have Error Handling as parent (due to sub-item relation)
    # We'll need to find Error Handling's ID first
    error_handling_response = notion.databases.query(
        database_id=steps_db_id,
        filter={
            "property": "Lessons",
            "title": {
                "equals": "Error Handling"
            }
        }
    )

    error_handling_id = None
    if error_handling_response.get("results"):
        error_handling_id = error_handling_response["results"][0]["id"]
    else:
        print("Error: Error Handling lesson not found.", file=sys.stderr)
        return False, "Error Handling lesson not found"

    expert_lessons = {
        "Metaprogramming and AST Manipulation": {
            "status": "To Do",
            "parent": bridge_id,
            "date": "2025-09-15"
        },
        "Async Concurrency Patterns": {
            "status": "To Do",
            "parent": error_handling_id,  # Parent is Error Handling due to sub-item relation
            "date": "2025-09-20"
        },
        "Memory Management and GC Tuning": {
            "status": "In Progress",
            "parent": bridge_id,
            "date": "2025-09-25"
        },
        "Building Python C Extensions": {
            "status": "To Do",
            "date": "2025-10-01"
        }
    }

    lesson_ids = {}

    try:
        for lesson_name, expected in expert_lessons.items():
            lesson_response = notion.databases.query(
                database_id=steps_db_id,
                filter={
                    "property": "Lessons",
                    "title": {
                        "equals": lesson_name
                    }
                }
            )

            if not lesson_response.get("results"):
                print(f"Error: Lesson '{lesson_name}' not found.", file=sys.stderr)
                return False, f"Lesson '{lesson_name}' not found"

            lesson = lesson_response["results"][0]
            lesson_ids[lesson_name] = lesson["id"]

            # Check status
            status_prop = lesson["properties"]["Status"]["status"]["name"]
            if status_prop != expected["status"]:
                msg = (f"Error: Lesson '{lesson_name}' should have status "
                       f"'{expected['status']}'.")
                print(msg, file=sys.stderr)
                return False, msg

            # Check linked to Expert Level chapter
            lesson_chapters = lesson["properties"]["Chapters"]["relation"]
            if not any(rel["id"] == expert_chapter_id for rel in lesson_chapters):
                msg = (f"Error: Lesson '{lesson_name}' not linked to "
                       "Expert Level chapter.")
                print(msg, file=sys.stderr)
                return False, msg

            # Check date
            lesson_date = lesson["properties"]["Date"]["date"]
            if lesson_date and lesson_date.get("start") != expected["date"]:
                msg = (f"Error: Lesson '{lesson_name}' should have date "
                       f"'{expected['date']}'.")
                print(msg, file=sys.stderr)
                return False, msg

            # Check parent item for lessons that have specific parent
            # requirements
            if "parent" in expected:
                lesson_parent = lesson["properties"]["Parent item"]["relation"]
                if not lesson_parent or lesson_parent[0]["id"] != expected["parent"]:
                    msg = (f"Error: Lesson '{lesson_name}' should have "
                           "correct parent item.")
                    print(msg, file=sys.stderr)
                    return False, msg

            print(f"✓ Lesson '{lesson_name}' found with correct properties")

        # Special checks for Building Python C Extensions parent relationship
        # (other parent checks are handled in the loop above)
        building_lesson = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "equals": "Building Python C Extensions"
                }
            }
        )["results"][0]

        building_parent = building_lesson["properties"]["Parent item"]["relation"]
        metaprog_id = lesson_ids["Metaprogramming and AST Manipulation"]
        if not building_parent or building_parent[0]["id"] != metaprog_id:
            msg = ("Error: Building Python C Extensions should have "
                   "Metaprogramming and AST Manipulation as parent.")
            print(msg, file=sys.stderr)
            return False, msg

        # Memory Management should have 2 sub-items
        memory_lesson = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "equals": "Memory Management and GC Tuning"
                }
            }
        )["results"][0]

        memory_subitems = memory_lesson["properties"]["Sub-item"]["relation"]
        if len(memory_subitems) != 2:
            msg = ("Error: Memory Management and GC Tuning should have "
                   "exactly 2 sub-items.")
            print(msg, file=sys.stderr)
            return False, msg

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error checking expert lessons: {e}", file=sys.stderr)
        return False, f"Error checking expert lessons: {e}"

    # Step 7: Verify Error Handling has Async Concurrency Patterns as sub-item
    print("7. Checking Error Handling sub-item...")

    try:
        error_handling_response = notion.databases.query(
            database_id=steps_db_id,
            filter={
                "property": "Lessons",
                "title": {
                    "equals": "Error Handling"
                }
            }
        )

        if error_handling_response.get("results"):
            error_handling_lesson = error_handling_response["results"][0]
            error_subitems = error_handling_lesson["properties"]["Sub-item"]["relation"]

            async_patterns_id = lesson_ids["Async Concurrency Patterns"]
            if not any(item["id"] == async_patterns_id
                       for item in error_subitems):
                msg = ("Error: Error Handling should have Async Concurrency "
                       "Patterns as sub-item.")
                print(msg, file=sys.stderr)
                return False, msg

            print("✓ Error Handling has Async Concurrency Patterns as sub-item")
        else:
            print("Error: Error Handling lesson not found.", file=sys.stderr)
            return False, "Error Handling lesson not found"

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error checking Error Handling: {e}", file=sys.stderr)
        return False, f"Error checking Error Handling: {e}"

    # Step 8: Verify block content in Advanced Foundations Review
    print("8. Checking Advanced Foundations Review page content...")

    try:
        blocks = notion_utils.get_all_blocks_recursively(notion, bridge_id)

        if len(blocks) < 3:
            msg = ("Error: Advanced Foundations Review should have at least "
                   "3 blocks.")
            print(msg, file=sys.stderr)
            return False, msg

        # Check Block 1: Heading 2
        block1 = blocks[0]
        if block1.get("type") != "heading_2":
            print("Error: First block should be heading_2.", file=sys.stderr)
            return False, "First block should be heading_2"

        heading_data = block1.get("heading_2", {}).get("rich_text", [{}])
        heading_text = heading_data[0].get("text", {}).get("content", "")
        if heading_text != "Prerequisites Checklist":
            msg = "Error: Heading should be 'Prerequisites Checklist'."
            print(msg, file=sys.stderr)
            return False, msg

        # Check Block 2: Bulleted list
        block2 = blocks[1]
        if block2.get("type") != "bulleted_list_item":
            print("Error: Second block should be bulleted_list_item.", file=sys.stderr)
            return False, "Second block should be bulleted_list_item"

        # Check Block 3 and 4 are also bulleted list items
        if len(blocks) >= 4:
            block3 = blocks[2]
            block4 = blocks[3]
            block3_ok = block3.get("type") == "bulleted_list_item"
            block4_ok = block4.get("type") == "bulleted_list_item"
            if not block3_ok or not block4_ok:
                msg = "Error: Blocks 2-4 should be bulleted list items."
                print(msg, file=sys.stderr)
                return False, msg

        # Check last block is paragraph
        last_block = blocks[-1]
        if last_block.get("type") != "paragraph":
            print("Error: Last block should be paragraph.", file=sys.stderr)
            return False, "Last block should be paragraph"

        para_data = last_block.get("paragraph", {}).get("rich_text", [{}])
        paragraph_text = para_data[0].get("text", {}).get("content", "")
        if "checkpoint" not in paragraph_text.lower():
            msg = "Error: Paragraph should contain text about checkpoint."
            print(msg, file=sys.stderr)
            return False, msg

        print("✓ Advanced Foundations Review page has correct content structure")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error checking page content: {e}", file=sys.stderr)
        return False, f"Error checking page content: {e}"

    # Step 9: Final verification counts
    print("9. Verifying final state counts...")

    try:
        # Count total lessons by status
        all_lessons = notion.databases.query(database_id=steps_db_id, page_size=100)["results"]

        done_lessons = [
            l for l in all_lessons
            if l["properties"]["Status"]["status"]["name"] == "Done"
        ]
        done_count = len(done_lessons)
        in_progress_count = sum(
            1 for l in all_lessons
            if l["properties"]["Status"]["status"]["name"] == "In Progress"
        )

        # Print out all Done lessons for debugging
        if done_count != 14:
            print(f"Found {done_count} Done lessons (expected 14):", file=sys.stderr)
            for lesson in done_lessons:
                title_data = lesson["properties"]["Lessons"]["title"][0]
                lesson_name = title_data["text"]["content"]
                print(f"  - {lesson_name}", file=sys.stderr)
            return False, f"Found {done_count} Done lessons (expected 14)"

        if in_progress_count != 1:
            msg = (f"Error: Should have 1 In Progress lesson, "
                   f"found {in_progress_count}.")
            print(msg, file=sys.stderr)
            return False, msg

        # Verify Expert Level has 5 lessons
        expert_chapter_updated = notion.databases.query(
            database_id=chapters_db_id,
            filter={
                "property": "Name",
                "title": {
                    "equals": "Expert Level"
                }
            }
        )["results"][0]

        expert_steps = expert_chapter_updated["properties"]["Steps"]["relation"]
        if len(expert_steps) != 5:
            steps_count = len(expert_steps)
            msg = (f"Error: Expert Level should have exactly 5 lessons, "
                   f"found {steps_count}.")
            print(msg, file=sys.stderr)
            return False, msg

        print("✓ Final state counts are correct")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error verifying final counts: {e}", file=sys.stderr)
        return False, f"Error verifying final counts: {e}"

    print("🎉 All verification checks passed!")
    return True, ""

def main():
    """
    Main verification function.
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
