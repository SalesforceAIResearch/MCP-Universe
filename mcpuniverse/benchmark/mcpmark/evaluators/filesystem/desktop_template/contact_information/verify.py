#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Contact Information Compilation Task
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
        category = meta.get("category_id", "desktop_template")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_contact_info_csv_exists(test_dir: Path) -> tuple:
    """Verify that the contact_info.csv file exists in the main directory."""
    contact_file = test_dir / "contact_info.csv"

    if not contact_file.exists():
        print("❌ File 'contact_info.csv' not found in main directory")
        return False, "File 'contact_info.csv' not found in main directory"

    print("✅ contact_info.csv file found")
    return True, ""

def verify_answer_txt_exists(test_dir: Path) -> tuple:
    """Verify that the answer.txt file exists in the main directory."""
    answer_file = test_dir / "answer.txt"

    if not answer_file.exists():
        print("❌ File 'answer.txt' not found in main directory")
        return False, "File 'answer.txt' not found in main directory"

    print("✅ answer.txt file found")
    return True, ""

def verify_csv_structure(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the CSV file has the correct structure."""
    contact_file = test_dir / "contact_info.csv"

    try:
        with open(contact_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        if len(rows) < 2:  # Need at least header + 1 data row
            print("❌ CSV file has insufficient rows")
            return False, "CSV file has insufficient rows"

        headers = rows[0]
        if not headers:
            print("❌ CSV file has no headers")
            return False, "CSV file has no headers"

        # Check that Name is the first column
        if headers[0].lower() != 'name':
            print("❌ First column is not 'Name'")
            return False, "First column is not 'Name'"

        # Check that Email and Phone are present (order may vary)
        header_lower = [h.lower() for h in headers]
        if 'email' not in header_lower:
            print("❌ 'Email' column not found")
            return False, "'Email' column not found"

        if 'phone' not in header_lower:
            print("❌ 'Phone' column not found")
            return False, "'Phone' column not found"

        print("✅ CSV structure is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading CSV file: {e}"

def verify_csv_content_accuracy(test_dir: Path) -> tuple:  # pylint: disable=R1702,R0912,R0914
    """Verify that the CSV content contains all required data,
    regardless of row order or extra entries.
    """
    contact_file = test_dir / "contact_info.csv"

    try:
        with open(contact_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Expected data from answer.csv (hardcoded as required)
        expected_data = [
            {"Name": "John Smith", "Email": "john@email.com",
             "Phone": "555-0101", "Status": "", "Industry": ""},
            {"Name": "Jane Doe", "Email": "jane@email.com",
             "Phone": "555-0102", "Status": "", "Industry": ""},
            {"Name": "Bob Johnson", "Email": "bob@email.com",
             "Phone": "555-0103", "Status": "", "Industry": ""},
            {"Name": "Alice Brown", "Email": "alice@email.com",
             "Phone": "555-0201", "Status": "Inactive", "Industry": ""},
            {"Name": "Charlie Davis", "Email": "charlie@email.com",
             "Phone": "555-0202", "Status": "Active", "Industry": ""},
            {"Name": "David Wilson", "Email": "david@email.com",
             "Phone": "555-0203", "Status": "Inactive", "Industry": ""},
            {"Name": "Acme Corp", "Email": "acme@corp.com",
             "Phone": "", "Status": "", "Industry": "Technology"},
            {"Name": "Global Inc", "Email": "global@inc.com",
             "Phone": "", "Status": "", "Industry": "Finance"},
            {"Name": "Local Business", "Email": "local@biz.com",
             "Phone": "", "Status": "", "Industry": "Retail"},
            {"Name": "Spouse", "Email": "", "Phone": "+1-555-0124",
             "Status": "", "Industry": ""},
            {"Name": "Parent", "Email": "", "Phone": "+1-555-0125",
             "Status": "", "Industry": ""},
            {"Name": "Sibling", "Email": "", "Phone": "+1-555-0126",
             "Status": "", "Industry": ""},
            {"Name": "Primary Doctor", "Email": "",
             "Phone": "+1-555-0201", "Status": "", "Industry": ""},
            {"Name": "Dentist", "Email": "", "Phone": "+1-555-0202",
             "Status": "", "Industry": ""},
            {"Name": "Pharmacy", "Email": "", "Phone": "+1-555-0203",
             "Status": "", "Industry": ""}
        ]

        # Convert expected data to a dictionary for easier lookup
        # We'll use Name as the key since it should be unique
        expected_dict = {}
        for entry in expected_data:
            expected_dict[entry["Name"]] = entry

        # Check each row for accuracy, regardless of order
        # Allow extra entries and mixed content
        found_entries = set()
        extra_entries = []

        for row in rows:
            row_name = row.get('Name', '')
            if not row_name:
                # Skip rows without names (they're not valid entries)
                continue

            if row_name in expected_dict:
                # This is one of our expected entries
                if row_name in found_entries:
                    print(f"❌ Duplicate name found: '{row_name}'")
                    return False, f"Duplicate name found: '{row_name}'"

                found_entries.add(row_name)
                expected = expected_dict[row_name]

                # Check all columns for this entry
                for key, expected_value in expected.items():
                    if key in row:
                        actual_value = row[key] if row[key] else ""
                        if actual_value != expected_value:
                            msg = (f"Entry '{row_name}', column '{key}': "
                                   f"expected '{expected_value}', "
                                   f"got '{actual_value}'")
                            print(f"❌ {msg}")
                            return False, msg
                    else:
                        print(f"❌ Entry '{row_name}' missing column '{key}'")
                        return False, f"Entry '{row_name}' missing column '{key}'"
            else:
                # This is an extra entry - record it for informational purposes
                extra_entries.append(row_name)

        # Verify all expected entries were found
        if len(found_entries) != len(expected_data):
            missing = set(expected_dict.keys()) - found_entries
            print(f"❌ Missing entries: {missing}")
            return False, f"Missing entries: {missing}"

        # Report extra entries if any
        if extra_entries:
            print(f"ℹ️  Found {len(extra_entries)} extra entries: {extra_entries}")

        msg = (f"CSV content accuracy verified: found all "
               f"{len(expected_data)} required entries "
               f"(plus {len(extra_entries)} extra entries)")
        print(f"✅ {msg}")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying CSV content: {e}")
        return False, f"Error verifying CSV content: {e}"

def verify_csv_data_completeness(test_dir: Path) -> tuple:
    """Verify that all required data is present and no entries are missing."""
    contact_file = test_dir / "contact_info.csv"

    try:
        with open(contact_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Check that all expected names are present
        expected_names = [
            "John Smith", "Jane Doe", "Bob Johnson", "Alice Brown",
            "Charlie Davis", "David Wilson", "Acme Corp", "Global Inc",
            "Local Business", "Spouse", "Parent", "Sibling",
            "Primary Doctor", "Dentist", "Pharmacy"
        ]

        actual_names = [row.get('Name', '') for row in rows if row.get('Name')]

        missing_names = set(expected_names) - set(actual_names)
        if missing_names:
            print(f"❌ Missing names: {missing_names}")
            return False, f"Missing names: {missing_names}"

        extra_names = set(actual_names) - set(expected_names)
        if extra_names:
            print(f"⚠️  Extra names found: {extra_names}")
            # This is a warning, not an error

        print("✅ CSV data completeness verified")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking data completeness: {e}")
        return False, f"Error checking data completeness: {e}"

def verify_answer_content(test_dir: Path) -> tuple:
    """Verify that the answer.txt contains the correct answer about Charlie Davis."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip().lower()

        # The answer should contain "dentist" (as per answer.txt)
        if "dentist" in content:
            print("✅ Answer about Charlie Davis's job is correct")
            return True, ""
        print(f"❌ Answer does not contain 'dentist'. Found: '{content}'")
        return False, f"Answer does not contain 'dentist'. Found: '{content}'"

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error reading answer.txt: {e}")
        return False, f"Error reading answer.txt: {e}"

def verify_file_locations(test_dir: Path) -> tuple:
    """Verify that files are in the correct locations."""
    contact_file = test_dir / "contact_info.csv"
    answer_file = test_dir / "answer.txt"

    # Check that files are in the main directory, not in subdirectories
    if contact_file.parent != test_dir:
        msg = f"contact_info.csv is not in main directory: {contact_file}"
        print(f"❌ {msg}")
        return False, msg

    if answer_file.parent != test_dir:
        msg = f"answer.txt is not in main directory: {answer_file}"
        print(f"❌ {msg}")
        return False, msg

    print("✅ Files are in correct locations")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Contact Information Compilation Task...")

    # Define verification steps
    verification_steps = [
        ("Contact Info CSV Exists", verify_contact_info_csv_exists),
        ("Answer TXT Exists", verify_answer_txt_exists),
        ("Files in Correct Locations", verify_file_locations),
        ("CSV Structure", verify_csv_structure),
        ("CSV Content Accuracy (Flexible)", verify_csv_content_accuracy),
        ("CSV Data Completeness", verify_csv_data_completeness),
        ("Answer Content", verify_answer_content),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Contact Information Compilation Task completed successfully!")
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
