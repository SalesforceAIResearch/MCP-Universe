"""Verification module for Deployment Process Sop task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """
    Verifies comprehensive SOP template completion with exact content matching.
    """
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(
            notion, main_id
        )
        if found_id and object_type == "page":
            page_id = found_id

    if not page_id:
        page_id = notion_utils.find_page(notion, "Standard Operating Procedure")
    if not page_id:
        print("Error: Page 'Standard Operating Procedure' not found.", file=sys.stderr)
        return False, "Error: Page 'Standard Operating Procedure' not found."

    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)
    verification_results = []

    # Check 1: Verify SOP header information updates
    sop_title_found = False
    created_date_found = False
    responsible_dept_found = False
    header_callout_found = False

    for block in all_blocks:
        if block.get("type") == "heading_1":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Software Deployment Process" in heading_text:
                sop_title_found = True
                verification_results.append("✅ SOP Title updated correctly")

        elif block.get("type") == "paragraph":
            para_text = notion_utils.get_block_plain_text(block)
            if "Created 2025-01-19" in para_text:
                created_date_found = True
                verification_results.append("✅ Created date updated correctly")
            elif "Responsible department: DevOps Engineering Team" in para_text:
                responsible_dept_found = True
                verification_results.append(
                    "✅ Responsible department updated correctly"
                )

        elif block.get("type") == "child_page":
            # Check child pages recursively for callout content - specifically the People team page
            try:
                child_page_info = notion.pages.retrieve(page_id=block["id"])
                child_page_title = ""
                if (
                    "properties" in child_page_info
                    and "title" in child_page_info["properties"]
                ):
                    title_list = child_page_info["properties"]["title"].get("title", [])
                    if title_list:
                        child_page_title = title_list[0].get("plain_text", "")
            except (KeyError, TypeError, IndexError):
                child_page_title = ""

            child_blocks = notion_utils.get_all_blocks_recursively(notion, block["id"])
            for child_block in child_blocks:
                if child_block.get("type") == "callout":
                    callout_text = notion_utils.get_block_plain_text(child_block)
                    # Look for the People team page with the DevOps Engineering Team Wiki callout
                    if (
                        "DevOps Engineering Team Wiki" in callout_text
                        and "deployment schedules" in callout_text
                        and "deployment activities" in callout_text
                    ):
                        header_callout_found = True
                        verification_results.append(
                            "✅ Header People team page callout updated correctly"
                        )

    # Check 2: Verify Purpose section content
    purpose_found = False
    expected_purpose = ("This SOP defines the standardized process for "
                        "deploying software applications to production "
                        "environments")

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Purpose" in heading_text:
                # Check next paragraph after Purpose heading
                for j in range(i + 1, min(i + 5, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(next_block)
                        if (
                            expected_purpose in para_text
                            and "engineering teams" in para_text
                        ):
                            purpose_found = True
                            verification_results.append(
                                "✅ Purpose section content updated correctly"
                            )
                        break
                break

    # Check 3: Verify Context section and child_page callouts
    context_found = False
    child_pages_updated = 0
    expected_context = ("Software deployments are critical operations that "
                        "can impact system availability")
    expected_child_callouts = [
        (
            "Change Management Policy (SOP-001)",
            ("Defines approval workflows and change review processes for "
             "all production modifications"),
            "Contacting IT",
        ),
        (
            "Incident Response Procedures (SOP-003)",
            ("Emergency procedures for handling deployment failures and "
             "system outages"),
            "Team lunches",
        ),
        (
            "Security Compliance Guidelines (SOP-007)",
            ("Security requirements and validation steps for production "
             "deployments"),
            "Sending swag",
        ),
    ]

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Context" in heading_text:
                # Check paragraph content
                for j in range(i + 1, min(i + 10, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(next_block)
                        if expected_context in para_text and "Q3 2023" in para_text:
                            context_found = True
                    elif next_block.get("type") == "toggle":
                        # Check child pages under toggle
                        toggle_blocks = notion_utils.get_all_blocks_recursively(
                            notion, next_block["id"]
                        )
                        for toggle_child in toggle_blocks:
                            if toggle_child.get("type") == "child_page":
                                # Get the child page title to match with expected callouts
                                try:
                                    child_page_info = notion.pages.retrieve(
                                        page_id=toggle_child["id"]
                                    )
                                    child_page_title = ""
                                    if (
                                        "properties" in child_page_info
                                        and "title" in child_page_info["properties"]
                                    ):
                                        title_list = child_page_info["properties"][
                                            "title"
                                        ].get("title", [])
                                        if title_list:
                                            child_page_title = title_list[0].get(
                                                "plain_text", ""
                                            )
                                except (KeyError, TypeError, IndexError):
                                    child_page_title = ""

                                child_blocks = notion_utils.get_all_blocks_recursively(
                                    notion, toggle_child["id"]
                                )
                                for child_block in child_blocks:
                                    if child_block.get("type") == "callout":
                                        callout_text = (
                                            notion_utils.get_block_plain_text(
                                                child_block
                                            )
                                        )
                                        for (
                                            expected_title,
                                            expected_content,
                                            expected_page_title,
                                        ) in expected_child_callouts:
                                            if (
                                                expected_title in callout_text
                                                and expected_content in callout_text
                                                and expected_page_title
                                                in child_page_title
                                            ):
                                                child_pages_updated += 1
                                                msg = (f"✅ Context child_page "
                                                       f"'{expected_page_title}' "
                                                       "updated correctly")
                                                verification_results.append(msg)
                                                break

    if context_found:
        verification_results.append("✅ Context section content updated correctly")

    if child_pages_updated == 3:
        verification_results.append(
            "✅ All 3 Context child_page callouts updated correctly"
        )
    else:
        msg = (f"❌ Only {child_pages_updated}/3 Context child_page callouts "
               "updated correctly (Contacting IT, Team lunches, Sending swag)")
        verification_results.append(msg)

    # Check 4: Verify Terminologies section with exact 4 bulleted items
    terminologies_found = False
    terminology_items = []
    expected_terminologies = [
        ("Blue-Green Deployment: A deployment strategy that maintains "
         "two identical production environments"),
        ("Rollback Window: The maximum time allowed to revert a deployment "
         "(30 minutes)"),
        ("Smoke Test: Initial verification tests run immediately after "
         "deployment"),
        ("Production Gateway: The approval checkpoint before production "
         "release"),
    ]

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Terminologies" in heading_text:
                # Check for intro paragraph
                for j in range(i + 1, min(i + 2, len(all_blocks))):
                    if all_blocks[j].get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(all_blocks[j])
                        if "Essential deployment terminology" in para_text:
                            terminologies_found = True
                            break

                # Check bulleted list items
                for j in range(i + 1, min(i + 10, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "bulleted_list_item":
                        item_text = notion_utils.get_block_plain_text(next_block)
                        terminology_items.append(item_text)
                    elif next_block.get("type") in [
                        "heading_1",
                        "heading_2",
                        "heading_3",
                    ]:
                        break
                break

    terminology_matches = sum(
        1
        for expected in expected_terminologies
        if any(expected in item for item in terminology_items)
    )

    if terminologies_found and len(terminology_items) == 4 and terminology_matches == 4:
        verification_results.append(
            "✅ Terminologies section with exactly 4 correct items"
        )
    else:
        items_count = len(terminology_items)
        msg = (f"❌ Terminologies: expected 4 items, found {items_count}, "
               f"{terminology_matches} correct")
        verification_results.append(msg)

    # Check 5: Verify Tools section with 2 child_page callouts
    tools_found = False
    tools_child_pages = 0
    expected_tools = [
        ("Jenkins CI/CD Pipeline", "automated deployments"),
        ("Kubernetes Dashboard", "rollback operations"),
    ]

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Tools" in heading_text:
                # Check intro paragraph
                for j in range(i + 1, min(i + 2, len(all_blocks))):
                    if all_blocks[j].get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(all_blocks[j])
                        if "Critical tools required" in para_text:
                            tools_found = True
                            break

                # Check child pages
                for j in range(i + 1, min(i + 10, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "child_page":
                        child_blocks = notion_utils.get_all_blocks_recursively(
                            notion, next_block["id"]
                        )
                        for child_block in child_blocks:
                            if child_block.get("type") == "callout":
                                callout_text = notion_utils.get_block_plain_text(
                                    child_block
                                )
                                for expected_title, expected_content in expected_tools:
                                    if (
                                        expected_title in callout_text
                                        and expected_content in callout_text
                                    ):
                                        tools_child_pages += 1
                                        break
                    elif next_block.get("type") in [
                        "heading_1",
                        "heading_2",
                        "heading_3",
                    ]:
                        break
                break

    if tools_found and tools_child_pages == 2:
        verification_results.append(
            "✅ Tools section with 2 correctly updated child_page callouts"
        )
    else:
        verification_results.append(
            f"❌ Tools section: expected 2 child_pages updated, found {tools_child_pages}"
        )

    # Check 6: Verify Roles & responsibilities with exactly 4 bulleted items
    roles_found = False
    role_items = []
    expected_roles = [
        ("DevOps Engineer: Executes deployment, monitors system health, "
         "initiates rollbacks if needed"),
        ("Lead Developer: Reviews code changes, approves deployment package, "
         "validates functionality"),
        ("QA Engineer: Verifies smoke tests, confirms user acceptance "
         "criteria"),
        ("Security Officer: Validates security compliance, approves "
         "security-sensitive deployments"),
    ]

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Roles" in heading_text and "responsibilities" in heading_text:
                # Check intro paragraph
                for j in range(i + 1, min(i + 2, len(all_blocks))):
                    if all_blocks[j].get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(all_blocks[j])
                        if "essential for successful deployment execution" in para_text:
                            roles_found = True
                            break

                # Check bulleted list items
                for j in range(i + 1, min(i + 10, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "bulleted_list_item":
                        item_text = notion_utils.get_block_plain_text(next_block)
                        role_items.append(item_text)
                    elif next_block.get("type") in [
                        "heading_1",
                        "heading_2",
                        "heading_3",
                    ]:
                        break
                break

    role_matches = sum(
        1 for expected in expected_roles
        if any(expected in item for item in role_items)
    )

    if roles_found and len(role_items) == 4 and role_matches == 4:
        verification_results.append(
            "✅ Roles & responsibilities section with exactly 4 correct items"
        )
    else:
        items_count = len(role_items)
        msg = (f"❌ Roles section: expected 4 items, found {items_count}, "
               f"{role_matches} correct")
        verification_results.append(msg)

    # Check 7: Verify Procedure section with exactly 3 numbered items
    procedure_found = False
    procedure_items = []
    expected_procedures = [
        ("Pre-deployment", "Lead Developer and Security Officer", "rollback plan"),
        ("Deployment execution", "staging environment first",
         "blue-green strategy"),
        (
            "Post-deployment",
            "minimum 30 minutes",
            "stakeholders via deployment notification",
        ),
    ]

    for i, block in enumerate(all_blocks):  # pylint: disable=too-many-nested-blocks
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Procedure" in heading_text:
                # Check intro paragraph
                for j in range(i + 1, min(i + 2, len(all_blocks))):
                    if all_blocks[j].get("type") == "paragraph":
                        para_text = notion_utils.get_block_plain_text(all_blocks[j])
                        if "Follow these steps in sequence" in para_text:
                            procedure_found = True
                            break

                # Check numbered list items
                for j in range(i + 1, min(i + 10, len(all_blocks))):
                    next_block = all_blocks[j]
                    if next_block.get("type") == "numbered_list_item":
                        item_text = notion_utils.get_block_plain_text(next_block)
                        procedure_items.append(item_text)
                    elif next_block.get("type") in [
                        "heading_1",
                        "heading_2",
                        "heading_3",
                    ]:
                        break
                break

    procedure_matches = 0
    for item_text in procedure_items:
        for (expected_title, expected_content1,
             expected_content2) in expected_procedures:
            if (
                expected_title in item_text
                and expected_content1 in item_text
                and expected_content2 in item_text
            ):
                procedure_matches += 1
                break

    if procedure_found and len(procedure_items) == 3 and procedure_matches == 3:
        verification_results.append("✅ Procedure section with exactly 3 correct items")
    else:
        items_count = len(procedure_items)
        msg = (f"❌ Procedure: expected 3 items, found {items_count}, "
               f"{procedure_matches} correct")
        verification_results.append(msg)

    # Calculate overall success
    total_checks = 14  # Number of major verification points
    successful_checks = sum(
        1 for result in verification_results if result.startswith("✅")
    )

    # Print all verification results
    print("\n=== SOP Template Verification Results ===", file=sys.stderr)
    for result in verification_results:
        print(result, file=sys.stderr)

    print(f"\n=== Summary: {successful_checks}/{total_checks} checks passed ===")

    # Must pass ALL checks to succeed
    success = (
        sop_title_found
        and created_date_found
        and responsible_dept_found
        and header_callout_found
        and purpose_found
        and context_found
        and child_pages_updated == 3
        and terminologies_found
        and len(terminology_items) == 4
        and terminology_matches == 4
        and tools_found
        and tools_child_pages == 2
        and roles_found
        and len(role_items) == 4
        and role_matches == 4
        and procedure_found
        and len(procedure_items) == 3
        and procedure_matches == 3
    )

    if success:
        print("\n🎉 SUCCESS: All SOP template requirements completed correctly!")
        return True, ""
    msg = (f"\n❌ FAILURE: SOP template verification failed. "
           f"{successful_checks}/{total_checks} requirements met.")
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
