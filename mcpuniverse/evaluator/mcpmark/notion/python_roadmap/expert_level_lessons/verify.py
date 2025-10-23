import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:
    """
    Verifies that the Expert Level chapter and its lessons have been created correctly with complex prerequisites.
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
            print(f"Error: Expert Level chapter not found in Chapters database.", file=sys.stderr)
            return False, "Expert Level chapter not found in Chapters database"
        
        expert_chapter = chapters_response["results"][0]
        expert_chapter_id = expert_chapter["id"]
        
        # Check chapter icon (purple circle)
        chapter_icon = expert_chapter.get("icon")
        if not chapter_icon or chapter_icon.get("type") != "emoji" or chapter_icon.get("emoji") != "🟣":
            print(f"Error: Expert Level chapter does not have the correct purple circle emoji icon.", file=sys.stderr)
            return False, "Expert Level chapter does not have the correct purple circle emoji icon"
        
        print(f"✓ Expert Level chapter found with correct icon: 🟣")
        
    except Exception as e:
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
            print(f"✓ Found Control Flow lesson with status 'Done'")
        else:
            print(f"Error: Control Flow lesson not found with status 'Done'.", file=sys.stderr)
            return False, "Control Flow lesson not found with status 'Done'"
        
    except Exception as e:
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
                print(f"Error: Decorators lesson should have status 'Done'.", file=sys.stderr)
                return False, "Decorators lesson should have status 'Done'"
            print(f"✓ Found Decorators lesson with status 'Done'")
        else:
            print(f"Error: Decorators lesson not found.", file=sys.stderr)
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
            print(f"✓ Found Calling API lesson")
        else:
            print(f"Error: Calling API lesson not found.", file=sys.stderr)
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
            print(f"✓ Found Regular Expressions lesson")
        else:
            print(f"Error: Regular Expressions lesson not found.", file=sys.stderr)
            return False, "Regular Expressions lesson not found"
        
    except Exception as e:
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
            print(f"Error: Advanced Foundations Review lesson not found.", file=sys.stderr)
            return False, "Advanced Foundations Review lesson not found"
        
        bridge_lesson = bridge_response["results"][0]
        bridge_id = bridge_lesson["id"]
        
        # Check status is Done
        if bridge_lesson["properties"]["Status"]["status"]["name"] != "Done":
            print(f"Error: Advanced Foundations Review should have status 'Done'.", file=sys.stderr)
            return False, "Advanced Foundations Review should have status 'Done'"
        
        # Check linked to Expert Level chapter
        bridge_chapters = bridge_lesson["properties"]["Chapters"]["relation"]
        if not any(rel["id"] == expert_chapter_id for rel in bridge_chapters):
            print(f"Error: Advanced Foundations Review not linked to Expert Level chapter.", file=sys.stderr)
            return False, "Advanced Foundations Review not linked to Expert Level chapter"
        
        # Check Parent item is Control Flow
        bridge_parent = bridge_lesson["properties"]["Parent item"]["relation"]
        if not bridge_parent or bridge_parent[0]["id"] != control_flow_id:
            print(f"Error: Advanced Foundations Review should have Control Flow as Parent item.", file=sys.stderr)
            return False, "Advanced Foundations Review should have Control Flow as Parent item"
        
        # Check Sub-items (should have at least 3 specific lessons plus any that reference it as parent)
        bridge_subitems = bridge_lesson["properties"]["Sub-item"]["relation"]
        required_subitems = {decorators_id, calling_api_id, regex_id}
        actual_subitems = {item["id"] for item in bridge_subitems}
        
        if not required_subitems.issubset(actual_subitems):
            print(f"Error: Advanced Foundations Review should have at least these 3 sub-items: Decorators, Calling API, Regular Expressions.", file=sys.stderr)
            return False, "Advanced Foundations Review should have at least these 3 sub-items: Decorators, Calling API, Regular Expressions"
        
        # Due to bidirectional relations, lessons that have this as parent will also appear as sub-items
        # We expect at least 5: 3 initial + 2 that reference it as parent (Metaprogramming and Memory Management)
        if len(bridge_subitems) < 5:
            print(f"Error: Advanced Foundations Review should have at least 5 sub-items (3 initial + 2 from parent relations), found {len(bridge_subitems)}.", file=sys.stderr)
            return False, f"Advanced Foundations Review should have at least 5 sub-items (3 initial + 2 from parent relations), found {len(bridge_subitems)}"
        
        print(f"✓ Advanced Foundations Review has {len(bridge_subitems)} sub-items, including the 3 required ones")
        
        print(f"✓ Advanced Foundations Review found with correct properties")
        
    except Exception as e:
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
        print(f"Error: Error Handling lesson not found.", file=sys.stderr)
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
            if lesson["properties"]["Status"]["status"]["name"] != expected["status"]:
                print(f"Error: Lesson '{lesson_name}' should have status '{expected['status']}'.", file=sys.stderr)
                return False, f"Lesson '{lesson_name}' should have status '{expected['status']}'"
            
            # Check linked to Expert Level chapter
            lesson_chapters = lesson["properties"]["Chapters"]["relation"]
            if not any(rel["id"] == expert_chapter_id for rel in lesson_chapters):
                print(f"Error: Lesson '{lesson_name}' not linked to Expert Level chapter.", file=sys.stderr)
                return False, f"Lesson '{lesson_name}' not linked to Expert Level chapter"
            
            # Check date
            lesson_date = lesson["properties"]["Date"]["date"]
            if lesson_date and lesson_date.get("start") != expected["date"]:
                print(f"Error: Lesson '{lesson_name}' should have date '{expected['date']}'.", file=sys.stderr)
                return False, f"Lesson '{lesson_name}' should have date '{expected['date']}'"
            
            # Check parent item for lessons that have specific parent requirements
            if "parent" in expected:
                lesson_parent = lesson["properties"]["Parent item"]["relation"]
                if not lesson_parent or lesson_parent[0]["id"] != expected["parent"]:
                    print(f"Error: Lesson '{lesson_name}' should have correct parent item.", file=sys.stderr)
                    return False, f"Lesson '{lesson_name}' should have correct parent item"
            
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
        if not building_parent or building_parent[0]["id"] != lesson_ids["Metaprogramming and AST Manipulation"]:
            print(f"Error: Building Python C Extensions should have Metaprogramming and AST Manipulation as parent.", file=sys.stderr)
            return False, "Building Python C Extensions should have Metaprogramming and AST Manipulation as parent"
        
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
            print(f"Error: Memory Management and GC Tuning should have exactly 2 sub-items.", file=sys.stderr)
            return False, "Memory Management and GC Tuning should have exactly 2 sub-items"
        
    except Exception as e:
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
            
            if not any(item["id"] == lesson_ids["Async Concurrency Patterns"] for item in error_subitems):
                print(f"Error: Error Handling should have Async Concurrency Patterns as sub-item.", file=sys.stderr)
                return False, "Error Handling should have Async Concurrency Patterns as sub-item"
            
            print(f"✓ Error Handling has Async Concurrency Patterns as sub-item")
        else:
            print(f"Error: Error Handling lesson not found.", file=sys.stderr)
            return False, "Error Handling lesson not found"
        
    except Exception as e:
        print(f"Error checking Error Handling: {e}", file=sys.stderr)
        return False, f"Error checking Error Handling: {e}"
    
    # Step 8: Verify block content in Advanced Foundations Review
    print("8. Checking Advanced Foundations Review page content...")
    
    try:
        blocks = notion_utils.get_all_blocks_recursively(notion, bridge_id)
        
        if len(blocks) < 3:
            print(f"Error: Advanced Foundations Review should have at least 3 blocks.", file=sys.stderr)
            return False, "Advanced Foundations Review should have at least 3 blocks"
        
        # Check Block 1: Heading 2
        block1 = blocks[0]
        if block1.get("type") != "heading_2":
            print(f"Error: First block should be heading_2.", file=sys.stderr)
            return False, "First block should be heading_2"
        
        heading_text = block1.get("heading_2", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
        if heading_text != "Prerequisites Checklist":
            print(f"Error: Heading should be 'Prerequisites Checklist'.", file=sys.stderr)
            return False, "Heading should be 'Prerequisites Checklist'"
        
        # Check Block 2: Bulleted list
        block2 = blocks[1]
        if block2.get("type") != "bulleted_list_item":
            print(f"Error: Second block should be bulleted_list_item.", file=sys.stderr)
            return False, "Second block should be bulleted_list_item"
        
        # Check Block 3 and 4 are also bulleted list items
        if len(blocks) >= 4:
            block3 = blocks[2]
            block4 = blocks[3]
            if block3.get("type") != "bulleted_list_item" or block4.get("type") != "bulleted_list_item":
                print(f"Error: Blocks 2-4 should be bulleted list items.", file=sys.stderr)
                return False, "Blocks 2-4 should be bulleted list items"
        
        # Check last block is paragraph
        last_block = blocks[-1]
        if last_block.get("type") != "paragraph":
            print(f"Error: Last block should be paragraph.", file=sys.stderr)
            return False, "Last block should be paragraph"
        
        paragraph_text = last_block.get("paragraph", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
        if "checkpoint" not in paragraph_text.lower():
            print(f"Error: Paragraph should contain text about checkpoint.", file=sys.stderr)
            return False, "Paragraph should contain text about checkpoint"
        
        print(f"✓ Advanced Foundations Review page has correct content structure")
        
    except Exception as e:
        print(f"Error checking page content: {e}", file=sys.stderr)
        return False, f"Error checking page content: {e}"
    
    # Step 9: Final verification counts
    print("9. Verifying final state counts...")
    
    try:
        # Count total lessons by status
        all_lessons = notion.databases.query(database_id=steps_db_id, page_size=100)["results"]
        
        done_lessons = [l for l in all_lessons if l["properties"]["Status"]["status"]["name"] == "Done"]
        done_count = len(done_lessons)
        in_progress_count = sum(1 for l in all_lessons if l["properties"]["Status"]["status"]["name"] == "In Progress")
        
        # Print out all Done lessons for debugging
        if done_count != 14:
            print(f"Found {done_count} Done lessons (expected 14):", file=sys.stderr)
            for lesson in done_lessons:
                lesson_name = lesson["properties"]["Lessons"]["title"][0]["text"]["content"]
                print(f"  - {lesson_name}", file=sys.stderr)
            return False, f"Found {done_count} Done lessons (expected 14)"
        
        if in_progress_count != 1:
            print(f"Error: Should have 1 In Progress lesson, found {in_progress_count}.", file=sys.stderr)
            return False, f"Should have 1 In Progress lesson, found {in_progress_count}"
        
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
            print(f"Error: Expert Level should have exactly 5 lessons, found {len(expert_steps)}.", file=sys.stderr)
            return False, f"Expert Level should have exactly 5 lessons, found {len(expert_steps)}"
        
        print(f"✓ Final state counts are correct")
        
    except Exception as e:
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
    success, error_msg = verify(notion, main_id)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()