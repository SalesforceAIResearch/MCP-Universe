import sys
from datetime import datetime
from notion_client import Client
from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

EXPECTED_HEADERS = ["Project", "Eng Hours", "Progress", "Start Date", "End Date"]

EXPECTED_ROWS = [
    {
        "Project": "Improve response times for support requests",
        "Eng Hours": 100,
        "Progress": 0.33,  # 33%
        "Start Date": "2024-10-30",
        "End Date": "2024-11-17",
    },
    {
        "Project": "Add a new social media integration",
        "Eng Hours": 200,
        "Progress": 0.40,  # 40%
        "Start Date": "2024-11-07",
        "End Date": "2024-11-25",
    },
    {
        "Project": "Integrate with a popular third-party service",
        "Eng Hours": 250,
        "Progress": 0.20,  # 20%
        "Start Date": "2024-11-10",
        "End Date": "2024-11-18",
    },
    {
        "Project": "Create customer knowledge base",
        "Eng Hours": 150,
        "Progress": 0.40,  # 40%
        "Start Date": "2024-11-19",
        "End Date": "2024-11-25",
    },
    {
        "Project": "Redesign the onboarding process",
        "Eng Hours": 300,
        "Progress": 0.75,  # 75%
        "Start Date": "2024-11-20",
        "End Date": "2024-12-04",
    },
    {
        "Project": "Publish support knowledge base",
        "Eng Hours": None,  # N/A
        "Progress": 0.0,  # 0%
        "Start Date": "2024-11-27",
        "End Date": "2024-11-29",
    },
]

# Sort the expected rows by End Date so we can directly compare order
EXPECTED_ROWS.sort(key=lambda r: r["End Date"])


def _plain_text_from_cell(cell):
    """Concatenate plain_text from a single cell (list of rich_text)."""
    return "".join(rt.get("plain_text", "") for rt in cell).strip()


def _parse_progress(value: str):
    """Convert a progress string like '40%', '40.0 %', '0.4' to float in range 0-1."""
    value = value.strip()
    if not value:
        return None

    has_percent = "%" in value
    # Remove percent sign and any spaces
    value = value.replace("%", "").strip()
    try:
        num = float(value)
        if has_percent or num > 1:
            num /= 100.0
        return num
    except ValueError:
        return None


