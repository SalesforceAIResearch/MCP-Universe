"""Verification module for Learning Metrics Dashboard task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def get_page_title_from_result(page_result):
    """
    Extract the title from a page result object from database query.
    """
    properties = page_result.get('properties', {})
    # Try common title property names
    for prop_name in ['Name', 'Title', 'title', 'Lessons']:
        if prop_name in properties:
            prop = properties[prop_name]
            if prop.get('type') == 'title':
                title_array = prop.get('title', [])
                if title_array and len(title_array) > 0:
                    return title_array[0].get('plain_text', '')
    return ''

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """
    Verifies that the Learning Metrics Dashboard has been implemented
    correctly according to description.md.
    """
    # Step 1: Find the main page and get all blocks
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

    # Get Steps database to calculate expected statistics
    steps_db_id = notion_utils.find_database(notion, "Steps")
    if not steps_db_id:
        print("Error: Steps database not found.", file=sys.stderr)
        return False, "Steps database not found"

    # Query Steps database to get all lessons
    steps_data = notion.databases.query(database_id=steps_db_id)
    total_lessons = len(steps_data['results'])
    completed_count = 0
    in_progress_count = 0
    completed_lessons = []

    # Get Chapters database for level information
    chapters_db_id = notion_utils.find_database(notion, "Chapters")
    if not chapters_db_id:
        print("Error: Chapters database not found.", file=sys.stderr)
        return False, "Chapters database not found"

    # Query Chapters database to get level information
    chapters_data = notion.databases.query(database_id=chapters_db_id)
    level_ids = {
        'Beginner Level': None,
        'Intermediate Level': None,
        'Advanced Level': None
    }

    for chapter in chapters_data['results']:
        chapter_name = get_page_title_from_result(chapter)
        if chapter_name in level_ids:
            level_ids[chapter_name] = chapter['id']

    # Initialize level counts
    level_counts = {
        'Beginner Level': {'total': 0, 'completed': 0},
        'Intermediate Level': {'total': 0, 'completed': 0},
        'Advanced Level': {'total': 0, 'completed': 0}
    }

    # Count lessons by status and level
    for lesson in steps_data['results']:
        status = lesson['properties']['Status']['status']
        if status and status['name'] == 'Done':
            completed_count += 1
            lesson_title = get_page_title_from_result(lesson)
            if lesson_title:
                completed_lessons.append(lesson_title)
        elif status and status['name'] == 'In Progress':
            in_progress_count += 1

        # Count by level
        chapters_relation = lesson['properties']['Chapters']['relation']
        for chapter_ref in chapters_relation:
            chapter_id = chapter_ref['id']
            for level_name, level_id in level_ids.items():
                if chapter_id == level_id:
                    level_counts[level_name]['total'] += 1
                    if status and status['name'] == 'Done':
                        level_counts[level_name]['completed'] += 1

    # Calculate percentages
    completed_percentage = (round((completed_count / total_lessons * 100), 1)
                            if total_lessons > 0 else 0)
    in_progress_percentage = (round((in_progress_count / total_lessons * 100), 1)
                              if total_lessons > 0 else 0)

    print("Expected statistics:")
    print(f"  Total Lessons: {total_lessons}")
    print(f"  Completed: {completed_count} ({completed_percentage}%)")
    print(f"  In Progress: {in_progress_count} ({in_progress_percentage}%)")
    beginner_total = level_counts['Beginner Level']['total']
    beginner_completed = level_counts['Beginner Level']['completed']
    print(f"  Beginner Level: {beginner_total} lessons "
          f"({beginner_completed} completed)")
    intermediate_total = level_counts['Intermediate Level']['total']
    intermediate_completed = level_counts['Intermediate Level']['completed']
    print(f"  Intermediate Level: {intermediate_total} lessons "
          f"({intermediate_completed} completed)")
    advanced_total = level_counts['Advanced Level']['total']
    advanced_completed = level_counts['Advanced Level']['completed']
    print(f"  Advanced Level: {advanced_total} lessons "
          f"({advanced_completed} completed)")
    print(f"  Completed lessons (first 5): {completed_lessons[:5]}")

    # Get all blocks from the page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, found_id)
    print(f"Found {len(all_blocks)} blocks")

    # Step 2: Verify the required elements in order
    learning_materials_idx = -1
    dashboard_heading_idx = -1
    callout_idx = -1
    toggle_idx = -1
    whether_paragraph_idx = -1  # Track the "Whether you're starting from scratch" paragraph

    # Track what we've verified
    callout_has_brown_bg = False
    callout_has_no_icon = False
    callout_has_course_statistics_title = False
    callout_title_has_correct_colors = False
    statistics_items_found = []
    completed_topics_found = []

    # Expected statistics content
    expected_statistics = [
        f"Total Lessons: {total_lessons}",
        f"Completed: {completed_count} ({completed_percentage}%)",
        f"In Progress: {in_progress_count} ({in_progress_percentage}%)",
        (f"Beginner Level: {beginner_total} lessons "
         f"({beginner_completed} completed)"),
        (f"Intermediate Level: {intermediate_total} lessons "
         f"({intermediate_completed} completed)"),
        (f"Advanced Level: {advanced_total} lessons "
         f"({advanced_completed} completed)")
    ]

    # Check blocks in order
    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block is None:
            continue

        block_type = block.get("type")

        # 1. Check for Learning Materials heading (requirement 1)
        if learning_materials_idx == -1 and block_type == "heading_3":
            block_text = notion_utils.get_block_plain_text(block)
            if "🎓 Learning Materials" in block_text or "Learning Materials" in block_text:
                learning_materials_idx = i
                print(f"✓ Requirement 1: Found Learning Materials heading at position {i}")

        # 2. Check for Learning Metrics Dashboard heading after
        #    Learning Materials (requirement 2)
        elif (learning_materials_idx != -1 and dashboard_heading_idx == -1
              and block_type == "heading_3"):
            block_text = notion_utils.get_block_plain_text(block)
            if "📊 Learning Metrics Dashboard" in block_text:
                dashboard_heading_idx = i
                print(f"✓ Requirement 2: Found Learning Metrics Dashboard heading at position {i}")

        # 3. Check for callout block after Dashboard heading (requirement 3)
        elif dashboard_heading_idx != -1 and callout_idx == -1 and block_type == "callout":
            callout_idx = i
            print(f"  Found callout block at position {i}")

            # Check brown background (requirement 3.1)
            if block.get("callout", {}).get("color") == "brown_background":
                callout_has_brown_bg = True
                print("  ✓ Requirement 3.1: Callout has brown background")

            # Check no icon (requirement 3.2)
            icon = block.get("callout", {}).get("icon")
            if icon is None:
                callout_has_no_icon = True
                print("  ✓ Requirement 3.2: Callout has no icon")

            # Get nested blocks for Course Statistics title and content
            nested_blocks = notion_utils.get_all_blocks_recursively(notion, block.get("id"))

            for nested in nested_blocks:
                # Check for heading_3 only as per requirement
                if nested and nested.get("type") == "heading_3":
                    # Check for "Course Statistics" title with correct formatting
                    rich_text = nested.get("heading_3", {}).get("rich_text", [])
                    course_found = False
                    course_correct = False
                    statistics_found = False
                    statistics_correct = False

                    for text_item in rich_text:
                        text_content = text_item.get("text", {}).get("content", "")
                        annotations = text_item.get("annotations", {})
                        color = annotations.get("color", "default")
                        is_bold = annotations.get("bold", False)

                        if "Course" in text_content:
                            course_found = True
                            # Check if Course is blue and bold
                            if color == "blue" and is_bold:
                                course_correct = True
                                print("  ✓ 'Course' has blue color and is bold")
                            else:
                                msg = (f"  ✗ 'Course' color: {color}, "
                                       f"bold: {is_bold} "
                                       "(should be blue and bold)")
                                print(msg)

                        if "Statistics" in text_content:
                            statistics_found = True
                            # Check if Statistics is yellow and bold
                            if color == "yellow" and is_bold:
                                statistics_correct = True
                                print("  ✓ 'Statistics' has yellow color and is bold")
                            else:
                                msg = (f"  ✗ 'Statistics' color: {color}, "
                                       f"bold: {is_bold} "
                                       "(should be yellow and bold)")
                                print(msg)

                    if course_found and statistics_found:
                        callout_has_course_statistics_title = True
                        if course_correct and statistics_correct:
                            callout_title_has_correct_colors = True
                            msg = ("  ✓ Requirement 3.3: Callout has "
                                   "'Course Statistics' title with "
                                   "correct colors")
                            print(msg)
                        else:
                            msg = ("  ✗ Requirement 3.3: Title found but "
                                   "colors/formatting incorrect")
                            print(msg)

                # Check for statistics items in bulleted list
                elif nested and nested.get("type") == "bulleted_list_item":
                    item_text = notion_utils.get_block_plain_text(nested)
                    for expected_item in expected_statistics:
                        if expected_item in item_text:
                            if expected_item not in statistics_items_found:
                                statistics_items_found.append(expected_item)
                                msg = (f"  ✓ Requirement 3.4: Found "
                                       f"statistics item: {expected_item}")
                                print(msg)

        # 4. Check for Completed Topics toggle after callout (requirement 4)
        elif callout_idx != -1 and toggle_idx == -1 and block_type == "toggle":
            block_text = notion_utils.get_block_plain_text(block)
            if "🏆 Completed Topics (Click to expand)" in block_text:
                toggle_idx = i
                print(f"✓ Requirement 4: Found Completed Topics toggle at position {i}")

                # Get nested blocks for completed topics list
                nested_blocks = notion_utils.get_all_blocks_recursively(notion, block.get("id"))
                for nested in nested_blocks:
                    if nested and nested.get("type") == "numbered_list_item":
                        item_text = notion_utils.get_block_plain_text(nested)
                        if item_text and item_text in completed_lessons:
                            completed_topics_found.append(item_text)
                            print(f"  ✓ Requirement 4.1: Found completed topic: {item_text}")

        # 5. Check for "Whether you're starting from scratch" paragraph
        #    (should be after dashboard content)
        elif block_type == "paragraph" and whether_paragraph_idx == -1:
            block_text = notion_utils.get_block_plain_text(block)
            scratch_text = "Whether you're starting from scratch"
            if scratch_text in block_text:
                whether_paragraph_idx = i
                print(f"  Found 'Whether you're starting from scratch' paragraph at position {i}")

    # Step 3: Verify all requirements were met
    print("\nVerification Summary:")

    all_passed = True

    # Requirement 1: Learning Materials section found
    if learning_materials_idx == -1:
        print("✗ Requirement 1: Learning Materials section NOT found", file=sys.stderr)
        all_passed = False
    else:
        print("✓ Requirement 1: Learning Materials section found")

    # Requirement 2: Learning Metrics Dashboard heading after
    # Learning Materials and before "Whether..." paragraph
    if dashboard_heading_idx == -1:
        msg = ("✗ Requirement 2: Learning Metrics Dashboard heading "
               "NOT found")
        print(msg, file=sys.stderr)
        all_passed = False
    elif dashboard_heading_idx <= learning_materials_idx:
        msg = ("✗ Requirement 2: Learning Metrics Dashboard heading not "
               "AFTER Learning Materials")
        print(msg, file=sys.stderr)
        all_passed = False
    elif whether_paragraph_idx != -1 and dashboard_heading_idx >= whether_paragraph_idx:
        msg = ("✗ Requirement 2: Learning Metrics Dashboard heading not "
               "BEFORE 'Whether you're starting from scratch' paragraph")
        print(msg, file=sys.stderr)
        all_passed = False
    else:
        msg = ("✓ Requirement 2: Learning Metrics Dashboard heading found "
               "after Learning Materials")
        print(msg)
        if whether_paragraph_idx != -1:
            msg2 = ("  ✓ Dashboard content is correctly placed before "
                    "'Whether you're starting from scratch' paragraph")
            print(msg2)

    # Requirement 3: Course Statistics callout block with all specifications
    if callout_idx == -1:
        print("✗ Requirement 3: Course Statistics callout block NOT found", file=sys.stderr)
        all_passed = False
    else:
        if not callout_has_brown_bg:
            print("✗ Requirement 3.1: Callout does NOT have brown background", file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 3.1: Callout has brown background")

        if not callout_has_no_icon:
            print("✗ Requirement 3.2: Callout has an icon (should have none)", file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 3.2: Callout has no icon")

        if not callout_has_course_statistics_title:
            msg = ("✗ Requirement 3.3: Callout does NOT have "
                   "'Course Statistics' title")
            print(msg, file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 3.3: Callout has 'Course Statistics' title")

        if not callout_title_has_correct_colors:
            msg = ("✗ Requirement 3.3.1: Title does NOT have correct colors "
                   "(blue for Course, yellow for Statistics)")
            print(msg, file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 3.3.1: Title has correct colors")

        # Check all statistics items
        missing_items = [item for item in expected_statistics if item not in statistics_items_found]
        if missing_items:
            print(f"✗ Requirement 3.4: Missing statistics items: {missing_items}", file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 3.4: All 6 statistics items found")

    # Requirement 4: Completed Topics toggle
    if toggle_idx == -1:
        print("✗ Requirement 4: Completed Topics toggle NOT found", file=sys.stderr)
        all_passed = False
    elif toggle_idx <= callout_idx:
        print("✗ Requirement 4: Completed Topics toggle not AFTER callout", file=sys.stderr)
        all_passed = False
    else:
        print("✓ Requirement 4: Completed Topics toggle found after callout")

        # Check that exactly 5 completed topics are listed
        if len(completed_topics_found) != 5:
            found_count = len(completed_topics_found)
            if found_count < 5:
                msg = (f"✗ Requirement 4.1: Only {found_count} completed "
                       "topics found (need exactly 5)")
                print(msg, file=sys.stderr)
            else:
                msg = (f"✗ Requirement 4.1: Found {found_count} completed "
                       "topics (need exactly 5, not more)")
                print(msg, file=sys.stderr)
            all_passed = False
        else:
            print("✓ Requirement 4.1: Found exactly 5 completed topics as required")

    # Requirement 5: Proper integration (implicitly checked by order)
    if all_passed:
        print("✓ Requirement 5: All content properly integrated in correct order")

    return all_passed, ""

def main():
    """
    Main verification function.
    """
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None
    success, _error_msg = verify(notion, main_id)
    if success:
        print("Verification passed")
        sys.exit(0)
    else:
        print("Verification failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
