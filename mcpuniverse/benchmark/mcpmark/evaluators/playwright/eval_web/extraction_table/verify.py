#!/usr/bin/env python3
"""
Verification script for checking Playwright web data extraction tasks.

This script verifies whether the model successfully extracted CSV format data from web pages
by checking the last assistant message in messages.json.
"""

import sys
import json
import os
import re
import csv
from io import StringIO

# Expected CSV header (must match exactly, including spaces)
EXPECTED_HEADER_LINE = "Title, Rating, Likes, Views, Replies"
EXPECTED_HEADERS = ["Title", "Rating", "Likes", "Views", "Replies"]
# Exact number of data rows (must match data.csv exactly)
EXPECTED_DATA_ROWS = 97


def get_model_response():
    """
    Get the model's response from the MCP_MESSAGES environment variable.
    Returns the last assistant message text.
    """
    messages_path = os.getenv("MCP_MESSAGES")
    print(f"| MCP_MESSAGES: {messages_path}")
    if not messages_path:
        print("| Warning: MCP_MESSAGES environment variable not set", file=sys.stderr)
        return None

    try:
        with open(messages_path, 'r', encoding='utf-8') as f:
            messages = json.load(f)

        # Find the last assistant message with status completed
        for message in reversed(messages):
            # Check if this is a completed assistant message
            if not (message.get('role') == 'assistant' and
                    message.get('status') == 'completed' and
                    message.get('type') == 'message'):
                continue

            content = message.get('content', [])
            # Extract text from content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') in ['text', 'output_text']:
                        return item.get('text', '')
            elif isinstance(content, str):
                return content

        print("| Warning: No completed assistant message found", file=sys.stderr)
        return None
    except (IOError, OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"| Error reading messages file: {str(e)}", file=sys.stderr)
        return None


def extract_csv_from_response(response):
    """
    Extract CSV data from model response.
    """
    # Look for CSV code blocks
    csv_pattern = r'```(?:csv)?\s*\n(.*?)\n```'
    matches = re.findall(csv_pattern, response, re.DOTALL | re.IGNORECASE)

    if matches:
        return matches[-1].strip()  # Return the last CSV block

    # If no code block found, try to find CSV data starting with header
    lines = response.split('\n')
    csv_start = -1

    # Stricter header matching: look for lines containing "Title" and "Rating"
    for i, line in enumerate(lines):
        if "Title" in line and "Rating" in line and "Likes" in line:
            csv_start = i
            break

    if csv_start >= 0:
        # Extract from header until empty line or non-CSV format line
        csv_lines = []
        for line in lines[csv_start:]:
            line = line.strip()
            if not line or ',' not in line:
                if csv_lines:  # If we already have data, stop at empty line
                    break
                continue
            csv_lines.append(line)
            if len(csv_lines) > 100:  # Prevent extracting too many rows
                break

        return '\n'.join(csv_lines)

    return None


def _validate_numeric_column(value, col_name, row_num):
    """Validate a numeric column value."""
    # Check for quotes (should not have any)
    if value.startswith('"') and value.endswith('"'):
        return False, f"| Row {row_num} {col_name} should not have quotes, actual: {value}"

    # Check numeric format
    if col_name == "Rating":
        try:
            float(value)
        except ValueError:
            return False, f"| Row {row_num} {col_name} should be a number, actual: {value}"
    else:
        if not value.isdigit():
            return False, f"| Row {row_num} {col_name} should be pure digits, actual: {value}"

    return True, None


def _validate_data_row(row, row_num):
    """Validate a single data row."""
    # Check if each column has data
    if not all(cell.strip() for cell in row):
        return False, f"| Row {row_num} contains empty data"

    # Check numeric column format
    for col_idx, col_name in [(1, "Rating"), (2, "Likes"), (3, "Views"), (4, "Replies")]:
        value = row[col_idx].strip()
        is_valid, error_msg = _validate_numeric_column(value, col_name, row_num)
        if not is_valid:
            return False, error_msg

    return True, None


def _validate_csv_structure(lines, rows):
    """Validate CSV structure (row count, header, column count)."""
    # Check total number of rows
    expected_total_rows = EXPECTED_DATA_ROWS + 1
    if len(lines) != expected_total_rows:
        msg = (f"| CSV total row count mismatch, expected: "
               f"{expected_total_rows} rows, actual: {len(lines)} rows")
        return False, msg

    # Check header row format
    header_line = lines[0].strip()
    if header_line != EXPECTED_HEADER_LINE:
        msg = (f"| Header format mismatch, expected: "
               f"'{EXPECTED_HEADER_LINE}', actual: '{header_line}'")
        return False, msg

    # Check column count for each row
    expected_columns = len(EXPECTED_HEADERS)
    for i, row in enumerate(rows):
        if len(row) != expected_columns:
            msg = (f"| Row {i+1} column count incorrect, expected: "
                   f"{expected_columns} columns, actual: {len(row)} columns")
            return False, msg

    return True, None


def validate_csv_data(csv_text):
    """
    Validate CSV data format and content, must match data.csv exactly.
    """
    if not csv_text:
        return False, "CSV data not found"

    try:
        lines = csv_text.strip().split('\n')
        csv_reader = csv.reader(StringIO(csv_text))
        rows = list(csv_reader)

        # Validate structure
        is_valid, error_msg = _validate_csv_structure(lines, rows)
        if not is_valid:
            return False, error_msg

        # Validate data row format
        valid_rows = 0
        for i, row in enumerate(rows[1:], 2):  # Skip header, start from row 2
            is_valid, error_msg = _validate_data_row(row, i)
            if not is_valid:
                return False, error_msg
            valid_rows += 1

        # Validate number of data rows
        if valid_rows != EXPECTED_DATA_ROWS:
            msg = (f"| Valid data row count mismatch, expected: "
                   f"{EXPECTED_DATA_ROWS} rows, actual: {valid_rows} rows")
            return False, msg

        msg = (f"| CSV validation successful: format matches data.csv "
               f"exactly, {valid_rows} valid data rows")
        return True, msg

    except (ValueError, KeyError, TypeError, AttributeError, csv.Error) as e:
        return False, f"| CSV format parsing error: {str(e)}"


def verify() -> tuple[bool, str]:
    """
    Verify if the model's response contains correct CSV data extraction results.
    """
    # Get model response
    model_response = get_model_response()

    if not model_response:
        print("| Model response not found", file=sys.stderr)
        return False, "Model response not found"

    print(f"|\n| Model response (first 500 characters): {model_response[:500]}...", file=sys.stderr)

    # Extract CSV data from response
    csv_data = extract_csv_from_response(model_response)

    if not csv_data:
        print("|\n| ✗ CSV data not found in response", file=sys.stderr)
        return False, "CSV data not found in response"

    print(f"|\n| Found CSV data (first 300 characters):\n| {csv_data[:300]}...", file=sys.stderr)

    # Validate CSV data
    is_valid, message = validate_csv_data(csv_data)

    if is_valid:
        print(f"|\n| ✓ {message}", file=sys.stderr)
        return True, ""
    print(f"|\n| ✗ CSV validation failed: {message}", file=sys.stderr)
    return False, f"CSV validation failed: {message}"


def main():
    """
    Executes the verification process and exits with a status code.
    """
    success, _error_msg = verify()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
