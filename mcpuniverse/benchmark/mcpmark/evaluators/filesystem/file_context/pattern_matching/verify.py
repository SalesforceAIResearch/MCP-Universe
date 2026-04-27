#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for File Filtering Task: Find Files with Common Substring
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

def verify_answer_file_exists(test_dir: Path) -> tuple:
    """Verify that the answer.txt file exists."""
    answer_file = test_dir / "answer.txt"

    if not answer_file.exists():
        print("❌ File 'answer.txt' not found")
        return False, "File 'answer.txt' not found"

    print("✅ Answer file found")
    return True, ""

def verify_answer_format(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the answer file has the correct format."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # If file is empty, that's acceptable (no matches found)
        if not content:
            print("✅ Answer file is empty (no matches found)")
            return True, ""

        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            # Check format: filename.txt,start_position
            parts = line.split(',')
            if len(parts) != 2:
                print(f"❌ Line {i} has incorrect format: {line}")
                print("   Expected format: filename.txt,start_position")
                return False, f"Line {i} has incorrect format: {line}"

            filename, start_pos = parts

            # Check filename format
            if not filename.endswith('.txt') or not filename.startswith('file_'):
                print(f"❌ Line {i} has invalid filename: {filename}")
                return False, f"Line {i} has invalid filename: {filename}"

            # Check position format (should be integer)
            try:
                start_int = int(start_pos)
                if start_int <= 0:
                    print(f"❌ Line {i} has invalid position: {start_pos}")
                    return False, f"Line {i} has invalid position: {start_pos}"
            except ValueError:
                print(f"❌ Line {i} has non-integer position: {start_pos}")
                return False, f"Line {i} has non-integer position: {start_pos}"

        print("✅ Answer format is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading answer file: {e}"

def find_30_plus_char_matches(test_dir: Path) -> dict:
    """Find all matches with 30 or more characters between files and large_file.txt."""
    large_file = test_dir / "large_file.txt"
    if not large_file.exists():
        print("❌ large_file.txt not found")
        return {}

    large_content = large_file.read_text()
    matches = {}

    # Check each file from file_01.txt to file_20.txt
    for i in range(1, 21):
        filename = f"file_{i:02d}.txt"
        file_path = test_dir / filename

        if not file_path.exists():
            continue

        file_content = file_path.read_text()

        # Find the longest matching substring (30+ characters)
        longest_match = ""
        longest_match_start = -1

        # Check all possible substrings in the file
        for start_pos in range(len(file_content)):
            for end_pos in range(start_pos + 30, len(file_content) + 1):  # At least 30 characters
                substring = file_content[start_pos:end_pos]

                # Check if this substring exists in large_file.txt
                if substring in large_content:
                    if len(substring) > len(longest_match):
                        longest_match = substring
                        # Find the position in large_file.txt where this substring starts
                        large_start_pos = large_content.find(substring)
                        longest_match_start = large_start_pos + 1  # 1-indexed

        # If we found a match of 30+ characters, record it
        if longest_match and len(longest_match) >= 30:
            matches[filename] = longest_match_start

    return matches

def verify_matches_are_correct(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the matches found in answer.txt are actually correct."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # If no content, check if there should actually be no matches
        if not content:
            expected_matches = find_30_plus_char_matches(test_dir)
            if expected_matches:
                print("❌ Answer file is empty but matches should exist")
                for filename, start_pos in expected_matches.items():
                    print(f"   Expected: {filename},{start_pos}")
                msg = (f"Answer file is empty but matches should exist: "
                       f"{list(expected_matches.keys())}")
                return False, msg
            print("✅ No matches found (correct)")
            return True, ""

        # Parse answer file
        answer_matches = {}
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            filename, start_pos = line.split(',')
            answer_matches[filename] = int(start_pos)

        # Get expected matches
        expected_matches = find_30_plus_char_matches(test_dir)

        # Check if all answer matches are correct
        for filename, start_pos in answer_matches.items():
            if filename not in expected_matches:
                print(f"❌ File {filename} listed in answer but has no valid 30+ character match")
                msg = (f"File {filename} listed in answer but has no valid "
                       f"30+ character match")
                return False, msg

            expected_start = expected_matches[filename]
            if start_pos != expected_start:
                print(f"❌ Incorrect match position for {filename}")
                print(f"   Expected: {expected_start}")
                print(f"   Found: {start_pos}")
                msg = (f"Incorrect match position for {filename}. "
                       f"Expected: {expected_start}, Found: {start_pos}")
                return False, msg

        # Check if all expected matches are in answer
        for filename in expected_matches:
            if filename not in answer_matches:
                print(f"❌ Missing match for {filename} in answer file")
                return False, f"Missing match for {filename} in answer file"

        print("✅ All matches are correct")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying matches: {e}")
        return False, f"Error verifying matches: {e}"

def verify_match_length_is_30_plus(test_dir: Path) -> tuple:  # pylint: disable=R0914
    """Verify that all matches are at least 30 characters long."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        if not content:
            return True, ""  # No matches to verify

        large_file = test_dir / "large_file.txt"
        large_content = large_file.read_text()

        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            filename, start_pos = line.split(',')
            start_int = int(start_pos)

            # Get the file content to check the match
            file_path = test_dir / filename
            file_content = file_path.read_text()

            # Find the longest matching substring starting from the given position
            longest_match = ""
            # At least 30 characters
            for end_pos in range(start_int + 30 - 1, len(large_content) + 1):
                # Convert to 0-indexed
                substring = large_content[start_int - 1:end_pos]
                if substring in file_content:
                    longest_match = substring
                else:
                    break

            if len(longest_match) < 30:
                msg = (f"Match in {filename} is {len(longest_match)} "
                       f"characters, less than 30")
                print(f"❌ {msg}")
                print(f"   Starting position: {start_int}")
                return False, msg

        print("✅ All matches are at least 30 characters long")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying match lengths: {e}")
        return False, f"Error verifying match lengths: {e}"

def verify_files_exist(test_dir: Path) -> tuple:
    """Verify that all files mentioned in answer.txt actually exist."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        if not content:
            return True, ""  # No files to verify

        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            filename = line.split(',')[0]
            file_path = test_dir / filename

            if not file_path.exists():
                print(f"❌ File mentioned in answer does not exist: {filename}")
                return False, f"File mentioned in answer does not exist: {filename}"

        print("✅ All files mentioned in answer exist")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying file: {e}")
        return False, f"Error verifying file existence: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Pattern Matching Task: Find Files with Common Substring...")

    # Define verification steps
    verification_steps = [
        ("Answer File Exists", verify_answer_file_exists),
        ("Answer Format", verify_answer_format),
        ("Files Exist", verify_files_exist),
        ("Match Length is 30+", verify_match_length_is_30_plus),
        ("Matches are Correct", verify_matches_are_correct),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ File filtering task completed correctly!")
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
