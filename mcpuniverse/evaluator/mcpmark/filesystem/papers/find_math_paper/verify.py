#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Find Math Paper Task
"""

import sys
from pathlib import Path
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
        category = meta.get("category_id", "papers")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_answer_file_exists(test_dir: Path) -> tuple:
    """Verify that answer.html exists in the papers directory."""
    answer_file = test_dir  / "answer.html"

    if not answer_file.exists():
        print("❌ File 'answer.html' not found")
        return False, "File 'answer.html' not found"

    print("✅ answer.html found")
    return True, ""

def verify_original_file_removed(test_dir: Path) -> tuple:
    """Verify that the original file (2407.01284.html) no longer exists."""
    original_file = test_dir  / "2407.01284.html"

    if original_file.exists():
        print("❌ Original file 2407.01284.html still exists")
        return False, "Original file 2407.01284.html still exists"

    print("✅ Original file has been renamed")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Find Math Paper Task...")

    # Define verification steps
    verification_steps = [
        ("Answer File Exists", verify_answer_file_exists),
        ("Original File Renamed", verify_original_file_removed),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Paper correctly renamed to answer.html!")
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
