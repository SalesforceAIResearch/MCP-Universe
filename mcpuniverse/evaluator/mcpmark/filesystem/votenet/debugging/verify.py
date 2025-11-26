#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for VoteNet Task: Debug Backbone Module
"""

import sys
from pathlib import Path
import os
import json
from typing import Union

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

def _read_answer_file(test_dir: Path) -> Union[tuple[str, None], tuple[None, str]]:
    """Read answer file content, returning (content, None)
    on success or (None, error_msg) on failure."""
    answer_file = test_dir / "answer.txt"
    try:
        content = answer_file.read_text().strip()
        return content, None
    except (IOError, OSError, UnicodeDecodeError) as e:
        return None, f"Error reading answer file: {e}"

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
    content, error_msg = _read_answer_file(test_dir)
    if error_msg:
        print(f"❌ {error_msg}")
        return False, error_msg

    # Check if content is not empty
    if not content:
        print("❌ Answer file is empty")
        return False, "Answer file is empty"

    # Check if it contains only one line (no additional text)
    if len(content.split('\n')) > 1:
        print("❌ Answer file contains multiple lines or additional text")
        return False, "Answer file contains multiple lines or additional text"

    # Check if path contains the expected components
    if 'models/backbone_module.py' not in content:
        print("❌ Answer should contain 'models/backbone_module.py'")
        return False, "Answer should contain 'models/backbone_module.py'"

    print("✅ Answer format is correct")
    return True, ""

def verify_file_path_structure(test_dir: Path) -> tuple:
    """Verify that the file path has the expected structure."""
    content, error_msg = _read_answer_file(test_dir)
    if error_msg:
        print(f"❌ Error verifying answer structure: {error_msg}")
        return False, f"Error verifying answer structure: {error_msg}"

    # Expected path components for backbone module
    expected_components = ["models", "backbone_module.py"]

    # Check if all expected components are in the content
    for component in expected_components:
        if component not in content:
            print(f"❌ Answer missing expected component: {component}")
            return False, f"Answer missing expected component: {component}"

    print("✅ Answer contains expected components")
    return True, ""

def verify_file_exists(test_dir: Path) -> tuple:
    """Verify that the identified file actually exists."""
    try:
        # Try the expected path
        file_path = test_dir / "models/backbone_module.py"

        if not file_path.exists():
            print("❌ Expected file does not exist: models/backbone_module.py")
            return False, "Expected file does not exist: models/backbone_module.py"

        print("✅ Expected file exists")
        return True, ""

    except (IOError, OSError) as e:
        print(f"❌ Error verifying file existence: {e}")
        return False, f"Error verifying file existence: {e}"

def verify_bug_fix(test_dir: Path) -> tuple:
    """Verify that the bug has been fixed in the code."""
    try:
        file_path = test_dir / "models/backbone_module.py"

        if not file_path.exists():
            print("❌ Cannot find file for bug fix verification: models/backbone_module.py")
            return False, "Cannot find file for bug fix verification: models/backbone_module.py"

        # Read the file and search for the specific line containing self.fp2 = PointnetFPModule
        file_content = file_path.read_text()
        lines = file_content.split('\n')

        # Find the line containing self.fp2 = PointnetFPModule
        target_line = None
        target_line_number = None

        for i, line in enumerate(lines):
            if "self.fp2 = PointnetFPModule" in line:
                target_line = line.strip()
                target_line_number = i + 1  # Convert to 1-based line number
                break

        if target_line is None:
            print("❌ Could not find line containing 'self.fp2 = PointnetFPModule'")
            return False, "Could not find line containing 'self.fp2 = PointnetFPModule'"

        # Check if the original buggy line still exists
        original_bug = "self.fp2 = PointnetFPModule(mlp=[256,256,256])"
        if original_bug in target_line:
            msg = "Bug has not been fixed - original line still exists"
            print(f"❌ {msg}")
            print(f"   Line {target_line_number} content: {target_line}")
            return False, msg

        # Check for the correct fix
        correct_fixes = [
            "self.fp2 = PointnetFPModule(mlp=[256+256,256,256])",
            "self.fp2 = PointnetFPModule(mlp=[512,256,256])"
        ]

        fix_found = False
        for fix in correct_fixes:
            if fix in target_line:
                fix_found = True
                break

        if not fix_found:
            print(f"❌ Bug fix not found at line {target_line_number}")
            print(f"   Line {target_line_number} content: {target_line}")
            print("   Expected one of:")
            for fix in correct_fixes:
                print(f"   - {fix}")
            return False, "Bug fix not found"

        print(f"✅ Bug has been fixed correctly at line {target_line_number}")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying bug fix: {e}")
        return False, f"Error verifying bug fix: {e}"



def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying VoteNet Task: Debug Backbone Module...")

    # Define verification steps
    verification_steps = [
        ("Answer File Exists", verify_answer_file_exists),
        ("Answer Format", verify_answer_format),
        ("Answer Structure", verify_file_path_structure),
        ("File Exists", verify_file_exists),
        ("Bug Fix Applied", verify_bug_fix),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ VoteNet backbone module bug has been correctly identified and fixed!")
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
