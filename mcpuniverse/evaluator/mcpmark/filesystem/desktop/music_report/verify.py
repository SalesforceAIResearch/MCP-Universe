#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Desktop 2 Music Report Task: Music Collection Analysis
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

# Hardcoded expected data from answer.json
EXPECTED_SONGS = [
    {"song_name": "晴天", "popularity_score": 2.576},
    {"song_name": "七里香", "popularity_score": 2.488},
    {"song_name": "江南", "popularity_score": 2.488},
    {"song_name": "夜曲", "popularity_score": 2.448},
    {"song_name": "一千年以后", "popularity_score": 2.44},
    {"song_name": "稻香", "popularity_score": 2.376},
    {"song_name": "青花瓷", "popularity_score": 2.336},
    {"song_name": "不为谁而作的歌", "popularity_score": 2.32},
    {"song_name": "学不会", "popularity_score": 2.304},
    {"song_name": "小酒窝", "popularity_score": 2.264},
    {"song_name": "可惜没如果", "popularity_score": 2.248},
    {"song_name": "修炼爱情", "popularity_score": 2.24},
    {"song_name": "背对背拥抱", "popularity_score": 2.24},
    {"song_name": "爱笑的眼睛", "popularity_score": 2.232},
    {"song_name": "她说", "popularity_score": 2.216},
    {"song_name": "简单爱", "popularity_score": 1.952},
    {"song_name": "龙卷风", "popularity_score": 1.936},
    {"song_name": "双截棍", "popularity_score": 1.92},
    {"song_name": "可爱女人", "popularity_score": 1.912},
    {"song_name": "星晴", "popularity_score": 1.896}
]

EXPECTED_TOP_5 = ["晴天", "七里香", "江南", "夜曲", "一千年以后"]

def verify_report_file_exists(test_dir: Path) -> tuple:
    """Verify that the music_analysis_report.txt file exists."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    if not report_file.exists():
        print("❌ 'music_analysis_report.txt' file not found in music/ folder")
        return False, "'music_analysis_report.txt' file not found in music/ folder"

    if not report_file.is_file():
        print("❌ 'music_analysis_report.txt' exists but is not a file")
        return False, "'music_analysis_report.txt' exists but is not a file"

    print("✅ 'music_analysis_report.txt' file exists")
    return True, ""

def verify_file_content_structure(test_dir: Path) -> tuple:
    """Verify that the file has exactly 25 lines."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        if len(lines) != 25:
            print(f"❌ File should have exactly 25 lines, but has {len(lines)}")
            return False, f"File should have exactly 25 lines, but has {len(lines)}"

        print("✅ File has exactly 25 lines")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading file content: {e}"

