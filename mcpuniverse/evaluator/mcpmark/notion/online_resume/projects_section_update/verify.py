"""Verification module for Projects Section Update task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that the projects section has been reorganized correctly with cross-section references.
    """
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        page_id = notion_utils.find_page(notion, "Online Resume")
    if not page_id:
        print("Error: Page 'Online Resume' not found.", file=sys.stderr)
        return False, "Error: Page 'Online Resume' not found."

    # Find the Projects database
    projects_db_id = notion_utils.find_database_in_block(notion, page_id, "Projects")
    if not projects_db_id:
        print("Error: Database 'Projects' not found.", file=sys.stderr)
        return False, "Error: Database 'Projects' not found."

    # Find the Skills database to get the highest skill level
    skills_db_id = notion_utils.find_database_in_block(notion, page_id, "Skills")
    if not skills_db_id:
        print("Error: Database 'Skills' not found.", file=sys.stderr)
        return False, "Error: Database 'Skills' not found."

    # Query Skills database to find the highest skill level
    skills_results = notion.databases.query(database_id=skills_db_id).get("results", [])
    highest_skill_name = ""
    highest_skill_level = 0

    for skill_page in skills_results:
        properties = skill_page.get("properties", {})
        skill_name_prop = properties.get("Skill", {}).get("title", [])
        skill_level_prop = properties.get("Skill Level", {}).get("number")

        if skill_name_prop and skill_level_prop is not None:
            skill_name = skill_name_prop[0].get("text", {}).get("content", "")
            if skill_level_prop > highest_skill_level:
                highest_skill_level = skill_level_prop
                highest_skill_name = skill_name

    if not highest_skill_name:
        print("Error: Could not find any skills with skill levels.", file=sys.stderr)
        return False, "Error: Could not find any skills with skill levels."

    # Query Projects database
    projects_results = notion.databases.query(database_id=projects_db_id).get(
        "results", []
    )

    # Check that "Knitties eComm Website" is deleted
    for page in projects_results:
        properties = page.get("properties", {})
        name_prop = properties.get("Name", {}).get("title", [])
        if (
            name_prop
            and name_prop[0].get("text", {}).get("content") == "Knitties eComm Website"
        ):
            print(
                "Failure: 'Knitties eComm Website' project was not deleted.",
                file=sys.stderr,
            )
            return False, "Failure: 'Knitties eComm Website' project was not deleted."

    # Check that "Zapier Dashboard Redesign" exists with correct properties
    zapier_project_found = False
    for page in projects_results:
        properties = page.get("properties", {})
        name_prop = properties.get("Name", {}).get("title", [])
        if (
            name_prop
            and name_prop[0].get("text", {}).get("content")
            == "Zapier Dashboard Redesign"
        ):
            zapier_project_found = True

            # Check description contains reference to UI Design Internship
            desc_prop = properties.get("Description", {}).get("rich_text", [])
            if not desc_prop:
                print("Failure: Zapier project has no description.", file=sys.stderr)
                return False, "Failure: Zapier project has no description."

            description_text = desc_prop[0].get("text", {}).get("content", "")
            base_desc = (
                "Led the complete redesign of Zapier's main dashboard, "
                "focusing on improved usability and modern design patterns. "
                "Implemented new navigation system and responsive layouts."
            )
            if base_desc not in description_text:
                print(
                    "Failure: Zapier project description is missing base content.",
                    file=sys.stderr,
                )
                return False, "Failure: Zapier project description is missing base content."

            # Check date
            date_prop = properties.get("Date", {}).get("date", {})
            if (
                not date_prop
                or date_prop.get("start") != "2024-01-01"
                or date_prop.get("end") != "2024-06-30"
            ):
                print(
                    "Failure: Zapier project date range is incorrect.", file=sys.stderr
                )
                return False, "Failure: Zapier project date range is incorrect."

            # Check tags
            tags_prop = properties.get("Tags", {}).get("multi_select", [])
            tag_names = {tag.get("name") for tag in tags_prop}
            if "UI Design" not in tag_names or "Enterprise" not in tag_names:
                print(
                    "Failure: Zapier project is missing required tags.", file=sys.stderr
                )
                return False, "Failure: Zapier project is missing required tags."

            # Check phone
            phone_prop = properties.get("Phone", {}).get("phone_number", [])
            if not phone_prop or phone_prop != "+44 7871263013":
                print(
                    "Failure: Zapier project phone number is incorrect.",
                    file=sys.stderr,
                )
                return False, "Failure: Zapier project phone number is incorrect."

            # Check url
            url_prop = properties.get("Url", {}).get("url", [])
            if not url_prop or url_prop != "www.zinenwine.com":
                print("Failure: Zapier project url is incorrect.", file=sys.stderr)
                return False, "Failure: Zapier project url is incorrect."

            # Check Enterprise tag color
            enterprise_tag_purple = False
            for tag in tags_prop:
                if tag.get("name") == "Enterprise" and tag.get("color") == "purple":
                    enterprise_tag_purple = True
                    break
            if not enterprise_tag_purple:
                print(
                    "Failure: Enterprise tag does not have purple color.",
                    file=sys.stderr,
                )
                return False, "Failure: Enterprise tag does not have purple color."

            break

    if not zapier_project_found:
        print(
            "Failure: 'Zapier Dashboard Redesign' project not found.", file=sys.stderr
        )
        return False, "Failure: 'Zapier Dashboard Redesign' project not found."

    # Find the Projects database block and verify blocks after it
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    # Find the Projects database block
    projects_db_index = -1
    for i, block in enumerate(all_blocks):
        if (
            block.get("type") == "child_database"
            and block.get("child_database", {}).get("title") == "Projects"
        ):
            projects_db_index = i
            break

    if projects_db_index == -1:
        print("Error: Could not find Projects database block.", file=sys.stderr)
        return False, "Error: Could not find Projects database block."

    # Check blocks after Projects database
    if projects_db_index + 3 > len(all_blocks):
        print("Failure: Not enough blocks after Projects database.", file=sys.stderr)
        return False, "Failure: Not enough blocks after Projects database."

    # Check divider block
    divider_block = all_blocks[projects_db_index + 1]
    if divider_block.get("type") != "divider":
        print(
            "Failure: Expected divider block after Projects database.", file=sys.stderr
        )
        return False, "Failure: Expected divider block after Projects database."

    # Check heading block
    heading_block = all_blocks[projects_db_index + 2]
    if heading_block.get("type") != "heading_2":
        print("Failure: Expected heading_2 block after divider.", file=sys.stderr)
        return False, "Failure: Expected heading_2 block after divider."

    heading_text = heading_block.get("heading_2", {}).get("rich_text", [])
    if (
        not heading_text
        or heading_text[0].get("text", {}).get("content") != "Current Focus"
    ):
        print("Failure: Heading text is incorrect.", file=sys.stderr)
        return False, "Failure: Heading text is incorrect."

    # Check paragraph block with dynamic skill reference
    paragraph_block = all_blocks[projects_db_index + 3]
    if paragraph_block.get("type") != "paragraph":
        print("Failure: Expected paragraph block after heading.", file=sys.stderr)
        return False, "Failure: Expected paragraph block after heading."

    paragraph_text = paragraph_block.get("paragraph", {}).get("rich_text", [])
    if not paragraph_text:
        print("Failure: Paragraph block is empty.", file=sys.stderr)
        return False, "Failure: Paragraph block is empty."

    paragraph_content = paragraph_text[0].get("text", {}).get("content", "")

    # Check that paragraph contains the base text
    base_text = (
        "The Zapier Dashboard Redesign represents my most impactful recent "
        "work, leveraging my expertise in"
    )
    if base_text not in paragraph_content:
        print("Failure: Paragraph does not contain base text.", file=sys.stderr)
        return False, "Failure: Paragraph does not contain base text."

    # Check that paragraph references the highest skill
    skill_level_percent = int(highest_skill_level * 100)
    expected_skill_ref = f"{highest_skill_name} ({skill_level_percent}%)"
    if expected_skill_ref not in paragraph_content:
        print(
            f"Failure: Paragraph does not reference highest skill '{expected_skill_ref}'.",
            file=sys.stderr,
        )
        return False, f"Failure: Paragraph does not reference highest skill '{expected_skill_ref}'."

    # Check that paragraph contains the ending text
    ending_text = (
        "enterprise-grade solutions that prioritize both aesthetics and functionality"
    )
    if ending_text not in paragraph_content:
        print(
            "Failure: Paragraph does not contain proper ending text.", file=sys.stderr
        )
        return False, "Failure: Paragraph does not contain proper ending text."

    msg = (f"Success: Projects section has been reorganized correctly with "
           f"cross-section references (highest skill: {highest_skill_name} "
           f"at {skill_level_percent}%).")
    print(msg)
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
