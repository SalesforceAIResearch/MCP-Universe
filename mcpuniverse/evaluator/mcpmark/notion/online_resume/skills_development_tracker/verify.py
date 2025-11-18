"""Verification module for Skills Development Tracker task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the Skills Development Tracker database and callout block were created correctly.
    """
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        page_id = notion_utils.find_page(notion, "New Online Resume")
    if not page_id:
        print("Error: Page 'New Online Resume' not found.", file=sys.stderr)
        return False, "Error: Page 'New Online Resume' not found."

    # Step 1: Verify Skills Development Tracker database exists
    tracker_db_id = notion_utils.find_database_in_block(
        notion, page_id, "Skills Development Tracker"
    )
    if not tracker_db_id:
        print(
            "Error: Database 'Skills Development Tracker' not found.", file=sys.stderr
        )
        return False, "Error: Database 'Skills Development Tracker' not found."

    # Step 2: Verify database schema
    try:
        db_info = notion.databases.retrieve(database_id=tracker_db_id)
        properties = db_info.get("properties", {})

        # Check required properties
        required_props = {
            "Name": "title",
            "Current Skill": "relation",
            "Current Proficiency": "rollup",
            "Target Proficiency": "number",
            "Gap": "formula",
            "Learning Resources": "rich_text",
            "Progress Notes": "rich_text",
        }

        for prop_name, expected_type in required_props.items():
            if prop_name not in properties:
                print(
                    f"Error: Property '{prop_name}' not found in database.",
                    file=sys.stderr,
                )
                return False, f"Error: Property '{prop_name}' not found in database."
            if properties[prop_name]["type"] != expected_type:
                found_type = properties[prop_name]['type']
                msg = (f"Error: Property '{prop_name}' has incorrect type. "
                       f"Expected '{expected_type}', got '{found_type}'.")
                print(msg, file=sys.stderr)
                return False, msg

        # Verify Target Proficiency is percent format
        if (
            properties["Target Proficiency"].get("number", {}).get("format")
            != "percent"
        ):
            print(
                "Error: Target Proficiency should have 'percent' format.",
                file=sys.stderr,
            )
            return False, "Error: Target Proficiency should have 'percent' format."

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error retrieving database info: {e}", file=sys.stderr)
        return False, f"Error retrieving database info: {e}"

    # Step 3: Get Skills database to check entries
    skills_db_id = notion_utils.find_database_in_block(notion, page_id, "Skills")
    if not skills_db_id:
        print("Error: Skills database not found.", file=sys.stderr)
        return False, "Error: Skills database not found."

    # Get all skills with proficiency < 70%
    skills_below_70 = []
    try:
        skills_results = notion.databases.query(database_id=skills_db_id).get(
            "results", []
        )
        for skill in skills_results:
            skill_level = (
                skill.get("properties", {}).get("Skill Level", {}).get("number", 1.0)
            )
            if skill_level < 0.7:
                skill_name = (
                    skill.get("properties", {}).get("Skill", {}).get("title", [])
                )
                if skill_name:
                    skill_name_text = skill_name[0].get("text", {}).get("content", "")
                    skills_below_70.append(
                        {
                            "name": skill_name_text,
                            "id": skill["id"],
                            "level": skill_level,
                        }
                    )
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Skills database: {e}", file=sys.stderr)
        return False, f"Error querying Skills database: {e}"

    if not skills_below_70:
        print("Warning: No skills found with proficiency below 70%.", file=sys.stderr)
        # This might be OK if all skills are above 70%

    # Step 4: Verify entries in Skills Development Tracker
    try:
        tracker_results = notion.databases.query(database_id=tracker_db_id).get(
            "results", []
        )

        # Check that we have entries for skills below 70%
        if len(skills_below_70) > 0 and len(tracker_results) == 0:
            print(
                "Error: No entries found in Skills Development Tracker database.",
                file=sys.stderr,
            )
            return False, "Error: No entries found in Skills Development Tracker database."

        # Verify each entry
        for entry in tracker_results:
            props = entry.get("properties", {})

            # Check name format
            name_prop = props.get("Name", {}).get("title", [])
            if not name_prop:
                print("Error: Entry missing Name property.", file=sys.stderr)
                return False, "Error: Entry missing Name property."
            name_text = name_prop[0].get("text", {}).get("content", "")
            if not name_text.endswith(" Development Plan"):
                print(
                    f"Error: Entry name '{name_text}' doesn't follow expected format.",
                    file=sys.stderr,
                )
                return False, f"Error: Entry name '{name_text}' doesn't follow expected format."

            # Check relation to Skills database
            skill_relation = props.get("Current Skill", {}).get("relation", [])
            if not skill_relation:
                print(
                    f"Error: Entry '{name_text}' missing Current Skill relation.",
                    file=sys.stderr,
                )
                return False, f"Error: Entry '{name_text}' missing Current Skill relation."

            # Check Target Proficiency (should be set)
            target_prof = props.get("Target Proficiency", {}).get("number")
            if target_prof is None:
                print(
                    f"Error: Entry '{name_text}' missing Target Proficiency.",
                    file=sys.stderr,
                )
                return False, f"Error: Entry '{name_text}' missing Target Proficiency."

            # Check Learning Resources
            learning_resources = props.get("Learning Resources", {}).get(
                "rich_text", []
            )
            if not learning_resources:
                print(
                    f"Error: Entry '{name_text}' missing Learning Resources.",
                    file=sys.stderr,
                )
                return False, f"Error: Entry '{name_text}' missing Learning Resources."

            # Check Progress Notes
            progress_notes = props.get("Progress Notes", {}).get("rich_text", [])
            if not progress_notes:
                print(
                    f"Error: Entry '{name_text}' missing Progress Notes.",
                    file=sys.stderr,
                )
                return False, f"Error: Entry '{name_text}' missing Progress Notes."

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Skills Development Tracker: {e}", file=sys.stderr)
        return False, f"Error querying Skills Development Tracker: {e}"

    # Step 5: Verify callout block exists after Skills section
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    # Find Skills database block
    skills_db_block_index = None
    for i, block in enumerate(all_blocks):
        if (
            block.get("type") == "child_database"
            and block.get("child_database", {}).get("title") == "Skills"
        ):
            skills_db_block_index = i
            break

    if skills_db_block_index is None:
        print("Error: Could not find Skills database block.", file=sys.stderr)
        return False, "Error: Could not find Skills database block."

    # Look for callout block after Skills database
    callout_found = False
    block = all_blocks[skills_db_block_index + 1]
    if block.get("type") == "callout":
        callout_data = block.get("callout", {})

        # Check background color
        if callout_data.get("color") != "blue_background":
            print("Error: Could not find callout block with blue background.")
            return False, "Error: Could not find callout block with blue background."

        # Check icon
        icon = callout_data.get("icon", {})
        if icon.get("type") != "emoji" or icon.get("emoji") != "🎯":
            print("Error: Could not find callout block with 🎯 emoji.")
            return False, "Error: Could not find callout block with 🎯 emoji."

        # Check content starts with "Focus Areas:"
        rich_text = callout_data.get("rich_text", [])
        if rich_text:
            content = rich_text[0].get("text", {}).get("content", "")
            if (
                content.startswith("Focus Areas:")
                and "CSS + Basic JS" in content
                and "Webflow" in content
                and "Rive" in content
            ):
                callout_found = True
                print(f"Success: Found callout block with content: {content}")
            else:
                print("Error: Could not find callout block with required text content.")
                return False, "Error: Could not find callout block with required text content."

    if not callout_found:
        print(
            "Error: Could not find callout block with Focus Areas after Skills section.",
            file=sys.stderr,
        )
        return False, "Error: Could not find callout block with Focus Areas after Skills section."

    print(
        "Success: Skills Development Tracker database and callout block verified successfully."
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
