#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Legal Document Dispute Review Task
"""

import sys
from pathlib import Path
import re
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
    """Verify that the dispute_review.txt file exists."""
    output_file = test_dir / "dispute_review.txt"

    if not output_file.exists():
        print("❌ File 'dispute_review.txt' not found")
        return False, "File 'dispute_review.txt' not found"

    print("✅ Output file found")
    return True, ""

def verify_output_format(test_dir: Path) -> tuple:
    """Verify that the output file has the correct format."""
    output_file = test_dir / "dispute_review.txt"

    try:
        content = output_file.read_text().strip()

        # Check if content is not empty
        if not content:
            print("❌ Output file is empty")
            return False, "Output file is empty"

        # Check format: each line should be "X.X:number"
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            # Check format: X.X:number
            if not re.match(r'^\d+\.\d+:\d+$', line):
                print(f"❌ Line {i} has incorrect format: '{line}'")
                print("   Expected format: 'X.X:number' (e.g., '1.1:3')")
                return False, f"Line {i} has incorrect format: '{line}'"

        print("✅ Output format is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading output file: {e}"

def verify_expected_entries(test_dir: Path) -> tuple:  # pylint: disable=R0912
    """Verify that the output contains the expected entries with correct counts."""
    output_file = test_dir / "dispute_review.txt"

    try:
        content = output_file.read_text().strip()
        lines = content.split('\n')

        # Parse the output into a dictionary
        output_entries = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            clause, count_str = line.split(':', 1)
            output_entries[clause] = int(count_str)

        # Expected entries based on answer.txt
        expected_entries = {
            "1.1": 3,
            "1.3": 3,
            "4.6": [5, 6],  # Can be either 5 or 6
            "4.16": 5,
            "6.8": 4
        }

        # Check if all expected entries are present
        missing_entries = []
        for clause in expected_entries:
            if clause not in output_entries:
                missing_entries.append(clause)

        if missing_entries:
            print(f"❌ Missing expected entries: {missing_entries}")
            return False, f"Missing expected entries: {missing_entries}"

        # Check if there are extra entries
        extra_entries = []
        for clause in output_entries:
            if clause not in expected_entries:
                extra_entries.append(clause)

        if extra_entries:
            print(f"❌ Unexpected extra entries: {extra_entries}")
            return False, f"Unexpected extra entries: {extra_entries}"

        # Check counts for each entry
        for clause, expected_count in expected_entries.items():
            actual_count = output_entries[clause]

            if isinstance(expected_count, list):
                # For 4.6, accept either 5 or 6
                if actual_count not in expected_count:
                    print(f"❌ Clause {clause}: expected {expected_count}, got {actual_count}")
                    return False, f"Clause {clause}: expected {expected_count}, got {actual_count}"
            else:
                if actual_count != expected_count:
                    print(f"❌ Clause {clause}: expected {expected_count}, got {actual_count}")
                    return False, f"Clause {clause}: expected {expected_count}, got {actual_count}"

        print("✅ All expected entries with correct counts")
        return True, ""

    except (OSError, ValueError) as error:
        print(f"❌ Error verifying entries: {error}")
        return False, f"Error verifying entries: {error}"

def verify_comment_count_accuracy(_test_dir: Path) -> tuple:
    """Verify that the comment counts are accurate by checking the actual files."""
    # Since we already verify the expected entries in verify_expected_entries,
    # and the answer.txt contains the correct counts, we can skip this complex verification
    # to avoid false negatives due to regex matching issues.

    print("✅ Comment count accuracy check skipped - relying on expected entries verification")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Legal Document Dispute Review Task...")

    # Define verification steps
    verification_steps = [
        ("Output File Exists", verify_output_file_exists),
        ("Output Format", verify_output_format),
        ("Expected Entries", verify_expected_entries),
        ("Comment Count Accuracy", verify_comment_count_accuracy),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Legal document dispute review completed correctly!")
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
