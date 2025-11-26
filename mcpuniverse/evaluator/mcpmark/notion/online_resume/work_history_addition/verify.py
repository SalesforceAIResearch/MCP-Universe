"""Verification module for Work History Addition task in Notion workspace."""

# pylint: disable=duplicate-code,import-error,astroid-error

import sys
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """
    Verifies that the new work history entry for 'Research Assistant' has been added correctly.
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

    all_blocks = notion_utils.get_all_blocks_recursively(notion, page_id)

    def find_image_url_under_heading(blocks, heading_text, notion_client):
        heading_index = -1
        for i, block in enumerate(blocks):
            block_type = block.get("type")
            if block_type == "heading_1":
                if heading_text in notion_utils.get_block_plain_text(block):
                    heading_index = i
                    break

        if heading_index == -1:
            return None

        for i in range(heading_index + 1, len(blocks)):  # pylint: disable=too-many-nested-blocks
            block = blocks[i]
            if block.get("type") in ["heading_1", "heading_2", "heading_3"]:
                break
            if block.get("type") == "image" and block.get("image", {}).get("file"):
                return block.get("image", {}).get("file", {}).get("url")
            if block.get("type") == "column_list":
                column_list_id = block["id"]
                columns = notion_utils.get_all_blocks_recursively(
                    notion_client, column_list_id
                )
                for column in columns:
                    if column.get("type") == "column":
                        column_id = column["id"]
                        column_blocks = notion_utils.get_all_blocks_recursively(
                            notion_client, column_id
                        )
                        for inner_block in column_blocks:
                            if inner_block.get("type") == "image" and inner_block.get(
                                "image", {}
                            ).get("file"):
                                return (
                                    inner_block.get("image", {})
                                    .get("file", {})
                                    .get("url")
                                )
        return None

    def get_block_annotations(block):
        block_type = block.get("type")
        if not block_type:
            return {}
        block_content = block.get(block_type)
        if not block_content:
            return {}
        rich_text_list = block_content.get("rich_text", [])
        if not rich_text_list:
            return {}
        return rich_text_list[0].get("annotations", {})

    education_image_url = find_image_url_under_heading(all_blocks, "Education", notion)
    if not education_image_url:
        print(
            "Error: Could not find the image in the 'Education' section.",
            file=sys.stderr,
        )
        return False, "Error: Could not find the image in the 'Education' section."

    heading_text = "Work History"
    heading_index = -1
    for i, block in enumerate(all_blocks):
        if block.get(
            "type"
        ) == "heading_1" and heading_text in notion_utils.get_block_plain_text(block):
            heading_index = i
            break

    if heading_index == -1:
        print(f"Error: Could not find the '{heading_text}' heading.", file=sys.stderr)
        return False, f"Error: Could not find the '{heading_text}' heading."

    for i in range(heading_index + 1, len(all_blocks)):  # pylint: disable=too-many-nested-blocks
        block = all_blocks[i]
        if block.get("type") in ["heading_1", "heading_2", "heading_3"]:
            break

        if block.get("type") == "column_list":
            column_list_id = block["id"]
            columns = notion_utils.get_all_blocks_recursively(notion, column_list_id)
            if len(columns) < 2:
                continue

            image_column = None
            text_column = None
            for column in columns:
                if column.get("type") == "column":
                    if column.get("column", {}).get("width_ratio") == 0.125:
                        image_column = column
                    elif column.get("column", {}).get("width_ratio") == 0.875:
                        text_column = column

            if image_column is None or text_column is None:
                continue

            image_column_blocks = notion_utils.get_all_blocks_recursively(
                notion, image_column["id"]
            )
            text_column_blocks = notion_utils.get_all_blocks_recursively(
                notion, text_column["id"]
            )

            column_image_url = None
            for inner_block in image_column_blocks:
                if inner_block.get("type") == "image" and inner_block.get(
                    "image", {}
                ).get("file"):
                    column_image_url = (
                        inner_block.get("image", {}).get("file", {}).get("url")
                    )
                    break

            if (
                not column_image_url
                or column_image_url[:100] != education_image_url[:100]
            ):
                continue

            for j, inner_block in enumerate(text_column_blocks):
                if "Research Assistant" in notion_utils.get_block_plain_text(
                    inner_block
                ):
                    title_annotations = get_block_annotations(inner_block)
                    if j + 2 < len(text_column_blocks):
                        date_block = text_column_blocks[j + 1]
                        description_block = text_column_blocks[j + 2]

                        date_text = "January - August 2023"
                        description_text = (
                            "Assisted in conducting user experience research "
                            "projects at my bachelor's program, supporting "
                            "data collection, analyzing user feedback, and "
                            "preparing research reports. Developed strong "
                            "skills in research methodologies and improved "
                            "collaboration with interdisciplinary teams."
                        )

                        date_annotations = get_block_annotations(date_block)
                        description_annotations = get_block_annotations(
                            description_block
                        )

                        if (
                            date_text in notion_utils.get_block_plain_text(date_block)  # pylint: disable=too-many-boolean-expressions
                            and description_text
                            in notion_utils.get_block_plain_text(description_block)
                            and title_annotations.get("bold")
                            and date_annotations.get("italic")
                            and date_annotations.get("color") == "gray"
                            and description_annotations.get("color") == "default"
                            and description_annotations.get("italic") is not True
                            and description_annotations.get("bold") is not True
                        ):
                            print("Success: Verified new work history entry.")
                            return True, ""

    print("Failure: Could not verify the new work history entry.", file=sys.stderr)
    return False, "Failure: Could not verify the new work history entry."


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
