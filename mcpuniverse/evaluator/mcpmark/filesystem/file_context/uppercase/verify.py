#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for File Context Task: Convert Files to Uppercase
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
        category = meta.get("category_id", "file_context")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_uppercase_directory_exists(test_dir: Path) -> tuple:
    """Verify that the uppercase directory exists."""
    uppercase_dir = test_dir / "uppercase"

    if not uppercase_dir.exists():
        print("| ❌ Directory 'uppercase' not found")
        return False, "Directory 'uppercase' not found"

    if not uppercase_dir.is_dir():
        print("| ❌ 'uppercase' exists but is not a directory")
        return False, "'uppercase' exists but is not a directory"

    print("| ✓ Uppercase directory found")
    return True, ""

def verify_uppercase_files_exist(test_dir: Path) -> tuple:
    """Verify that all 10 uppercase files exist."""
    uppercase_dir = test_dir / "uppercase"

    for i in range(1, 11):
        filename = f"file_{i:02d}.txt"
        file_path = uppercase_dir / filename

        if not file_path.exists():
            print(f"| ❌ File '{filename}' not found in uppercase directory")
            return False, f"File '{filename}' not found in uppercase directory"

    print("| ✓ All 10 uppercase files found")
    return True, ""

def verify_uppercase_content(test_dir: Path) -> tuple:
    """Verify that uppercase files contain the correct uppercase content."""
    uppercase_dir = test_dir / "uppercase"

    for i in range(1, 11):
        filename = f"file_{i:02d}.txt"
        original_file = test_dir / filename
        uppercase_file = uppercase_dir / filename

        if not original_file.exists():
            print(f"| ❌ Original file '{filename}' not found")
            return False, f"Original file '{filename}' not found"

        try:
            original_content = original_file.read_text()
            uppercase_content = uppercase_file.read_text()

            # Check if uppercase content is the uppercase version of original
            expected_uppercase = original_content.upper()

            if uppercase_content != expected_uppercase:
                print(f"| ❌ File '{filename}' content is not properly converted to uppercase")
                return False, f"File '{filename}' content is not properly converted to uppercase"

        except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
            print(f"| ❌ Error reading file '{filename}': {e}")
            return False, f"Error reading file '{filename}': {e}"

    print("| ✓ All uppercase files contain correct uppercase content")
    return True, ""

def verify_answer_file_exists(test_dir: Path) -> tuple:
    """Verify that the answer.txt file exists in the uppercase directory."""
    uppercase_dir = test_dir / "uppercase"
    answer_file = uppercase_dir / "answer.txt"

    if not answer_file.exists():
        print("| ❌ File 'answer.txt' not found in uppercase directory")
        return False, "File 'answer.txt' not found in uppercase directory"

    print("| ✓ Answer file found in uppercase directory")
    return True, ""

