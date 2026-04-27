#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Directory Structure Mirroring with Smart Placeholders Task
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
        category = meta.get("category_id", "folder_structure")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_mirror_directory_exists(test_dir: Path, mirror_path: Path) -> tuple:
    """Verify that a mirror directory exists."""
    if not mirror_path.exists():
        print(f"❌ Mirror directory not found: {mirror_path.relative_to(test_dir)}")
        return False, f"Mirror directory not found: {mirror_path.relative_to(test_dir)}"

    if not mirror_path.is_dir():
        rel_path = mirror_path.relative_to(test_dir)
        msg = f"Mirror path exists but is not a directory: {rel_path}"
        print(f"❌ {msg}")
        return False, msg

    print(f"✅ Mirror directory exists: {mirror_path.relative_to(test_dir)}")
    return True, ""

def verify_placeholder_file_exists(mirror_path: Path, test_dir: Path) -> tuple:
    """Verify that placeholder.txt exists in the mirror directory."""
    placeholder_file = mirror_path / "placeholder.txt"

    if not placeholder_file.exists():
        rel_path = mirror_path.relative_to(test_dir)
        msg = f"placeholder.txt not found in: {rel_path}"
        print(f"❌ {msg}")
        return False, msg

    if not placeholder_file.is_file():
        rel_path = mirror_path.relative_to(test_dir)
        msg = f"placeholder.txt exists but is not a file in: {rel_path}"
        print(f"❌ {msg}")
        return False, msg

    print(f"✅ placeholder.txt exists in: {mirror_path.relative_to(test_dir)}")
    return True, ""

def verify_placeholder_content(mirror_path: Path, test_dir: Path) -> tuple:
    """Verify that placeholder.txt contains the correct path ending
    with complex_structure_mirror/...
    """
    placeholder_file = mirror_path / "placeholder.txt"

    try:
        content = placeholder_file.read_text().strip()

        # Check if content is not empty
        if not content:
            rel_path = mirror_path.relative_to(test_dir)
            msg = f"placeholder.txt is empty in: {rel_path}"
            print(f"❌ {msg}")
            return False, msg

        # Check if it contains the correct path ending
        # with complex_structure_mirror/...
        rel_mirror = mirror_path.relative_to(test_dir / 'complex_structure_mirror')
        expected_ending = f"complex_structure_mirror/{rel_mirror}"
        if not content.endswith(expected_ending):
            rel_path = mirror_path.relative_to(test_dir)
            msg = f"placeholder.txt content incorrect in: {rel_path}"
            print(f"❌ {msg}")
            print(f"   Expected ending: {expected_ending}")
            print(f"   Found: {content}")
            return False, msg

        print(f"✅ placeholder.txt content is correct in: {mirror_path.relative_to(test_dir)}")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        rel_path = mirror_path.relative_to(test_dir)
        msg = f"Error reading placeholder.txt in {rel_path}: {e}"
        print(f"❌ {msg}")
        return False, msg

def verify_no_files_copied(test_dir: Path) -> tuple:
    """Verify that no file contents were copied, only directory structure."""
    source_dir = test_dir / "complex_structure"
    mirror_dir = test_dir / "complex_structure_mirror"

    if not mirror_dir.exists():
        print("❌ Mirror directory 'complex_structure_mirror' not found")
        return False, "Mirror directory 'complex_structure_mirror' not found"

    # Check that no files from source were copied (except placeholder.txt files)
    for source_file in source_dir.rglob("*"):
        if source_file.is_file():
            # Calculate the corresponding mirror path
            relative_path = source_file.relative_to(source_dir)
            mirror_file = mirror_dir / relative_path

            # Skip if this would be a placeholder.txt file
            if mirror_file.name == "placeholder.txt":
                continue

            if mirror_file.exists():
                print(f"❌ File was copied when it shouldn't be: {relative_path}")
                return False, f"File was copied when it shouldn't be: {relative_path}"

    print("✅ No file contents were copied, only directory structure")
    return True, ""

def verify_mirror_structure_completeness(test_dir: Path) -> tuple:
    """Verify that the mirror structure is complete and matches expected structure."""
    mirror_dir = test_dir / "complex_structure_mirror"

    if not mirror_dir.exists():
        print("❌ Mirror directory 'complex_structure_mirror' not found")
        return False, "Mirror directory 'complex_structure_mirror' not found"

    # Define expected directories that should exist (based on backup structure)
    expected_dirs = [
        "deeply",
        "deeply/nested",
        "deeply/nested/folder",
        "deeply/nested/folder/structure",
        "empty_folder",
        "folder_lxkHt_0_1_processed",
        "folder_QdTAj_0_2_processed",
        "folder_xtgyi_0_0_processed",
        "mixed_content",
        "mixed_content/images_and_text",
        "project",
        "project/docs",
        "project/docs/archive",
        "project/docs/archive/2023_processed",
        "project/src",
        "project/src/main",
        "project/src/main/resources"
    ]

    # Define which directories should have placeholder.txt files
    placeholder_dirs = [
        "deeply/nested/folder/structure",
        "empty_folder",
        "folder_lxkHt_0_1_processed",
        "folder_QdTAj_0_2_processed",
        "folder_xtgyi_0_0_processed",
        "mixed_content/images_and_text",
        "project/docs/archive/2023_processed",
        "project/src/main/resources"
    ]

    # Check that all expected directories exist
    for expected_dir in expected_dirs:
        mirror_path = mirror_dir / expected_dir
        passed, error_msg = verify_mirror_directory_exists(test_dir, mirror_path)
        if not passed:
            return False, error_msg
        if expected_dir in placeholder_dirs:
            # Check placeholder.txt for directories that should have it
            passed, error_msg = verify_placeholder_file_exists(mirror_path, test_dir)
            if not passed:
                return False, error_msg
            passed, error_msg = verify_placeholder_content(mirror_path, test_dir)
            if not passed:
                return False, error_msg

    # Check that no unexpected directories exist
    for mirror_subdir in mirror_dir.rglob("*"):
        if mirror_subdir.is_dir():
            relative_path = mirror_subdir.relative_to(mirror_dir)
            if str(relative_path) not in expected_dirs and str(relative_path) != ".":
                print(f"❌ Unexpected directory found: {relative_path}")
                return False, f"Unexpected directory found: {relative_path}"

    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print(f"🔍 Verifying Directory Structure Mirroring with Smart Placeholders in: {test_dir}")

    # Define verification steps
    verification_steps = [
        ("No files copied", verify_no_files_copied),
        ("Mirror structure completeness", verify_mirror_structure_completeness),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n📋 Checking: {step_name}")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Directory structure mirroring completed correctly!")
    print("🎉 Structure Mirror verification: PASS")
    return True, ""

def main():
    """Main verification function."""
    try:
        test_dir = get_test_directory()
        passed, error_msg = verify(test_dir)

        if passed:
            sys.exit(0)
        else:
            print(f"\n❌ Structure Mirror verification: FAIL - {error_msg}")
            sys.exit(1)

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Verification failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
