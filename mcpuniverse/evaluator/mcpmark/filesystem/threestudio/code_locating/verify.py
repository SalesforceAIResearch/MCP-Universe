#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for ThreeStudio Task 1: Find Zero123 Guidance Implementation
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
        category = meta.get("category_id", "threestudio")

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

def verify_answer_format(test_dir: Path) -> tuple:
    """Verify that the answer file has the correct format."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # Check if content is not empty
        if not content:
            print("❌ Answer file is empty")
            return False, "Answer file is empty"

        # Check if it contains only the file path (no additional text)
        if len(content.split('\n')) > 1:
            print("❌ Answer file contains multiple lines or additional text")
            return False, "Answer file contains multiple lines or additional text"

        # Check if it uses forward slashes
        if '\\' in content:
            print("❌ Answer uses backslashes instead of forward slashes")
            return False, "Answer uses backslashes instead of forward slashes"

        # Check if it's a relative path
        if content.startswith('/') or ':' in content:
            print("❌ Answer appears to be an absolute path")
            return False, "Answer appears to be an absolute path"

        print("✅ Answer format is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading answer file: {e}"

def verify_file_path_structure(test_dir: Path) -> tuple:
    """Verify that the file path has the expected structure."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # Expected path components for Zero123 guidance
        # In backup directories, the path is
        # threestudio/models/guidance/zero123_guidance.py
        # In test_environments, the path is
        # threestudio/threestudio/models/guidance/zero123_guidance.py
        expected_components = ["threestudio", "models", "guidance", "zero123_guidance.py"]

        # Check if all expected components are in the path
        for component in expected_components:
            if component not in content:
                print(f"❌ Path missing expected component: {component}")
                return False, f"Path missing expected component: {component}"

        print("✅ File path structure is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying file: {e}")
        return False, f"Error verifying file path structure: {e}"

def verify_file_exists(test_dir: Path) -> tuple:
    """Verify that the identified file actually exists."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # Try the path as provided in the answer file
        file_path = test_dir / content

        # If that doesn't exist, try with the correct path structure
        # The answer file might have threestudio/models/guidance/zero123_guidance.py
        # but the actual path is threestudio/threestudio/models/guidance/zero123_guidance.py
        if not file_path.exists():
            # Try to fix the path by adding the missing threestudio prefix
            if content.startswith("threestudio/models/"):
                corrected_path = content.replace(
                    "threestudio/models/", "threestudio/threestudio/models/")
                file_path = test_dir / corrected_path
                if file_path.exists():
                    print(f"✅ File exists with corrected path: {corrected_path}")
                    return True, ""

        if not file_path.exists():
            print(f"❌ Identified file does not exist: {content}")
            return False, f"Identified file does not exist: {content}"

        print("✅ Identified file exists")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying file: {e}")
        return False, f"Error verifying file existence: {e}"

def verify_zero123_guidance_content(test_dir: Path) -> tuple:
    """Verify that the identified file actually contains Zero123 guidance implementation."""
    answer_file = test_dir / "answer.txt"

    try:
        content = answer_file.read_text().strip()

        # Try the path as provided in the answer file
        file_path = test_dir / content

        # If that doesn't exist, try with the correct path structure
        if not file_path.exists():
            # Try to fix the path by adding the missing threestudio prefix
            if content.startswith("threestudio/models/"):
                corrected_path = content.replace(
                    "threestudio/models/", "threestudio/threestudio/models/")
                file_path = test_dir / corrected_path

        if not file_path.exists():
            print(f"❌ Cannot find file for content verification: {content}")
            return False, f"Cannot find file for content verification: {content}"

        file_content = file_path.read_text()

        # Check for the main Zero123 guidance implementation
        # The main implementation should have the class name "Zero123Guidance"
        # and register as "zero123-guidance"
        main_zero123_indicators = [
            r'class Zero123Guidance',  # Main class name
            r'@threestudio\.register\("zero123-guidance"\)',  # Correct registration
            r'BaseObject',  # Base class
            r'zero123',  # General zero123 reference
        ]

        found_indicators = []
        for indicator in main_zero123_indicators:
            if re.search(indicator, file_content, re.IGNORECASE):
                found_indicators.append(indicator)

        # Check if this is the main Zero123 guidance implementation
        is_main_implementation = (
            'class Zero123Guidance' in file_content and
            '@threestudio.register("zero123-guidance")' in file_content
        )

        if not is_main_implementation:
            msg = "File is not the main Zero123 guidance implementation"
            print(f"❌ {msg}")
            print("   Expected: class Zero123Guidance and "
                  "@threestudio.register('zero123-guidance')")
            return False, msg

        msg = (f"File contains main Zero123 guidance implementation "
               f"indicators: {found_indicators}")
        print(f"✅ {msg}")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying file: {e}")
        return False, f"Error verifying file content: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying ThreeStudio Task 1: Find Zero123 Guidance Implementation...")

    # Define verification steps
    verification_steps = [
        ("Answer File Exists", verify_answer_file_exists),
        ("Answer Format", verify_answer_format),
        ("File Path Structure", verify_file_path_structure),
        ("File Exists", verify_file_exists),
        ("Zero123 Guidance Content", verify_zero123_guidance_content),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Zero123 guidance file path identified correctly!")
    print("🎉 Task 1 verification: PASS")
    return True, ""

def main():
    """Main verification function."""
    test_dir = get_test_directory()
    passed, error_msg = verify(test_dir)

    if passed:
        sys.exit(0)
    else:
        print(f"\n❌ Task 1 verification: FAIL - {error_msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()