def verify_answer_format(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the answer file has the correct format."""
    uppercase_dir = test_dir / "uppercase"
    answer_file = uppercase_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        if not content:
            print("| ❌ Answer file is empty")
            return False, "Answer file is empty"

        lines = content.split('\n')

        # Check if we have exactly 10 lines
        if len(lines) != 10:
            print(f"| ❌ Answer file has {len(lines)} lines, expected 10")
            return False, f"Answer file has {len(lines)} lines, expected 10"

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                print(f"| ❌ Line {i} is empty")
                return False, f"Line {i} is empty"

            # Check format: filename:word_count
            if ':' not in line:
                print(f"| ❌ Line {i} has incorrect format: {line}")
                print("   Expected format: filename:word_count")
                return False, f"Line {i} has incorrect format: {line}"

            parts = line.split(':', 1)
            if len(parts) != 2:
                print(f"| ❌ Line {i} has incorrect format: {line}")
                print("   Expected format: filename:word_count")
                return False, f"Line {i} has incorrect format: {line}"

            filename, word_count_str = parts

            # Check filename format
            if not filename.endswith('.txt') or not filename.startswith('file_'):
                print(f"| ❌ Line {i} has invalid filename: {filename}")
                return False, f"Line {i} has invalid filename: {filename}"

            # Check word count format (should be integer)
            try:
                word_count = int(word_count_str)
                if word_count <= 0:
                    print(f"| ❌ Line {i} has invalid word count: {word_count_str}")
                    return False, f"Line {i} has invalid word count: {word_count_str}"
            except ValueError:
                print(f"| ❌ Line {i} has non-integer word count: {word_count_str}")
                return False, f"Line {i} has non-integer word count: {word_count_str}"

        print("| ✓ Answer format is correct")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"| ❌ Error reading answer file: {e}")
        return False, f"Error reading answer file: {e}"

def count_words_in_file(file_path: Path) -> int:
    """Count words in a file."""
    try:
        content = file_path.read_text()
        # Split by whitespace and filter out empty strings
        words = [word for word in content.split() if word.strip()]
        return len(words)
    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"| ❌ Error reading file {file_path}: {e}")
        return 0

def verify_word_counts_are_correct(test_dir: Path) -> tuple:
    """Verify that the word counts in answer.txt are correct."""
    uppercase_dir = test_dir / "uppercase"
    answer_file = uppercase_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()
        lines = content.split('\n')

        # Expected word counts based on answer.md
        expected_counts = [22, 22, 22, 22, 18, 22, 22, 22, 18, 20]

        # Create a set of expected file entries for easier checking
        expected_entries = set()
        for i in range(1, 11):
            filename = f"file_{i:02d}.txt"
            expected_count = expected_counts[i - 1]
            if i == 6:  # Special case for file_06.txt: can be 21 or 22
                expected_entries.add(f"{filename}:21")
                expected_entries.add(f"{filename}:22")
            else:
                expected_entries.add(f"{filename}:{expected_count}")

        # Check each line in the answer file
        found_entries = set()
        for line in lines:
            line = line.strip()
            if line in expected_entries:
                found_entries.add(line)
            else:
                print(f"| ❌ Invalid entry: {line}")
                return False, f"Invalid entry: {line}"

        # Check if we found all expected entries
        if len(found_entries) != 10:
            print(f"| ❌ Found {len(found_entries)} entries, expected 10")
            missing = expected_entries - found_entries
            if missing:
                print(f"   Missing entries: {missing}")
            return False, f"Found {len(found_entries)} entries, expected 10"

        print("| ✓ All word counts are correct")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"| ❌ Error verifying word counts: {e}")
        return False, f"Error verifying word counts: {e}"

def verify_all_files_are_included(test_dir: Path) -> tuple:
    """Verify that all 10 files are included in the answer."""
    uppercase_dir = test_dir / "uppercase"
    answer_file = uppercase_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()
        lines = content.split('\n')

        # Check that all 10 files are present
        found_files = set()
        for line in lines:
            parts = line.split(':', 1)
            filename = parts[0]
            found_files.add(filename)

        expected_files = {f"file_{i:02d}.txt" for i in range(1, 11)}

        if found_files != expected_files:
            missing = expected_files - found_files
            extra = found_files - expected_files
            if missing:
                print(f"| ❌ Missing files in answer: {missing}")
            if extra:
                print(f"| ❌ Extra files in answer: {extra}")
            return False, f"Missing files: {missing}, Extra files: {extra}"

        print("| ✓ All 10 files are included in answer")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"| ❌ Error verifying file inclusion: {e}")
        return False, f"Error verifying file inclusion: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print(f"| 🔍 Verifying Uppercase in: {test_dir}")
    print('|')

    # Run all verification checks
    checks = [
        ("Uppercase directory exists", verify_uppercase_directory_exists),
        ("Uppercase files exist", verify_uppercase_files_exist),
        ("Uppercase content is correct", verify_uppercase_content),
        ("Answer file exists in uppercase directory", verify_answer_file_exists),
        ("Answer format is correct", verify_answer_format),
        ("All files are included", verify_all_files_are_included),
        ("Word counts are correct", verify_word_counts_are_correct),
    ]

    for check_name, check_func in checks:
        print(f"| Checking {check_name}...")
        passed, error_msg = check_func(test_dir)
        if not passed:
            return False, error_msg
        print('|')

    print("| 🎉 All verification checks passed!")
    return True, ""

def main():
    """Main verification function."""
    try:
        test_dir = get_test_directory()
        passed, error_msg = verify(test_dir)

        if passed:
            sys.exit(0)
        else:
            print(f"| ❌ Verification failed: {error_msg}")
            sys.exit(1)

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"| ❌ Verification failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
