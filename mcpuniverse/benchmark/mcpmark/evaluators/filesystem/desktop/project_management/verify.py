#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Desktop 2 Project Management Task: File Reorganization
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
        category = meta.get("category_id", "desktop")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_organized_projects_directory_exists(test_dir: Path) -> tuple:
    """Verify that the organized_projects directory exists."""
    organized_dir = test_dir / "organized_projects"

    if not organized_dir.exists():
        print("❌ 'organized_projects' directory not found")
        return False, "'organized_projects' directory not found"

    if not organized_dir.is_dir():
        print("❌ 'organized_projects' exists but is not a directory")
        return False, "'organized_projects' exists but is not a directory"

    print("✅ 'organized_projects' directory exists")
    return True, ""

def verify_directory_structure(test_dir: Path) -> tuple:
    """Verify that all required subdirectories exist."""
    organized_dir = test_dir / "organized_projects"

    required_dirs = [
        "experiments",
        "experiments/ml_projects",
        "experiments/data_analysis",
        "learning",
        "learning/progress_tracking",
        "learning/resources",
        "personal",
        "personal/entertainment",
        "personal/collections"
    ]

    missing_dirs = []
    for dir_path in required_dirs:
        full_path = organized_dir / dir_path
        if not full_path.exists():
            missing_dirs.append(dir_path)
        elif not full_path.is_dir():
            missing_dirs.append(f"{dir_path} (not a directory)")

    if missing_dirs:
        print(f"❌ Missing or invalid directories: {missing_dirs}")
        return False, f"Missing or invalid directories: {missing_dirs}"

    print("✅ All required directory structure created correctly")
    return True, ""

def verify_python_files_in_ml_projects(test_dir: Path) -> tuple:
    """Verify that all Python files are moved to experiments/ml_projects."""
    organized_dir = test_dir / "organized_projects"
    ml_projects_dir = organized_dir / "experiments" / "ml_projects"

    expected_python_files = [
        "study_notes.py",
        "model.py",
        "data_analysis.py",
        "travel_calculator.py",
        "inventory.py",
        "playlist_manager.py"
    ]

    missing_files = []
    for filename in expected_python_files:
        file_path = ml_projects_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"❌ Missing Python files in ml_projects: {missing_files}")
        return False, f"Missing Python files in ml_projects: {missing_files}"

    print("✅ All Python files moved to experiments/ml_projects")
    return True, ""

def verify_csv_files_in_data_analysis(test_dir: Path) -> tuple:
    """Verify that all CSV files are moved to experiments/data_analysis."""
    organized_dir = test_dir / "organized_projects"
    data_analysis_dir = organized_dir / "experiments" / "data_analysis"

    expected_csv_files = [
        "learning_progress.csv",
        "weekly_schedule.csv",
        "results_record.csv",
        "september_summary.csv",
        "data.csv",
        "favorite_songs.csv",
        "travel_itinerary.csv"
    ]

    missing_files = []
    for filename in expected_csv_files:
        file_path = data_analysis_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"❌ Missing CSV files in data_analysis: {missing_files}")
        return False, f"Missing CSV files in data_analysis: {missing_files}"

    print("✅ All CSV files moved to experiments/data_analysis")
    return True, ""

def verify_learning_md_files_in_resources(test_dir: Path) -> tuple:
    """Verify that learning-related markdown files are moved to learning/resources."""
    organized_dir = test_dir / "organized_projects"
    resources_dir = organized_dir / "learning" / "resources"

    expected_learning_files = [
        "learning_roadmap.md",
        "research_topics.md",
        "experiment_summary.md",
        "exp_record.md",
        "README.md",
        "analysis_report.md",
        "learning_goals.md"
    ]

    missing_files = []
    for filename in expected_learning_files:
        file_path = resources_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"❌ Missing learning markdown files in resources: {missing_files}")
        return False, f"Missing learning markdown files in resources: {missing_files}"

    print("✅ All learning markdown files moved to learning/resources")
    return True, ""