def verify_song_ranking_format(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that lines 1-20 contain songs with scores in correct format."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        # Check lines 1-20 (index 0-19)
        for i in range(20):
            line = lines[i].strip()
            if not line:
                print(f"❌ Line {i+1} is empty")
                return False, f"Line {i+1} is empty"

            # Check format: songname:popularity_score
            if ':' not in line:
                print(f"❌ Line {i+1} missing colon separator: '{line}'")
                return False, f"Line {i+1} missing colon separator: '{line}'"

            parts = line.split(':', 1)
            if len(parts) != 2:
                print(f"❌ Line {i+1} has incorrect format: '{line}'")
                return False, f"Line {i+1} has incorrect format: '{line}'"

            song_name, score_str = parts

            if not song_name.strip():
                print(f"❌ Line {i+1} has empty song name: '{line}'")
                return False, f"Line {i+1} has empty song name: '{line}'"

            try:
                score = float(score_str.strip())
                if score < 0 or score > 5:
                    print(f"❌ Line {i+1} has invalid score range: {score}")
                    return False, f"Line {i+1} has invalid score range: {score}"
            except ValueError:
                print(f"❌ Line {i+1} has invalid score format: '{score_str}'")
                return False, f"Line {i+1} has invalid score format: '{score_str}'"

        print("✅ Lines 1-20 have correct song:score format")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking song ranking format: {e}")
        return False, f"Error checking song ranking format: {e}"

def verify_song_ranking_order_with_tolerance(test_dir: Path) -> tuple:
    """Verify that songs are ranked by popularity score in descending order,
    allowing equal scores to be swapped."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        scores = []
        for i in range(20):
            line = lines[i].strip()
            parts = line.split(':', 1)
            score = float(parts[1].strip())
            scores.append(score)

        # Check if scores are in descending order,
        # allowing equal scores to be adjacent
        for i in range(1, len(scores)):
            if scores[i] > scores[i-1]:
                msg = (f"Scores not in descending order: "
                       f"{scores[i-1]} < {scores[i]} at line {i+1}")
                print(f"❌ {msg}")
                return False, msg

        print("✅ Songs are ranked by popularity score in descending order (allowing equal scores)")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking song ranking order: {e}")
        return False, f"Error checking song ranking order: {e}"

def verify_song_names_match_expected(test_dir: Path) -> tuple:
    """Verify that all expected song names are present in the ranking."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        found_songs = []
        for i in range(20):
            line = lines[i].strip()
            song_name = line.split(':', 1)[0].strip()
            found_songs.append(song_name)

        # Check if all expected songs are present
        missing_songs = []
        for expected_song in EXPECTED_SONGS:
            if expected_song["song_name"] not in found_songs:
                missing_songs.append(expected_song["song_name"])

        if missing_songs:
            print(f"❌ Missing expected songs: {missing_songs}")
            return False, f"Missing expected songs: {missing_songs}"

        print("✅ All expected song names are present")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking song names: {e}")
        return False, f"Error checking song names: {e}"

def verify_popularity_scores_match_expected(test_dir: Path) -> tuple:
    """Verify that popularity scores match the expected values."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        score_errors = []
        for i in range(20):
            line = lines[i].strip()
            parts = line.split(':', 1)
            song_name = parts[0].strip()
            actual_score = float(parts[1].strip())

            # Find expected score for this song
            expected_score = None
            for expected_song in EXPECTED_SONGS:
                if expected_song["song_name"] == song_name:
                    expected_score = expected_song["popularity_score"]
                    break

            if expected_score is not None:
                # Allow small floating point precision differences
                if abs(actual_score - expected_score) > 0.001:
                    msg = (f"{song_name}: expected {expected_score}, "
                           f"got {actual_score}")
                    score_errors.append(msg)

        if score_errors:
            print(f"❌ Score mismatches: {score_errors}")
            return False, f"Score mismatches: {score_errors}"

        print("✅ All popularity scores match expected values")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking popularity scores: {e}")
        return False, f"Error checking popularity scores: {e}"

def verify_top_5_songs(test_dir: Path) -> tuple:
    """Verify that lines 21-25 contain the top 5 song names,
    allowing equal scores to be in different order."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        # Check lines 21-25 (index 20-24)
        found_top_5 = []
        for i in range(5):
            line_num = i + 21
            line = lines[i + 20].strip()  # Index 20-24 for lines 21-25

            if not line:
                print(f"❌ Line {line_num} is empty")
                return False, f"Line {line_num} is empty"

            if ':' in line:
                print(f"❌ Line {line_num} should not contain colon: '{line}'")
                return False, f"Line {line_num} should not contain colon: '{line}'"

            found_top_5.append(line)

        # Check if all expected top 5 songs are present (order doesn't matter for equal scores)
        missing_songs = []
        for expected_song in EXPECTED_TOP_5:
            if expected_song not in found_top_5:
                missing_songs.append(expected_song)

        if missing_songs:
            print(f"❌ Missing expected top 5 songs: {missing_songs}")
            return False, f"Missing expected top 5 songs: {missing_songs}"

        # Check if the order is valid (allowing equal scores to be swapped)
        # Since 七里香 and 江南 both have score 2.488, they can be in either order
        valid_orders = [
            ["晴天", "七里香", "江南", "夜曲", "一千年以后"],  # Original order
            ["晴天", "江南", "七里香", "夜曲", "一千年以后"],  # Swapped 七里香 and 江南
        ]

        order_valid = False
        for valid_order in valid_orders:
            if found_top_5 == valid_order:
                order_valid = True
                break

        if not order_valid:
            msg = (f"Top 5 songs order is invalid. Found: {found_top_5}, "
                   f"Expected one of: {valid_orders}")
            print(f"❌ {msg}")
            print(f"Expected one of: {valid_orders}")
            return False, msg

        print("✅ Lines 21-25 contain correct top 5 song names in valid order")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking top 5 songs: {e}")
        return False, f"Error checking top 5 songs: {e}"

def verify_no_extra_content(test_dir: Path) -> tuple:
    """Verify that the file contains no extra content beyond the 25 lines."""
    report_file = test_dir / "music" / "music_analysis_report.txt"

    try:
        content = report_file.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        if len(lines) != 25:
            print(f"❌ File should have exactly 25 lines, but has {len(lines)}")
            return False, f"File should have exactly 25 lines, but has {len(lines)}"

        print("✅ File contains exactly 25 lines with no extra content")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking for extra content: {e}")
        return False, f"Error checking for extra content: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Desktop 2 Music Report Task: Music Collection Analysis...")

    # Define verification steps
    verification_steps = [
        ("Report File Exists", verify_report_file_exists),
        ("File Content Structure", verify_file_content_structure),
        ("Song Ranking Format", verify_song_ranking_format),
        ("Song Ranking Order", verify_song_ranking_order_with_tolerance),
        ("Song Names Match Expected", verify_song_names_match_expected),
        ("Popularity Scores Match Expected", verify_popularity_scores_match_expected),
        ("Top 5 Songs", verify_top_5_songs),
        ("No Extra Content", verify_no_extra_content),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Music collection analysis completed correctly!")
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
