#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Student Database Grade-Based Score Analysis Task
"""

import sys
from pathlib import Path
import os
import re
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
        category = meta.get("category_id", "student_database")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_grade_summary_exists(test_dir: Path) -> tuple:
    """Verify that grade_summary.txt file exists."""
    grade_summary_file = test_dir / "grade_summary.txt"

    if not grade_summary_file.exists():
        print("❌ File 'grade_summary.txt' not found")
        return False, "File 'grade_summary.txt' not found"

    print("✅ grade_summary.txt file found")
    return True, ""

def verify_grade_summary_readable(test_dir: Path) -> tuple:
    """Verify that the grade_summary.txt file is readable."""
    grade_summary_file = test_dir / "grade_summary.txt"

    try:
        content = grade_summary_file.read_text()
        if not content.strip():
            print("❌ grade_summary.txt file is empty")
            return False, "grade_summary.txt file is empty"

        print("✅ grade_summary.txt file is readable")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading grade_summary.txt file: {e}"

def extract_numbers_from_text(text: str) -> list:
    """Extract all numbers from text."""
    numbers = re.findall(r'\d+', text)
    return [int(num) for num in numbers]

def verify_three_subjects_present(test_dir: Path) -> tuple:
    """Verify that grade_summary.txt contains all three subjects (case insensitive)."""
    grade_summary_file = test_dir / "grade_summary.txt"

    try:
        content = grade_summary_file.read_text()

        # Check if all three subjects are mentioned (case insensitive)
        subjects = ["chinese", "math", "english"]
        missing_subjects = []

        for subject in subjects:
            if subject.lower() not in content.lower():
                missing_subjects.append(subject)

        if missing_subjects:
            print(f"❌ Missing subjects in grade_summary.txt: {missing_subjects}")
            return False, f"Missing subjects in grade_summary.txt: {missing_subjects}"

        print("✅ All three subjects (Chinese, Math, English) found in grade_summary.txt")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking subjects: {e}")
        return False, f"Error checking subjects: {e}"

def verify_grade_summary_content(test_dir: Path) -> tuple:
    """Verify that grade_summary.txt contains the correct statistics from answer.md."""
    grade_summary_file = test_dir / "grade_summary.txt"

    try:
        content = grade_summary_file.read_text()

        # Extract all numbers from the content
        found_numbers = extract_numbers_from_text(content)

        if not found_numbers:
            print("❌ No numbers found in grade_summary.txt")
            return False

        # Expected numbers from answer.md
        # Format: [total_students, chinese_A, chinese_B, chinese_C, chinese_D,
        #          chinese_pass, chinese_fail, math_A, math_B, math_C, math_D,
        #          math_pass, math_fail, english_A, english_B, english_C,
        #          english_D, english_F, english_pass, english_fail]
        expected_numbers = [
            # Total students
            150,
            # Chinese grades: A(42), B(37), C(43), D(28), Pass(122), Fail(28)
            42, 37, 43, 28, 122, 28,
            # Math grades: A(31), B(38), C(47), D(34), Pass(116), Fail(34)
            31, 38, 47, 34, 116, 34,
            # English grades: A(32), B(38), C(38), D(41), F(1), Pass(108), Fail(42)
            32, 38, 38, 41, 1, 108, 42
        ]

        # Check if all expected numbers are present in the found numbers
        missing_numbers = []
        for expected in expected_numbers:
            if expected not in found_numbers:
                missing_numbers.append(expected)

        if missing_numbers:
            print(f"❌ Missing expected numbers: {missing_numbers}")
            print(f"   Found numbers: {found_numbers}")
            return False, f"Missing expected numbers: {missing_numbers}"

        # Check if the counts match (each number should appear the expected number of times)
        for expected in expected_numbers:
            expected_count = expected_numbers.count(expected)
            found_count = found_numbers.count(expected)
            if found_count < expected_count:
                msg = (f"Number {expected} appears {found_count} times, "
                       f"expected {expected_count} times")
                print(f"❌ {msg}")
                return False, msg

        print("✅ All expected grade statistics found in grade_summary.txt")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying grade summary content: {e}")
        return False, f"Error verifying grade summary content: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print(f"🔍 Verifying Student Database Grade-Based Score Analysis in: {test_dir}")

    # Define verification steps
    verification_steps = [
        ("Grade Summary File Exists", verify_grade_summary_exists),
        ("File is Readable", verify_grade_summary_readable),
        ("Three Subjects Present", verify_three_subjects_present),
        ("Grade Statistics Content", verify_grade_summary_content),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Student grade analysis completed correctly!")
    print("🎉 Grade-Based Score Analysis verification: PASS")
    return True, ""

def main():
    """Main verification function."""
    try:
        test_dir = get_test_directory()
        passed, error_msg = verify(test_dir)

        if passed:
            sys.exit(0)
        else:
            print(f"\n❌ Grade-Based Score Analysis verification: FAIL - {error_msg}")
            sys.exit(1)

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Verification failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