def verify_entertainment_md_files_in_entertainment(test_dir: Path) -> tuple:
    """Verify that entertainment planning markdown files are moved to personal/entertainment."""
    organized_dir = test_dir / "organized_projects"
    entertainment_dir = organized_dir / "personal" / "entertainment"

    expected_entertainment_files = [
        "gaming_schedule.md",
        "entertainment_planner.md",
        "travel_bucket_list.md"
    ]

    missing_files = []
    for filename in expected_entertainment_files:
        file_path = entertainment_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"❌ Missing entertainment markdown files in entertainment: {missing_files}")
        return False, f"Missing entertainment markdown files in entertainment: {missing_files}"

    print("✅ All entertainment markdown files moved to personal/entertainment")
    return True, ""

def verify_music_md_files_in_collections(test_dir: Path) -> tuple:
    """Verify that music collection markdown files are moved to personal/collections."""
    organized_dir = test_dir / "organized_projects"
    collections_dir = organized_dir / "personal" / "collections"

    expected_music_files = [
        "music_collection.md"
    ]

    missing_files = []
    for filename in expected_music_files:
        file_path = collections_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"❌ Missing music collection markdown files in collections: {missing_files}")
        return False, f"Missing music collection markdown files in collections: {missing_files}"

    print("✅ All music collection markdown files moved to personal/collections")
    return True, ""

def verify_progress_tracking_empty(test_dir: Path) -> tuple:
    """Verify that progress_tracking directory is empty."""
    organized_dir = test_dir / "organized_projects"
    progress_dir = organized_dir / "learning" / "progress_tracking"

    files_in_progress = list(progress_dir.iterdir())
    if files_in_progress:
        file_names = [f.name for f in files_in_progress]
        msg = (f"progress_tracking directory should be empty, "
               f"but contains: {file_names}")
        print(f"❌ {msg}")
        return False, msg

    print("✅ progress_tracking directory is correctly empty")
    return True, ""

def verify_project_structure_file_exists(test_dir: Path) -> tuple:
    """Verify that project_structure.md file exists."""
    organized_dir = test_dir / "organized_projects"
    structure_file = organized_dir / "project_structure.md"

    if not structure_file.exists():
        print("❌ 'project_structure.md' file not found")
        return False, "'project_structure.md' file not found"

    if not structure_file.is_file():
        print("❌ 'project_structure.md' exists but is not a file")
        return False, "'project_structure.md' exists but is not a file"

    print("✅ 'project_structure.md' file exists")
    return True, ""

def verify_file_counts(test_dir: Path) -> tuple:
    """Verify that each directory has the correct number of files."""
    organized_dir = test_dir / "organized_projects"

    expected_counts = {
        "experiments/ml_projects": 6,      # 6 Python files
        "experiments/data_analysis": 7,    # 7 CSV files
        "learning/resources": 7,           # 7 learning markdown files
        "learning/progress_tracking": 0,   # 0 files (empty)
        "personal/entertainment": 3,       # 3 entertainment markdown files
        "personal/collections": 1          # 1 music collection markdown file
    }

    incorrect_counts = []
    for dir_path, expected_count in expected_counts.items():
        full_path = organized_dir / dir_path
        actual_count = len([f for f in full_path.iterdir() if f.is_file()])

        if actual_count != expected_count:
            incorrect_counts.append(f"{dir_path}: expected {expected_count}, got {actual_count}")

    if incorrect_counts:
        print(f"❌ Incorrect file counts: {incorrect_counts}")
        return False, f"Incorrect file counts: {incorrect_counts}"

    print("✅ All directories have correct file counts")
    return True, ""

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Desktop 2 Project Management Task: File Reorganization...")

    # Define verification steps
    verification_steps = [
        ("Organized Projects Directory Exists", verify_organized_projects_directory_exists),
        ("Directory Structure", verify_directory_structure),
        ("Python Files in ML Projects", verify_python_files_in_ml_projects),
        ("CSV Files in Data Analysis", verify_csv_files_in_data_analysis),
        ("Learning Markdown Files in Resources", verify_learning_md_files_in_resources),
        ("Entertainment Markdown Files in Entertainment",
         verify_entertainment_md_files_in_entertainment),
        ("Music Collection Files in Collections", verify_music_md_files_in_collections),
        ("Progress Tracking Empty", verify_progress_tracking_empty),
        ("Project Structure File Exists", verify_project_structure_file_exists),
        ("File Counts", verify_file_counts),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Desktop 2 project reorganization completed correctly!")
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
