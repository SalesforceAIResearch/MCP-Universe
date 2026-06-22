"""
Evaluation functions for Notion tasks
"""
# pylint: disable=broad-exception-caught,unused-argument, too-many-return-statements
import json
import asyncio
from mcpuniverse.evaluator.functions import compare_func
from mcpuniverse.mcp.manager import MCPManager


##################################################################################
# Utils Function for Notion
##################################################################################
async def notion__search_page(query: str, **kwargs):
    """Check whether a Notion page exists."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = json.dumps({'query': query, 'filter': {'property': 'object', 'value': 'page'}})
    output = await manager.execute(
        server_name="notion",
        tool_name="API-post-search",
        arguments={"query": args},
        transport="stdio"
    )
    if output.isError:
        print(f"Error: {output}")
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def notion__get_block_children(block_id: str, return_block: bool = True, **kwargs):
    """Get the children of a Notion block."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        'block_id': block_id,
        'page_size': 100
    }
    output = await manager.execute(
        server_name="notion",
        tool_name="API-get-block-children",
        arguments=args,
        transport="stdio"
    )
    if output.isError:
        print(f"Error: {output}")
        return None
    json_obj = json.loads(output.content[0].text)

    if return_block:
        ret_blocks = []
        for block in json_obj['results']:
            rich_text = block.get(block['type'], {}).get('rich_text', [])
            for text_obj in rich_text:
                ret_blocks.append(text_obj['plain_text'])
        return ret_blocks
    return json_obj


async def notion__get_content_by_page_title(page_title: str, return_block: bool = True, **kwargs):
    """Get the content of a Notion page by page title."""

    notion_search_page_result = await notion__search_page(page_title)
    if 'results' not in notion_search_page_result or \
            len(notion_search_page_result['results']) == 0:
        return False, "Page not found"

    page_id = notion_search_page_result['results'][0]['id']
    blocks = await notion__get_block_children(page_id)

    if return_block:
        return True, blocks
    return True, "\n".join(blocks)


##################################################################################
# Evaluation functions
##################################################################################
@compare_func(name="notion.search_page")
async def notion_search_page(x: dict, *args, **kwargs) -> (bool, str):
    """Check whether a Notion page exists."""
    _, query = args
    pages = await notion__search_page(query, **kwargs)
    for result in pages['results']:
        if "properties" in result:
            title_obj = result['properties'].get('title', {})
            text_items = title_obj.get("title", [])
            if text_items and text_items[0]["text"]["content"] == query:
                return True, ""
    return False, "Page not found"


@compare_func(name="notion.compare_block_content_no_order")
async def compare_block_content_no_order(x: dict, *args, **kwargs) -> (bool, str):
    """Get the children of a Notion block."""
    gt_content, op_args = args

    page_title = op_args.get("page_title", None)
    if not page_title:
        return False, "page_title is required"

    if not gt_content:
        return False, "gt_content is required"

    # Add a small delay to ensure the page is available
    await asyncio.sleep(20)
    notion_search_page_result = await notion__search_page(page_title)
    if 'results' not in notion_search_page_result or \
            len(notion_search_page_result['results']) == 0:
        return False, f"Page {page_title} not found"

    page_id = notion_search_page_result['results'][0]['id']
    blocks = await notion__get_block_children(page_id)

    if len(blocks) != len(gt_content):
        return False, "Number of blocks not match"

    for item in blocks:
        if item not in gt_content:
            return False, f"Block content [{item}] not in ground truth list"

    return True, ""


@compare_func(name="notion.compare_page_text")
async def compare_page_text(x: dict, *args, **kwargs) -> (bool, str):
    """Compare the text of a Notion page."""
    gt_content, op_args = args
    page_title = op_args.get("page_title", None)
    if not page_title:
        return False, "page_title is required"

    if not gt_content:
        return False, "gt_content is required"

    # Add a small delay to ensure the page is available
    await asyncio.sleep(20)
    notion_search_page_result = await notion__search_page(page_title)

    if 'results' not in notion_search_page_result or \
            len(notion_search_page_result['results']) == 0:
        return False, f"Page {page_title} not found"

    page_id = notion_search_page_result['results'][0]['id']
    blocks = await notion__get_block_children(page_id)

    llm_response = []
    for block in blocks:
        llm_response.append(block)
    # add \n between each block
    llm_response = "\n".join(llm_response)

    if llm_response.strip().lower() != gt_content.strip().lower():
        return False, f"Page text not match:\nllm response:\n{llm_response}\ngt content:\n{gt_content}"

    return True, ""


@compare_func(name="notion.check_postcode_distance_to_place_in_notion_page")
async def check_postcode_distance_to_place_in_notion_page(x: dict, *args, **kwargs) -> (bool, str):
    """Check the postcode and distance to a place in a Notion page."""

    def _check_item_in_list(list_obj, filter_item_dict):
        """
        filter the list_obj by the filter_item_dict
        {
            "Apartment Name": "...",
            "Singapore Postcode": "...",
            "Distance to Suntec City (in km)": [float],
        }
        """
        for gt_item in list_obj:
            if gt_item["Apartment Name"] == filter_item_dict["Apartment Name"] and \
                    gt_item["Singapore Postcode"] == filter_item_dict["Singapore Postcode"]:

                pred_distance = filter_item_dict["Distance to Suntec City (in km)"]
                gt_distance = gt_item["Distance to Suntec City (in km)"]

                if abs(pred_distance - gt_distance) / max(pred_distance, gt_distance) <= 0.1:
                    return True
        return False

    gt_content, op_args = args
    page_title = op_args.get("page_title", None)
    if not page_title:
        return False, "page_title is required"

    place = op_args.get("place", None)
    if not place:
        return False, "place is required"

    gt_json_obj = gt_content

    search_return_code, notion_search_page_result = await notion__get_content_by_page_title(
        page_title, return_block=False)
    if not search_return_code:
        return False, f"Page {page_title} not found"

    if not isinstance(notion_search_page_result, str):
        return False, "Notion page content is not a string"

    # parse the json string
    try:
        notion_json_obj = json.loads(notion_search_page_result.replace('\n', ''))

        if not isinstance(notion_json_obj, list):
            return False, "Notion page content is not a list"

        # check the number of items
        if len(notion_json_obj) != len(gt_json_obj):
            return False, "Number of items not match"

        for item in notion_json_obj:
            filtered_dict = {
                "Apartment Name": item.get("Apartment Name", None),
                "Singapore Postcode": item.get("Singapore Postcode", None),
                "Distance to Suntec City (in km)": item.get("Distance to Suntec City (in km)", None),
            }
            check_result = _check_item_in_list(gt_json_obj, filtered_dict)
            if not check_result:
                return False, f"Item {filtered_dict} not found in ground truth list"

        return True, ""


    except json.JSONDecodeError:
        return False, "Notion page content is not a valid JSON"
