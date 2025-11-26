"""Verification module for Packing Progress Summary task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    """
    Verifies that:
    1. All Clothes items except hat are marked as packed
    2. SIM Card and Wallet entries are checked
    3. Packing Progress Summary section is created with statistics
    """
    # Find the main Japan Travel Planner page
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

    # Find the Packing List database
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)
    packing_list_db_id = None
    packing_list_heading_id = None

    for i, block in enumerate(all_blocks):
        # Find the Packing List heading
        if block.get("type") == "heading_2":
            heading_text = notion_utils.get_block_plain_text(block)
            if "Packing List" in heading_text and "💼" in heading_text:
                packing_list_heading_id = block["id"]
                # Look for the database after this heading
                for j in range(i + 1, len(all_blocks)):
                    if all_blocks[j].get("type") == "child_database":
                        packing_list_db_id = all_blocks[j]["id"]
                        break
                break

    if not packing_list_db_id:
        print("Error: Packing List database not found.", file=sys.stderr)
        return False, "Error: Packing List database not found."

    # Query the database for all items
    try:
        db_items = notion.databases.query(database_id=packing_list_db_id)

        # Track items for verification
        clothes_items = []
        sim_card_found = False
        sim_card_packed = False
        wallet_found = False
        wallet_packed = False

        # Process all items
        for page in db_items.get("results", []):
            props = page.get("properties", {})

            # Get item name
            name_prop = props.get("Name", {})
            if name_prop.get("type") == "title":
                name = "".join(
                    [t.get("plain_text", "") for t in name_prop.get("title", [])]
                )
            else:
                continue

            # Get type (multi_select)
            type_prop = props.get("Type", {})
            types = []
            if type_prop.get("type") == "multi_select":
                types = [
                    opt.get("name", "") for opt in type_prop.get("multi_select", [])
                ]

            # Get packed status
            packed_prop = props.get("Packed", {})
            packed = False
            if packed_prop.get("type") == "checkbox":
                packed = packed_prop.get("checkbox", False)

            # Check specific items
            if name == "SIM Card":
                sim_card_found = True
                sim_card_packed = packed
            elif name == "Wallet":
                wallet_found = True
                wallet_packed = packed

            # Track Clothes items
            if "Clothes" in types:
                clothes_items.append(
                    {"name": name, "packed": packed, "is_hat": "hat" in name.lower()}
                )

        # Verify Clothes items (all packed except hat)
        for item in clothes_items:
            if item["is_hat"]:
                if item["packed"]:
                    print(
                        "Error: Hat should not be packed but is marked as packed.",
                        file=sys.stderr,
                    )
                    return False, "Error: Hat should not be packed but is marked as packed."
            else:
                if not item["packed"]:
                    print(
                        f"Error: Clothes item '{item['name']}' should be packed but is not.",
                        file=sys.stderr,
                    )
                    msg = (f"Error: Clothes item '{item['name']}' should be "
                           "packed but is not.")
                    return False, msg

        print("Success: All Clothes items are correctly marked (packed except hat).")

        # Verify SIM Card and Wallet
        if not sim_card_found:
            print("Error: SIM Card entry not found.", file=sys.stderr)
            return False, "Error: SIM Card entry not found."
        if not sim_card_packed:
            print("Error: SIM Card entry is not checked (packed).", file=sys.stderr)
            return False, "Error: SIM Card entry is not checked (packed)."

        if not wallet_found:
            print("Error: Wallet entry not found.", file=sys.stderr)
            return False, "Error: Wallet entry not found."
        if not wallet_packed:
            print("Error: Wallet entry is not checked (packed).", file=sys.stderr)
            return False, "Error: Wallet entry is not checked (packed)."

        print("Success: SIM Card and Wallet entries are checked.")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"Error querying Packing List database: {e}", file=sys.stderr)
        return False, f"Error querying Packing List database: {e}"

    # Expected ground truth statistics
    expected_stats = {
        "Clothes": {"packed": 12, "total": 13},
        "Electronics": {"packed": 1, "total": 10},
        "Essentials": {"packed": 1, "total": 12},
        "Miscellaneous": {"packed": 0, "total": 10},
        "Shoes": {"packed": 0, "total": 2},
        "Toiletries": {"packed": 0, "total": 19},
    }

    # Verify Packing Progress Summary section
    # Re-fetch blocks to get updated content
    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    # Find the Packing List heading again and check blocks after it
    packing_heading_index = None
    for i, block in enumerate(all_blocks):
        if block.get("id") == packing_list_heading_id:
            packing_heading_index = i
            break

    summary_found = False
    statistics_verified = True
    found_statistics = {}

    if packing_heading_index is not None:  # pylint: disable=too-many-nested-blocks
        # Look for summary in the next few blocks
        for i in range(
            packing_heading_index + 1, min(packing_heading_index + 15, len(all_blocks))
        ):
            block = all_blocks[i]
            block_text = notion_utils.get_block_plain_text(block)

            # Check for "Packing Progress Summary" paragraph
            if "Packing Progress Summary" in block_text:
                summary_found = True
                # Check if it's bold
                if block.get("type") == "paragraph":
                    rich_text_list = block.get("paragraph", {}).get("rich_text", [])
                    for text_obj in rich_text_list:
                        if "Packing Progress Summary" in text_obj.get("text", {}).get(
                            "content", ""
                        ):
                            if not text_obj.get("annotations", {}).get("bold", False):
                                print(
                                    "Error: 'Packing Progress Summary' text is not bold.",
                                    file=sys.stderr,
                                )
                                return False, "Error: 'Packing Progress Summary' text is not bold."

            # Check for statistics bullet points in format "Category: X/Y packed"
            if (
                block.get("type") == "bulleted_list_item"
                and ":" in block_text
                and "/" in block_text
                and "packed" in block_text
            ):
                # Parse the statistic line
                # Expected format: "Category: X/Y packed"
                try:
                    parts = block_text.split(":")
                    if len(parts) >= 2:
                        category = parts[0].strip()
                        stats_part = parts[1].strip()

                        # Extract X/Y from "X/Y packed"
                        if "/" in stats_part and "packed" in stats_part:
                            nums = stats_part.split("packed")[0].strip()
                            if "/" in nums:
                                x_str, y_str = nums.split("/")
                                x = int(x_str.strip())
                                y = int(y_str.strip())
                                found_statistics[category] = {"packed": x, "total": y}
                except (ValueError, TypeError, AttributeError, KeyError):
                    pass  # Continue if parsing fails

    if not summary_found:
        msg = ("Error: 'Packing Progress Summary' section not found after "
               "Packing List heading.")
        print(msg, file=sys.stderr)
        return False, msg

    if not found_statistics:
        msg = ("Error: No valid packing statistics bullet points found in "
               "format 'Category: X/Y packed'.")
        print(msg, file=sys.stderr)
        return False, msg

    # Verify the statistics match the expected values
    for category, stats in expected_stats.items():
        if category not in found_statistics:
            print(
                f"Error: Category '{category}' missing from Packing Progress Summary.",
                file=sys.stderr,
            )
            statistics_verified = False
        else:
            found = found_statistics[category]
            if found["packed"] != stats["packed"] or found["total"] != stats["total"]:
                expected_str = f"{stats['packed']}/{stats['total']}"
                found_str = f"{found['packed']}/{found['total']}"
                msg = (f"Error: Statistics mismatch for '{category}': "
                       f"expected {expected_str} packed, "
                       f"found {found_str} packed.")
                print(msg, file=sys.stderr)
                statistics_verified = False

    # Check for extra categories in summary that don't exist in expected
    for category in found_statistics:
        if category not in expected_stats:
            print(
                f"Error: Unexpected category '{category}' in summary.", file=sys.stderr
            )
            statistics_verified = False

    if not statistics_verified:
        return False, "Error: Statistics verification failed."

    msg = ("Success: Packing Progress Summary section created with correct "
           "statistics.")
    print(msg)
    # print(f"Verified statistics: {', '.join(f'{k}: {v['packed']}/"
    #       f"{v['total']} packed' for k, v in expected_stats.items())}")

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
