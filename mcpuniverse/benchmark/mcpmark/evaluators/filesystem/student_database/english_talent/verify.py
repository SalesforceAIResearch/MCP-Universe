#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Student Database Task: English Talent Recruitment
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
        category = meta.get("category_id", "student_database")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_qualified_students_file_exists(test_dir: Path) -> tuple:
    """Verify that the qualified_students.txt file exists."""
    answer_file = test_dir / "qualified_students.txt"

    if not answer_file.exists():
        print("❌ File 'qualified_students.txt' not found")
        return False, "File 'qualified_students.txt' not found"

    print("✅ Qualified students file found")
    return True, ""

def verify_file_format(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the qualified_students.txt file has the correct format."""
    answer_file = test_dir / "qualified_students.txt"

    try:
        content = answer_file.read_text()
        lines = content.strip().split('\n')

        if not lines:
            print("❌ File is empty")
            return False

        # Check if content follows the expected pattern
        # Each student should have 3 lines: name, id, email
        # Students should be separated by blank lines
        current_line = 0
        student_count = 0

        while current_line < len(lines):
            # Skip blank lines
            if not lines[current_line].strip():
                current_line += 1
                continue

            # Check if we have enough lines for a complete student
            if current_line + 2 >= len(lines):
                print(f"❌ Incomplete student entry at line {current_line + 1}")
                return False, f"Incomplete student entry at line {current_line + 1}"

            # Verify name line format
            if not lines[current_line].strip().startswith("name: "):
                msg = (f"Invalid name line format at line {current_line + 1}: "
                       f"{lines[current_line]}")
                print(f"❌ {msg}")
                return False, msg

            # Verify id line format
            if not lines[current_line + 1].strip().startswith("id: "):
                msg = (f"Invalid id line format at line {current_line + 2}: "
                       f"{lines[current_line + 1]}")
                print(f"❌ {msg}")
                return False, msg

            # Verify email line format
            if not lines[current_line + 2].strip().startswith("email: "):
                msg = (f"Invalid email line format at line {current_line + 3}: "
                       f"{lines[current_line + 2]}")
                print(f"❌ {msg}")
                return False, msg

            student_count += 1
            current_line += 3

            # Check for blank line separator (except for the last student)
            if current_line < len(lines) and lines[current_line].strip():
                print(f"❌ Missing blank line separator after student {student_count}")
                return False, f"Missing blank line separator after student {student_count}"

            current_line += 1

        if student_count == 0:
            print("❌ No valid student entries found")
            return False, "No valid student entries found"

        print(f"✅ File format is correct with {student_count} students")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading qualified students file: {e}"

def parse_qualified_students_file(test_dir: Path) -> list:
    """Parse the qualified_students.txt file and return structured data."""
    answer_file = test_dir / "qualified_students.txt"

    try:
        content = answer_file.read_text()
        lines = content.strip().split('\n')

        students = []
        current_line = 0

        while current_line < len(lines):
            # Skip blank lines
            if not lines[current_line].strip():
                current_line += 1
                continue

            # Parse student entry
            name_line = lines[current_line].strip()
            id_line = lines[current_line + 1].strip()
            email_line = lines[current_line + 2].strip()

            # Extract name
            name = name_line.replace("name: ", "").strip()

            # Extract id
            student_id = id_line.replace("id: ", "").strip()

            # Extract email
            email = email_line.replace("email: ", "").strip()

            students.append({
                'name': name,
                'id': student_id,
                'email': email
            })

            current_line += 4  # Skip to next student (after blank line)

        return students

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error: {e}")
        return []

def verify_student_count(students: list) -> tuple:
    """Verify that exactly 19 students are found."""
    expected_count = 19
    actual_count = len(students)

    if actual_count != expected_count:
        print(f"❌ Expected {expected_count} students, but found {actual_count}")
        return False, f"Expected {expected_count} students, but found {actual_count}"

    print(f"✅ Found exactly {expected_count} students")
    return True, ""

def verify_expected_students(students: list) -> tuple:
    """Verify that all expected students are present with correct details."""
    # Expected students from answer.md
    expected_students = {
        'James Smith': {'id': '20177389', 'email': 'james.smith30@outlook.com'},
        'Ava Lopez': {'id': '20166998', 'email': 'ava.lopez67@outlook.com'},
        'James Anderson': {'id': '20153606', 'email': 'james.anderson71@yahoo.com'},
        'Benjamin Anderson': {'id': '20136681', 'email': 'benjamin.anderson37@qq.com'},
        'Sarah Wilson': {'id': '20158819', 'email': 'sarah.wilson96@outlook.com'},
        'Isabella Davis': {'id': '20101701', 'email': 'isabella.davis89@gmail.com'},
        'James Moore': {'id': '20188937', 'email': 'james.moore62@gmail.com'},
        'Harper Williams': {'id': '20157943', 'email': 'harper.williams38@163.com'},
        'Noah Smith': {'id': '20132669', 'email': 'noah.smith45@163.com'},
        'Emma Thomas': {'id': '20109144', 'email': 'emma.thomas68@163.com'},
        'Mary Brown': {'id': '20199583', 'email': 'mary.brown27@yahoo.com'},
        'John Jones': {'id': '20201800', 'email': 'john.jones46@gmail.com'},
        'Mia Anderson': {'id': '20162542', 'email': 'mia.anderson3@outlook.com'},
        'Barbara Davis': {'id': '20126203', 'email': 'barbara.davis67@163.com'},
        'Thomas Brown': {'id': '20119528', 'email': 'thomas.brown43@163.com'},
        'Susan Anderson': {'id': '20148778', 'email': 'susan.anderson16@163.com'},
        'Mary Garcia': {'id': '20174369', 'email': 'mary.garcia58@gmail.com'},
        'Richard Wilson': {'id': '20174207', 'email': 'richard.wilson39@outlook.com'},
        'Joseph Lopez': {'id': '20191265', 'email': 'joseph.lopez93@yahoo.com'}
    }

    # Check if all expected students are present
    found_students = set()
    for student in students:
        found_students.add(student['name'])

    missing_students = set(expected_students.keys()) - found_students
    if missing_students:
        print(f"❌ Missing expected students: {missing_students}")
        return False, f"Missing expected students: {missing_students}"

    # Check if all found students are expected
    unexpected_students = found_students - set(expected_students.keys())
    if unexpected_students:
        print(f"❌ Unexpected students found: {unexpected_students}")
        return False, f"Unexpected students found: {unexpected_students}"

    # Check if student details match exactly
    for student in students:
        expected = expected_students[student['name']]
        if student['id'] != expected['id']:
            msg = (f"ID mismatch for {student['name']}: expected "
                   f"{expected['id']}, got {student['id']}")
            print(f"❌ {msg}")
            return False, msg
        if student['email'] != expected['email']:
            msg = (f"Email mismatch for {student['name']}: expected "
                   f"{expected['email']}, got {student['email']}")
            print(f"❌ {msg}")
            return False, msg

    print("✅ All expected students are present with correct details")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Student Database Task: English Talent Recruitment...")

    # Define verification steps
    verification_steps = [
        ("Qualified Students File Exists", verify_qualified_students_file_exists),
        ("File Format", verify_file_format),
    ]

    # Run basic verification steps first
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Parse the file and run content verification
    print("\n--- Content Verification ---")
    students = parse_qualified_students_file(test_dir)

    if not students:
        return False, "Failed to parse qualified students file"

    content_verification_steps = [
        ("Student Count", lambda: verify_student_count(students)),
        ("Expected Students", lambda: verify_expected_students(students)),
    ]

    for step_name, verify_func in content_verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func()
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ English talent recruitment completed correctly!")
    print(f"🎉 Found exactly {len(students)} qualified students")
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
