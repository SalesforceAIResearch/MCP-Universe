#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Legal Document Solution Tracing Task
"""

import sys
from pathlib import Path
import csv
import os
import json

def get_test_directory() -> Path:
    """Get the test directory from FILESYSTEM_TEST_DIR env var."""
    test_root = os.environ.get("FILESYSTEM_TEST_DIR")
    if not test_root:
        raise ValueError("FILESYSTEM_TEST_DIR environment variable is required")

    # Ensure the path includes the category
    # Read category from meta.json
    meta_file = Path(__file__).parent / "meta.json"
    with open(meta_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)
        category = meta.get("category_id", "legal_document")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_output_file_exists(test_dir: Path) -> tuple:
    """Verify that the tracing.csv file exists."""
    output_file = test_dir / "tracing.csv"

    if not output_file.exists():
        print("❌ File 'tracing.csv' not found")
        return False, "File 'tracing.csv' not found"

    print("✅ Output file 'tracing.csv' found")
    return True, ""

def verify_csv_format(test_dir: Path) -> tuple:
    """Verify that the CSV file has the correct format."""
    output_file = test_dir / "tracing.csv"

    try:
        with open(output_file, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)

            if not rows:
                print("❌ CSV file is empty")
                return False, "CSV file is empty"

            # Check if there are at least 2 rows (header + data)
            if len(rows) < 2:
                print("❌ CSV file has insufficient rows")
                return False, "CSV file has insufficient rows"

            # Check if header row has correct number of columns
            header = rows[0]
            if len(header) != 5:  # First column (can be anything) + 4 clauses
                msg = (f"Header row has incorrect number of columns: "
                       f"{len(header)}, expected 5")
                print(f"❌ {msg}")
                return False, msg

            # Check if data rows have correct number of columns
            for i, row in enumerate(rows[1:], 1):
                if len(row) != 5:
                    msg = (f"Data row {i} has incorrect number of columns: "
                           f"{len(row)}, expected 5")
                    print(f"❌ {msg}")
                    return False, msg

            print("✅ CSV format is correct")
            return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading CSV file: {e}"

def verify_csv_content(test_dir: Path) -> tuple:  # pylint: disable=R0911,R0912,R0914,R0915
    """Verify that the CSV content matches the expected answer exactly."""
    output_file = test_dir / "tracing.csv"

    try:
        with open(output_file, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)

            # Expected data based on answer.csv
            expected_data = {
                "version_number": ["5", "6", "7", "8"],
                "name": ["Bill Harvey", "Michelle Jackson", "Michelle Jackson", "Tony Taylor"]
            }

            # Expected header columns (excluding first column which can be anything)
            expected_header_columns = ["4.6", "4.16", "6.8", "6.16"]

            # Verify header has correct number of columns
            header = rows[0]
            if len(header) != 5:  # First column + 4 clauses
                msg = (f"Header row has incorrect number of columns: "
                       f"{len(header)}, expected 5")
                print(f"❌ {msg}")
                return False, msg

            # Check if all expected clause columns are present (allow order to be different)
            # Allow first column to be anything, so we check columns 1-4
            header_clauses = header[1:5]
            missing_clauses = []
            for expected_clause in expected_header_columns:
                if expected_clause not in header_clauses:
                    missing_clauses.append(expected_clause)

            if missing_clauses:
                print(f"❌ Missing expected clause columns: {missing_clauses}")
                return False, f"Missing expected clause columns: {missing_clauses}"

            # Check if there are extra clause columns
            extra_clauses = []
            for clause in header_clauses:
                if clause not in expected_header_columns:
                    extra_clauses.append(clause)

            if extra_clauses:
                print(f"❌ Unexpected extra clause columns: {extra_clauses}")
                return False, f"Unexpected extra clause columns: {extra_clauses}"

            # Create a mapping from expected clause order to actual column indices
            clause_mapping = {}
            for i, clause in enumerate(header_clauses):
                if clause in expected_header_columns:
                    clause_mapping[clause] = i

            # Parse the CSV data into a dictionary with correct column mapping
            csv_data = {}
            for row in rows[1:]:
                if len(row) >= 5:
                    row_type = row[0]  # version_number or name
                    # Map values according to the expected clause order
                    values = []
                    for expected_clause in expected_header_columns:
                        # +1 because we skip first column
                        col_index = clause_mapping[expected_clause] + 1
                        values.append(row[col_index])
                    csv_data[row_type] = values

            # Check if all expected row types are present
            missing_types = []
            for expected_type in expected_data:
                if expected_type not in csv_data:
                    missing_types.append(expected_type)

            if missing_types:
                print(f"❌ Missing expected row types: {missing_types}")
                return False, f"Missing expected row types: {missing_types}"

            # Check if there are extra row types
            extra_types = []
            for row_type in csv_data:
                if row_type not in expected_data:
                    extra_types.append(row_type)

            if extra_types:
                print(f"❌ Unexpected extra row types: {extra_types}")
                return False, f"Unexpected extra row types: {extra_types}"

            # Check values for each row type
            for row_type, expected_values in expected_data.items():
                actual_values = csv_data[row_type]

                if actual_values != expected_values:
                    print(f"❌ Values mismatch for {row_type}:")
                    print(f"   Expected: {expected_values}")
                    print(f"   Got:      {actual_values}")
                    return False, f"Values mismatch for {row_type}"

            print("✅ CSV content matches expected answer exactly")
            return True, ""

    except (OSError, ValueError) as error:
        print(f"❌ Error verifying CSV content: {error}")
        return False, f"Error verifying CSV content: {error}"

def verify_data_accuracy(test_dir: Path) -> tuple:  # pylint: disable=R1702
    """Verify that the data values are accurate."""
    output_file = test_dir / "tracing.csv"

    try:
        with open(output_file, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            rows = list(reader)

            # Skip header row
            for i, row in enumerate(rows[1:], 1):
                if len(row) >= 5:
                    row_type = row[0]
                    values = row[1:5]

                    # Check version_number row
                    if row_type == "version_number":
                        for j, value in enumerate(values, 1):
                            try:
                                int_val = int(value)
                                if int_val < 5 or int_val > 8:
                                    msg = (f"Row {i}, column {j}: version number "
                                           f"'{value}' is out of expected range [5-8]")
                                    print(f"❌ {msg}")
                                    return False, msg
                            except ValueError:
                                msg = (f"Row {i}, column {j}: non-integer "
                                       f"version number '{value}'")
                                print(f"❌ {msg}")
                                return False, msg

                    # Check name row
                    elif row_type == "name":
                        expected_names = ["Bill Harvey",
                                          "Michelle Jackson",
                                          "Michelle Jackson",
                                          "Tony Taylor"]
                        for j, value in enumerate(values, 1):
                            if value not in expected_names:
                                print(f"❌ Row {i}, column {j}: unexpected name '{value}'")
                                return False, f"Row {i}, column {j}: unexpected name '{value}'"

            print("✅ All data values are accurate")
            return True, ""

    except (OSError, ValueError) as error:
        print(f"❌ Error verifying data accuracy: {error}")
        return False, f"Error verifying data accuracy: {error}"

def verify_file_location(test_dir: Path) -> tuple:
    """Verify that the file is in the main directory (not in a subdirectory)."""
    output_file = test_dir / "tracing.csv"

    if output_file.exists():
        print("✅ File is located in the main directory")
        return True, ""
    print("❌ File is not in the main directory")
    return False, "File is not in the main directory"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Legal Document Solution Tracing Task...")

    # Define verification steps
    verification_steps = [
        ("Output File Exists", verify_output_file_exists),
        ("CSV Format", verify_csv_format),
        ("CSV Content", verify_csv_content),
        ("Data Accuracy", verify_data_accuracy),
        ("File Location", verify_file_location),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Legal document solution tracing task completed correctly!")
    print("🎉 Task verification: PASS")
    return True, ""

def main():
    """Main verification function."""
    test_dir = get_test_directory()
    passed, error_msg = verify(test_dir)

    if passed:
        sys.exit(0)
    else:
        print(f"\n❌ Task verification: FAIL - {error_msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()
