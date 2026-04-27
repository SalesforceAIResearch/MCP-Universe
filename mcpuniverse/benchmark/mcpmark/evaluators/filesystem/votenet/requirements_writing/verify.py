#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for VoteNet Task: Create Requirements.txt File
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
        category = meta.get("category_id", "votenet")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_requirements_file_exists(test_dir: Path) -> tuple:
    """Verify that the requirements.txt file exists."""
    requirements_file = test_dir / "requirements.txt"

    if not requirements_file.exists():
        print("❌ File 'requirements.txt' not found")
        return False, "File 'requirements.txt' not found"

    print("✅ Requirements.txt file found")
    return True, ""

def verify_requirements_file_readable(test_dir: Path) -> tuple:
    """Verify that the requirements.txt file is readable."""
    requirements_file = test_dir / "requirements.txt"

    try:
        content = requirements_file.read_text()
        if not content.strip():
            print("❌ Requirements.txt file is empty")
            return False, "Requirements.txt file is empty"

        print("✅ Requirements.txt file is readable")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading requirements.txt file: {e}"

def verify_required_dependencies_present(test_dir: Path) -> tuple:
    """Verify that all required dependencies are present."""
    requirements_file = test_dir / "requirements.txt"

    try:
        content = requirements_file.read_text()

        # Required dependencies from answer.txt
        required_deps = [
            "matplotlib",
            "opencv",
            "plyfile",
            "trimesh",
            "pointnet2",
            "networkx"
        ]

        missing_deps = []
        found_deps = []

        for dep in required_deps:
            if dep.lower() in content.lower():
                found_deps.append(dep)
            else:
                missing_deps.append(dep)

        if missing_deps:
            print(f"❌ Missing required dependencies: {missing_deps}")
            return False, f"Missing required dependencies: {missing_deps}"

        print(f"✅ All required dependencies found: {found_deps}")
        return True, ""

    except (OSError, ValueError) as error:
        print(f"❌ Error checking dependencies: {error}")
        return False, f"Error checking dependencies: {error}"

def verify_file_format(test_dir: Path) -> tuple:
    """Verify that the requirements.txt file has proper format."""
    requirements_file = test_dir / "requirements.txt"

    try:
        content = requirements_file.read_text()
        lines = content.split('\n')

        # Check if file has content and proper line structure
        if not content.strip():
            print("❌ File is completely empty")
            return False, "File is completely empty"

        # Check if there are multiple lines (indicating multiple dependencies)
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        if len(non_empty_lines) < 3:  # Should have at least 3 dependencies
            print("❌ File seems to have too few dependencies")
            return False, "File seems to have too few dependencies"

        print("✅ File format is acceptable")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error checking file: {e}")
        return False, f"Error checking file format: {e}"

def verify_no_duplicate_entries(test_dir: Path) -> tuple:
    """Verify that there are no duplicate dependency entries."""
    requirements_file = test_dir / "requirements.txt"

    try:
        content = requirements_file.read_text()
        lines = [line.strip().lower() for line in content.split('\n') if line.strip()]

        # Check for duplicates
        if len(lines) != len(set(lines)):
            print("❌ File contains duplicate entries")
            return False, "File contains duplicate entries"

        print("✅ No duplicate entries found")
        return True, ""

    except (OSError, ValueError) as error:
        print(f"❌ Error checking for duplicates: {error}")
        return False, f"Error checking for duplicates: {error}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying VoteNet Task: Create Requirements.txt File...")

    # Define verification steps
    verification_steps = [
        ("Requirements File Exists", verify_requirements_file_exists),
        ("File is Readable", verify_requirements_file_readable),
        ("Required Dependencies Present", verify_required_dependencies_present),
        ("File Format", verify_file_format),
        ("No Duplicate Entries", verify_no_duplicate_entries),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Requirements.txt file successfully created with all required dependencies!")
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
