"""Verification module for Hyperfocus Analysis Report task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from collections import Counter
import re

from notion_client import Client

from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def validate_comma_separated(text: str, expected_items: list) -> bool:
    """
    Validates that a comma-separated list contains expected items (case-insensitive).
    """
    if not text or not expected_items:
        return False

    # Extract items from text
    items = [item.strip().lower() for item in text.split(",")]
    expected_lower = [item.lower() for item in expected_items]

    # Check if all expected items are present
    for expected in expected_lower:
        if not any(expected in item or item in expected for item in items):
            return False
    return True


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the Hyperfocus Analysis Report has been created correctly.
    """
    # Find the Self Assessment page
    self_assessment_page_id = main_id
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            self_assessment_page_id = found_id

    if not self_assessment_page_id:
        # Try to find by name
        self_assessment_page_id = notion_utils.find_page(notion, "Self Assessment")

    if not self_assessment_page_id:
        print("Error: Self Assessment page not found.", file=sys.stderr)
        return False, "Error: Self Assessment page not found."

    # Find the Hyperfocus Analysis Report page
    report_page_id = None
    report_position = -1
    callout_position = -1
    divider_position = -1
    children = notion.blocks.children.list(block_id=self_assessment_page_id).get(
        "results", []
    )
    for i, child in enumerate(children):
        # Track position of callout with "Why Use the Term"
        if child.get("type") == "callout":
            callout_text = notion_utils.get_block_plain_text(child)
            if "Why Use the Term" in callout_text and "Hyperfocus" in callout_text:
                callout_position = i

        # Track position of divider
        elif child.get("type") == "divider":
            if callout_position != -1 and divider_position == -1:
                divider_position = i

        # Find the report page
        elif child.get("type") == "child_page":
            page_data = notion.pages.retrieve(page_id=child["id"])
            title_prop = (
                page_data.get("properties", {}).get("title", {}).get("title", [])
            )
            if (
                title_prop
                and title_prop[0].get("plain_text") == "Hyperfocus Analysis Report"
            ):
                report_page_id = child["id"]
                report_position = i

    if not report_page_id:
        print("Error: 'Hyperfocus Analysis Report' page not found.", file=sys.stderr)
        return False, "Error: 'Hyperfocus Analysis Report' page not found."

    # Verify position
    if callout_position == -1:
        print(
            "Error: Could not find 'Why Use the Term \"Hyperfocus\"?' callout.",
            file=sys.stderr,
        )
        return False, "Error: Could not find 'Why Use the Term \"Hyperfocus\"?' callout."

    if divider_position == -1:
        print("Error: Could not find divider after the callout.", file=sys.stderr)
        return False, "Error: Could not find divider after the callout."

    if not callout_position < report_position < divider_position:
        msg = (f"Error: Report page is not positioned between callout and "
               f"divider. Positions: callout={callout_position}, "
               f"report={report_position}, divider={divider_position}")
        print(msg, file=sys.stderr)
        return False, msg

    # Get all blocks from the report page
    all_blocks = notion_utils.get_all_blocks_recursively(notion, report_page_id)

    # Find the database in the Self Assessment page
    database_id = None
    for block in notion_utils.get_all_blocks_recursively(
        notion, self_assessment_page_id
    ):
        if block.get("type") == "child_database":
            db_data = notion.databases.retrieve(database_id=block["id"])
            db_title = "".join(
                [t.get("plain_text", "") for t in db_data.get("title", [])]
            )
            if "Hyperfocus Self-Assessment Worksheet" in db_title:
                database_id = block["id"]
                break

    if not database_id:
        print(
            "Error: Database 'Hyperfocus Self-Assessment Worksheet' not found.",
            file=sys.stderr,
        )
        return False, "Error: Database 'Hyperfocus Self-Assessment Worksheet' not found."

    # Query database for sessions with >80% completion rate and challenges
    query_results = notion.databases.query(
        database_id=database_id,
        filter={
            "and": [
                {"property": "Work Completion Rate", "number": {"greater_than": 0.8}},
                {"property": "Challenges", "multi_select": {"is_not_empty": True}},
            ]
        },
    ).get("results", [])

    if not query_results:
        print(
            "Warning: No sessions found with >80% completion rate and challenges.",
            file=sys.stderr,
        )
        # Still check if the page structure is correct

    # Verify page structure
    has_callout = False
    has_top_strategies = False
    session_count = 0
    found_sessions = {}  # Track sessions by date for validation

    # Track strategies for validation - count from ALL sessions
    all_sessions = notion.databases.query(database_id=database_id).get("results", [])
    all_strategies = []
    for session in all_sessions:
        strategies = (
            session.get("properties", {})
            .get("Key Strategies Used", {})
            .get("multi_select", [])
        )
        all_strategies.extend([s.get("name") for s in strategies])

    strategy_counts = Counter(all_strategies)
    top_2_strategies = strategy_counts.most_common(2)

    # Build expected sessions from query results with all data
    expected_sessions = {}
    for result in query_results:
        date_prop = result.get("properties", {}).get("Date", {}).get("date", {})
        activity_prop = (
            result.get("properties", {}).get("Activity", {}).get("select", {})
        )
        if date_prop and date_prop.get("start") and activity_prop:
            date_str = date_prop["start"]
            activity_name = activity_prop.get("name", "")

            # Extract all session data for validation
            focus_factors = [
                f.get("name", "")
                for f in result.get("properties", {})
                .get("Focus Factors", {})
                .get("multi_select", [])
            ]
            challenges = [
                c.get("name", "")
                for c in result.get("properties", {})
                .get("Challenges", {})
                .get("multi_select", [])
            ]
            strategies = [
                s.get("name", "")
                for s in result.get("properties", {})
                .get("Key Strategies Used", {})
                .get("multi_select", [])
            ]
            energy = result.get("properties", {}).get("Energy Level", {}).get("number")
            mood = result.get("properties", {}).get("Mood", {}).get("number")
            completion = (
                result.get("properties", {})
                .get("Work Completion Rate", {})
                .get("number")
            )

            expected_sessions[date_str] = {
                "activity": activity_name,
                "focus_factors": focus_factors,
                "challenges": challenges,
                "strategies": strategies,
                "energy": energy,
                "mood": mood,
                "completion": completion,
            }

    current_session_date = None
    current_session_data = None
    session_bullet_points = {}  # Track bullet points for each session

    for i, block in enumerate(all_blocks):
        block_type = block.get("type")

        # Check for callout at the top
        if block_type == "callout" and i < 5:  # Should be near the top
            callout_text = notion_utils.get_block_plain_text(block)
            if "Top 2 Most Effective Strategies" in callout_text:
                has_callout = True
                # Check if it contains strategy information
                s1, n1 = top_2_strategies[0]
                s2, n2 = top_2_strategies[1]
                t1 = f"{s1} (used in {n1} sessions)"
                t2 = f"{s2} (used in {n2} sessions)"

                if t1 in callout_text and t2 in callout_text:
                    has_top_strategies = True
                    break

        # Check for session headings with format YYYY-MM-DD Activity
        if block_type == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            # Check if heading matches expected format
            for date_str, session_data in expected_sessions.items():
                activity = session_data["activity"]
                expected_heading = f"{date_str} {activity}"
                if expected_heading in heading_text:
                    found_sessions[date_str] = session_data
                    session_count += 1
                    current_session_date = date_str
                    current_session_data = session_data
                    session_bullet_points[date_str] = []
                    break

        # Check for bullet points with session details
        if block_type == "bulleted_list_item" and current_session_data:
            bullet_text = notion_utils.get_block_plain_text(block)

            # Track bullet points for current session
            if current_session_date:
                session_bullet_points[current_session_date].append(bullet_text)

            # Validate specific bullet point content
            if bullet_text.startswith("Focus factors"):
                content = bullet_text.split(":", 1)[1].strip()
                expected_factors = current_session_data.get("focus_factors", [])
                if not validate_comma_separated(content, expected_factors):
                    msg = (f"Error: Focus factors mismatch for "
                           f"{current_session_date}. Expected: "
                           f"{expected_factors}, Found: {content}")
                    print(msg, file=sys.stderr)
                    return False, msg

            elif "Energy" in bullet_text and "Mood" in bullet_text:
                # Extract energy and mood values
                energy_match = re.search(r"Energy:\s*(\d+)/10", bullet_text)
                mood_match = re.search(r"Mood:\s*(\d+)/10", bullet_text)

                if energy_match and mood_match:
                    found_energy = int(energy_match.group(1))
                    found_mood = int(mood_match.group(1))
                    expected_energy = current_session_data.get("energy")
                    expected_mood = current_session_data.get("mood")

                    if found_energy != expected_energy or found_mood != expected_mood:
                        msg = (f"Error: Energy/Mood mismatch for "
                               f"{current_session_date}. Expected: Energy: "
                               f"{expected_energy}/10, Mood: {expected_mood}/10")
                        print(msg, file=sys.stderr)
                        return False, msg
                else:
                    print(
                        f"Error: Invalid Energy/Mood format for {current_session_date}",
                        file=sys.stderr,
                    )
                    return False, f"Error: Invalid Energy/Mood format for {current_session_date}"

            elif bullet_text.startswith("Challenges"):
                content = bullet_text.split(":", 1)[1].strip()
                expected_challenges = current_session_data.get("challenges", [])
                if not validate_comma_separated(content, expected_challenges):
                    msg = (f"Error: Challenges mismatch for "
                           f"{current_session_date}. Expected: "
                           f"{expected_challenges}, Found: {content}")
                    print(msg, file=sys.stderr)
                    return False, msg

            elif bullet_text.startswith("Strategies"):
                content = bullet_text.split(":", 1)[1].strip()
                expected_strategies = current_session_data.get("strategies", [])
                if len(expected_strategies) > 0 and not validate_comma_separated(
                    content, expected_strategies
                ):
                    msg = (f"Error: Strategies mismatch for "
                           f"{current_session_date}. Expected: "
                           f"{expected_strategies}, Found: {content}")
                    print(msg, file=sys.stderr)
                    return False, msg

            elif bullet_text.startswith("Completion"):
                # Extract completion percentage
                completion_match = re.search(r"Completion:\s*(\d+)%", bullet_text)

                if completion_match:
                    found_completion = int(completion_match.group(1))
                    expected_completion = int(
                        current_session_data.get("completion", 0) * 100
                    )

                    if found_completion != expected_completion:
                        msg = (f"Error: Completion rate mismatch for "
                               f"{current_session_date}. Expected: "
                               f"{expected_completion}%, Found: "
                               f"{found_completion}%")
                        print(msg, file=sys.stderr)
                        return False, msg
                else:
                    print(
                        f"Error: Invalid completion format for {current_session_date}",
                        file=sys.stderr,
                    )
                    return False, f"Error: Invalid completion format for {current_session_date}"

    # Verify all sessions have complete bullet points
    for date_str, bullets in session_bullet_points.items():
        bullets_text = " ".join(bullets)
        required_items = [
            "Focus factors",
            "Energy:",
            "Mood:",
            "Challenges",
            "Strategies",
            "Completion",
        ]
        missing_items = []

        for item in required_items:
            if item not in bullets_text:
                missing_items.append(item)

        if missing_items:
            missing_str = ', '.join(missing_items)
            msg = (f"Error: Missing bullet points for session {date_str}: "
                   f"{missing_str}")
            print(msg, file=sys.stderr)
            return False, msg

    # Verify all requirements
    if not has_callout:
        print(
            "Error: Missing callout block with 'Top 2 Most Effective Strategies'.",
            file=sys.stderr,
        )
        return False, "Error: Missing callout block with 'Top 2 Most Effective Strategies'."

    if not has_top_strategies and len(top_2_strategies) > 0:
        print("Error: Callout doesn't contain strategy information.", file=sys.stderr)
        return False, "Error: Callout doesn't contain strategy information."

    if query_results and session_count == 0:
        print("Error: No session sections found with proper headings.", file=sys.stderr)
        return False, "Error: No session sections found with proper headings."

    # Check if all expected sessions are present
    missing_sessions = []
    for date_str in expected_sessions:
        if date_str not in found_sessions:
            missing_sessions.append(date_str)

    if missing_sessions:
        print(
            f"Error: Missing session sections for dates: {', '.join(missing_sessions)}",
            file=sys.stderr,
        )
        return False, f"Error: Missing session sections for dates: {', '.join(missing_sessions)}"

    if query_results and session_count < len(query_results):
        print(
            f"Warning: Found {session_count} session sections but expected {len(query_results)}.",
            file=sys.stderr,
        )

    print(
        "Success: Hyperfocus Analysis Report created with proper structure and content."
    )
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