def _parse_eng_hours(value: str):
    value = value.strip().lower()
    if value in {"n/a", "na", "", "—", "-"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str):
    value = value.strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def verify(notion: Client, main_id: str = None) -> tuple[bool, str]:
    """Verify that the last table in the 'Team Projects' page matches EXPECTED_ROWS and headers."""
    page_id = None
    if main_id:
        found_id, object_type = notion_utils.find_page_or_database_by_id(notion, main_id)
        if found_id and object_type == 'page':
            page_id = found_id
    
    if not page_id:
        page_id = notion_utils.find_page(notion, "Team Projects")
    if not page_id:
        print("Error: Page 'Team Projects' not found.", file=sys.stderr)
        return False, "Page 'Team Projects' not found"

    # Fetch all blocks to locate table blocks
    blocks = notion_utils.get_all_blocks_recursively(notion, page_id)
    table_blocks = [b for b in blocks if b.get("type") == "table"]
    if not table_blocks:
        print("Error: No table blocks found in 'Team Projects' page.", file=sys.stderr)
        return False, "No table blocks found in 'Team Projects' page"

    table_block = table_blocks[-1]  # Use the last table block
    table_id = table_block["id"]

    # Retrieve table rows
    rows = notion.blocks.children.list(block_id=table_id).get("results", [])
    if not rows:
        print("Error: Table block has no rows.", file=sys.stderr)
        return False, "Table block has no rows"

    # Validate headers
    header_cells = rows[0].get("table_row", {}).get("cells", [])
    headers = [_plain_text_from_cell(c) for c in header_cells]
    if headers != EXPECTED_HEADERS:
        print(f"Error: Table headers mismatch. Found {headers}, expected {EXPECTED_HEADERS}.", file=sys.stderr)
        return False, f"Table headers mismatch. Found {headers}, expected {EXPECTED_HEADERS}"

    # Parse data rows
    data_rows = []
    for r in rows[1:]:
        cells = r.get("table_row", {}).get("cells", [])
        if len(cells) < 5:
            continue  # Skip malformed rows
        project = _plain_text_from_cell(cells[0])
        eng_hours_raw = _plain_text_from_cell(cells[1])
        progress_raw = _plain_text_from_cell(cells[2])
        start_raw = _plain_text_from_cell(cells[3])
        end_raw = _plain_text_from_cell(cells[4])

        row_dict = {
            "Project": project,
            "Eng Hours": _parse_eng_hours(eng_hours_raw),
            "Progress": _parse_progress(progress_raw),
            "Start Date": start_raw.strip(),
            "End Date": end_raw.strip(),
        }
        data_rows.append(row_dict)

    if len(data_rows) != len(EXPECTED_ROWS):
        print(f"Error: Expected {len(EXPECTED_ROWS)} data rows, found {len(data_rows)}.", file=sys.stderr)
        return False, f"Expected {len(EXPECTED_ROWS)} data rows, found {len(data_rows)}"

    # Verify sorting by End Date ascending
    parsed_end_dates = [_parse_date(r["End Date"]) for r in data_rows]
    if any(d is None for d in parsed_end_dates):
        print("Error: One or more End Date values could not be parsed.", file=sys.stderr)
        return False, "One or more End Date values could not be parsed"
    if parsed_end_dates != sorted(parsed_end_dates):
        print("Error: Table is not sorted by End Date ascending.", file=sys.stderr)
        return False, "Table is not sorted by End Date ascending"

    # Create mapping from project -> row for comparison
    data_map = {r["Project"]: r for r in data_rows}

    for expected in EXPECTED_ROWS:
        proj = expected["Project"]
        if proj not in data_map:
            print(f"Error: Project '{proj}' not found in table.", file=sys.stderr)
            return False, f"Project '{proj}' not found in table"
        actual = data_map[proj]

        # Compare Eng Hours
        expected_hours = expected["Eng Hours"]
        actual_hours = actual["Eng Hours"]
        if expected_hours is None:
            if actual_hours is not None:
                print(f"Error: Eng Hours for '{proj}' expected to be empty/N\u204aA but found '{actual_hours}'.", file=sys.stderr)
                return False, f"Eng Hours for '{proj}' expected to be empty/N/A but found '{actual_hours}'"
        else:
            if actual_hours is None or abs(actual_hours - expected_hours) > 1e-2:
                print(f"Error: Eng Hours for '{proj}' mismatch. Expected {expected_hours}, found {actual_hours}.", file=sys.stderr)
                return False, f"Eng Hours for '{proj}' mismatch. Expected {expected_hours}, found {actual_hours}"

        # Compare Progress with tolerance
        expected_progress = expected["Progress"]
        actual_progress = actual["Progress"]
        if actual_progress is None or abs(actual_progress - expected_progress) > 1e-2:
            print(f"Error: Progress for '{proj}' mismatch. Expected {expected_progress}, found {actual_progress}.", file=sys.stderr)
            return False, f"Progress for '{proj}' mismatch. Expected {expected_progress}, found {actual_progress}"

        # Compare Start and End Dates (string equality)
        if actual["Start Date"] != expected["Start Date"]:
            print(f"Error: Start Date for '{proj}' mismatch. Expected {expected['Start Date']}, found {actual['Start Date']}.", file=sys.stderr)
            return False, f"Start Date for '{proj}' mismatch. Expected {expected['Start Date']}, found {actual['Start Date']}"
        if actual["End Date"] != expected["End Date"]:
            print(f"Error: End Date for '{proj}' mismatch. Expected {expected['End Date']}, found {actual['End Date']}.", file=sys.stderr)
            return False, f"End Date for '{proj}' mismatch. Expected {expected['End Date']}, found {actual['End Date']}"

    print("Success: Verified table block contents and order successfully.")
    return True, ""


def main():
    """Main verification function."""
    notion = notion_utils.get_notion_client()
    main_id = sys.argv[1] if len(sys.argv) > 1 else None
    success, error_msg = verify(notion, main_id)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main() 