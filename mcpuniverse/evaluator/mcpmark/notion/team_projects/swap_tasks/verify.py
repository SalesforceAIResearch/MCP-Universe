"""Verification module for Swap Tasks task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the task assignees have been swapped correctly.
    Checks:
    1. "Develop a plan for promotion" and "Evaluate different third-party "
       "services" have swapped assignees
    2. The person with most tasks and person with least tasks have swapped
       all their tasks
    """
    # Step 1: Find the Team Projects page
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if not found_id or object_type != 'page':
            print("Error: Team Projects page not found.", file=sys.stderr)
            return False, "Team Projects page not found"
    else:
        # Try to find the page by searching
        found_id = notion_utils.find_page(notion, "Team Projects")
        if not found_id:
            print("Error: Team Projects page not found.", file=sys.stderr)
            return False, "Team Projects page not found"

    # Get all blocks from the page to find database references
    all_blocks = notion_utils.get_all_blocks_recursively(notion, found_id)

    # Find Tasks database ID from the page
    tasks_db_id = None

    for block in all_blocks:
        if block and block.get("type") == "child_database":
            db_title = block.get("child_database", {}).get("title", "")
            if "Tasks" in db_title:
                tasks_db_id = block["id"]
                break

    if not tasks_db_id:
        print("Error: Tasks database not found.", file=sys.stderr)
        return False, "Tasks database not found"

    print("\n📋 Starting verification...")

    # Step 2: Query all tasks to analyze assignees

    try:
        all_tasks_response = notion.databases.query(
            database_id=tasks_db_id,
            page_size=100
        )

        if not all_tasks_response.get("results"):
            print("Error: No tasks found in Tasks database.", file=sys.stderr)
            return False, "No tasks found in Tasks database"

        tasks = all_tasks_response["results"]

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Tasks database: {e}", file=sys.stderr)
        return False, f"Error querying Tasks database: {e}"

    # Step 3: Check specific tasks have swapped assignees

    develop_plan_task = None
    evaluate_services_task = None

    for task in tasks:
        task_name = task["properties"]["Name"]["title"][0]["text"]["content"]
        if task_name == "Develop a plan for promotion":
            develop_plan_task = task
        elif task_name == "Evaluate different third-party services":
            evaluate_services_task = task

    if not develop_plan_task or not evaluate_services_task:
        print("Error: Could not find both required tasks.", file=sys.stderr)
        return False, "Could not find both required tasks"

    # Get assignees for these tasks
    develop_plan_assignees = develop_plan_task["properties"]["Assigned"]["people"]
    evaluate_services_assignees = evaluate_services_task["properties"]["Assigned"]["people"]

    if not develop_plan_assignees or not evaluate_services_assignees:
        print("Error: Tasks don't have assignees.", file=sys.stderr)
        return False, "Tasks don't have assignees"

    develop_plan_assignee_id = develop_plan_assignees[0]["id"]
    evaluate_services_assignee_id = evaluate_services_assignees[0]["id"]

    # These should be different (swapped)
    if develop_plan_assignee_id == evaluate_services_assignee_id:
        print("Error: Tasks should have different assignees after swap.", file=sys.stderr)
        return False, "Tasks should have different assignees after swap"

    # Step 4: Count tasks per person

    task_counts = {}
    unassigned_count = 0

    for task in tasks:
        assignees = task["properties"]["Assigned"]["people"]
        if assignees:
            assignee_id = assignees[0]["id"]
            if assignee_id not in task_counts:
                task_counts[assignee_id] = []
            task_name = task["properties"]["Name"]["title"][0]["text"]["content"]
            task_counts[assignee_id].append(task_name)
        else:
            unassigned_count += 1

    # Sort by task count
    sorted_assignees = sorted(task_counts.items(), key=lambda x: len(x[1]))

    if len(sorted_assignees) < 2:
        print("Error: Need at least 2 people with tasks to verify swap.", file=sys.stderr)
        return False, "Need at least 2 people with tasks to verify swap"

    # Get person with least and most tasks
    person_with_least = sorted_assignees[0]
    person_with_most = sorted_assignees[-1]

    _least_id, least_tasks = person_with_least
    _most_id, most_tasks = person_with_most

    # Step 5: Verify the swap pattern

    # Original distribution (before swap):
    # - 5ac96c02-49a4-4320-8de6-b663ba83126b had 3 tasks (least)
    # - ac7a3bd0-c111-4464-8f45-8a857a1abc8a had 10 tasks (most)

    # After complete swap, we expect:
    # - 5ac96c02-49a4-4320-8de6-b663ba83126b should have 10 tasks
    # - ac7a3bd0-c111-4464-8f45-8a857a1abc8a should have 3 tasks

    original_least_id = "5ac96c02-49a4-4320-8de6-b663ba83126b"
    original_most_id = "ac7a3bd0-c111-4464-8f45-8a857a1abc8a"

    # Check if the swap has been completed
    swap_completed = False
    for assignee_id, assignee_tasks in task_counts.items():
        if assignee_id == original_least_id and len(assignee_tasks) == 10:
            # Person who had 3 now has 10
            for other_id, other_tasks in task_counts.items():
                if other_id == original_most_id and len(other_tasks) == 3:
                    # Person who had 10 now has 3
                    swap_completed = True
                    break

    # Step 6: Summary
    print("\n📊 Task Distribution:")
    print(f"  • Total tasks: {len(tasks)}")
    print(f"  • Assigned tasks: {len(tasks) - unassigned_count}")
    print(f"  • Unassigned tasks: {unassigned_count}")
    print(f"  • People with tasks: {len(task_counts)}")
    print("\n  Task counts by person:")
    for assignee_id, assignee_tasks in sorted_assignees:
        print(f"    - {assignee_id[:8]}...: {len(assignee_tasks)} tasks")

    # Step 7: Final verification
    print("\n🔍 Verification Results:")

    # Check that the swap has created a significant difference
    if len(most_tasks) - len(least_tasks) < 5:
        diff = len(most_tasks) - len(least_tasks)
        msg = (f"Warning: Difference between most and least is only "
               f"{diff} tasks")
        print(msg, file=sys.stderr)

    # Verify specific expected outcomes
    verification_passed = True

    # Check 1: Specific tasks have been swapped
    specific_tasks_swapped = develop_plan_assignee_id != evaluate_services_assignee_id
    if specific_tasks_swapped:
        print("  ✓ Specific tasks have been swapped")
    else:
        print("  ✗ Specific tasks were not swapped", file=sys.stderr)
        verification_passed = False

    # Check 2: Task distribution shows a complete swap
    if swap_completed:
        print("  ✓ Complete task swap verified (3↔10 tasks)")
    else:
        # Show actual distribution for debugging
        person1_tasks = len(task_counts.get(original_least_id, []))
        person2_tasks = len(task_counts.get(original_most_id, []))
        msg1 = ("  ✗ Swap incomplete! Expected 5ac96c02→10 tasks, "
                "ac7a3bd0→3 tasks")
        print(msg1, file=sys.stderr)
        msg2 = (f"    Actual: 5ac96c02→{person1_tasks} tasks, "
                f"ac7a3bd0→{person2_tasks} tasks")
        print(msg2, file=sys.stderr)
        verification_passed = False

    # Check 3: Total task count is preserved
    total_assigned_tasks = sum(len(tasks) for _, tasks in task_counts.items())
    expected_total = len(tasks) - unassigned_count

    if total_assigned_tasks == expected_total:
        print(f"  ✓ Total task count preserved ({total_assigned_tasks} assigned)")
    else:
        msg = (f"  ✗ Task count mismatch: {total_assigned_tasks} vs "
               f"{expected_total} expected")
        print(msg, file=sys.stderr)
        verification_passed = False

    if verification_passed:
        print("\n✅ All verification checks passed!")
        return True, ""
    print("\n❌ Verification failed", file=sys.stderr)
    return False, "Verification failed"

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
