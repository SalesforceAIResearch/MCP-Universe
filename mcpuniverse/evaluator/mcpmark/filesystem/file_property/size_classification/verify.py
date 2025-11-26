#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for File Classification Task
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
        category = meta.get("category_id", "file_property")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def get_expected_classification():
    """Return the expected file classification based on answer.md."""
    return {
        "small_files": ["random_file_1.txt", "random_file_3.txt"],
        "medium_files": ["random_file_2.txt"],
        "large_files": ["bear.jpg", "sg.jpg", "road.MOV", "bus.MOV", "bridge.jpg"]
    }

def verify_directories_exist(test_dir: Path) -> tuple:
    """Verify that all three required directories exist."""
    required_dirs = ["small_files", "medium_files", "large_files"]

    for dir_name in required_dirs:
        dir_path = test_dir / dir_name
        if not dir_path.exists():
            print(f"❌ Directory '{dir_name}' not found")
            return False, f"Directory '{dir_name}' not found"
        if not dir_path.is_dir():
            print(f"❌ '{dir_name}' exists but is not a directory")
            return False, f"'{dir_name}' exists but is not a directory"

    print("✅ All required directories exist")
    return True, ""

def verify_file_classification(test_dir: Path) -> tuple:
    """Verify that files are correctly classified into the right directories."""
    expected_classification = get_expected_classification()

    for dir_name, expected_files in expected_classification.items():
        dir_path = test_dir / dir_name

        # Check that all expected files are in the directory
        missing_files = []
        for filename in expected_files:
            file_path = dir_path / filename
            if not file_path.exists():
                missing_files.append(filename)

        if missing_files:
            print(f"❌ Missing files in '{dir_name}': {missing_files}")
            return False, f"Missing files in '{dir_name}': {missing_files}"

        # Check that no unexpected files are in the directory
        # (ignore .DS_Store and similar system files)
        actual_files = [f.name for f in dir_path.iterdir() if f.is_file()]
        # Filter out system files that are commonly present
        system_files = ['.DS_Store', 'Thumbs.db', '.DS_Store?', '._.DS_Store']
        unexpected_files = [f for f in actual_files
                           if f not in expected_files and f not in system_files]

        if unexpected_files:
            print(f"❌ Unexpected files in '{dir_name}': {unexpected_files}")
            return False, f"Unexpected files in '{dir_name}': {unexpected_files}"

    print("✅ All files are correctly classified")
    return True, ""

def verify_no_files_in_root(test_dir: Path) -> tuple:
    """Verify that no files remain in the root test directory."""
    root_files = [f for f in test_dir.iterdir() if f.is_file()]

    # Filter out system files that are commonly present
    system_files = ['.DS_Store', 'Thumbs.db', '.DS_Store?', '._.DS_Store']
    non_system_files = [f for f in root_files if f.name not in system_files]

    if non_system_files:
        print(f"❌ Files still present in root directory: {[f.name for f in non_system_files]}")
        return False, f"Files still present in root directory: {[f.name for f in non_system_files]}"

    print("✅ No files remain in root directory")
    return True, ""

def verify_file_sizes(test_dir: Path) -> tuple:
    """Verify that files are actually in the correct size categories."""
    size_ranges = {
        "small_files": (0, 299),  # < 300 bytes
        "medium_files": (300, 700),  # 300-700 bytes (inclusive)
        "large_files": (701, float('inf'))  # > 700 bytes
    }

    for dir_name, _ in size_ranges.items():
        dir_path = test_dir / dir_name

        for file_path in dir_path.iterdir():
            if file_path.is_file():
                file_size = file_path.stat().st_size

                if dir_name == "small_files" and file_size >= 300:
                    msg = (f"File {file_path.name} in small_files "
                           f"but size is {file_size} bytes")
                    print(f"❌ {msg}")
                    return False, msg
                if dir_name == "medium_files" and (file_size < 300 or
                                                   file_size > 700):
                    msg = (f"File {file_path.name} in medium_files "
                           f"but size is {file_size} bytes")
                    print(f"❌ {msg}")
                    return False, msg
                if dir_name == "large_files" and file_size <= 700:
                    msg = (f"File {file_path.name} in large_files "
                           f"but size is {file_size} bytes")
                    print(f"❌ {msg}")
                    return False, msg

    print("✅ All files are in correct size categories")
    return True, ""

def verify_total_file_count(test_dir: Path) -> tuple:
    """Verify that all original files are accounted for."""
    expected_classification = get_expected_classification()
    total_expected = sum(len(files) for files in expected_classification.values())

    total_actual = 0
    for dir_name in ["small_files", "medium_files", "large_files"]:
        dir_path = test_dir / dir_name
        if dir_path.exists():
            # Count only non-system files
            system_files = ['.DS_Store', 'Thumbs.db', '.DS_Store?', '._.DS_Store']
            files_in_dir = [f for f in dir_path.iterdir()
                           if f.is_file() and f.name not in system_files]
            total_actual += len(files_in_dir)

    if total_actual != total_expected:
        print(f"❌ Expected {total_expected} files total, found {total_actual}")
        return False, f"Expected {total_expected} files total, found {total_actual}"

    print(f"✅ Total file count is correct: {total_actual}")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print(f"🔍 Verifying file classification in: {test_dir}")

    # Run all verification checks
    checks = [
        ("Directory existence", verify_directories_exist),
        ("File classification", verify_file_classification),
        ("No files in root", verify_no_files_in_root),
        ("File size validation", verify_file_sizes),
        ("Total file count", verify_total_file_count)
    ]

    for check_name, check_func in checks:
        print(f"\n📋 Checking: {check_name}")
        passed, error_msg = check_func(test_dir)
        if not passed:
            return False, error_msg

    print("\n🎉 All verification checks passed!")
    return True, ""

def main():
    """Main verification function."""
    try:
        test_dir = get_test_directory()
        passed, error_msg = verify(test_dir)

        if passed:
            sys.exit(0)
        else:
            print(f"\n❌ Verification failed: {error_msg}")
            sys.exit(1)

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Verification failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
