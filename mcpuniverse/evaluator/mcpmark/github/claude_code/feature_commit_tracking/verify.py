"""Verification module for feature commit tracking in claude-code repository."""
# pylint: disable=R0911,R0915,astroid-error,duplicate-code,import-error
import sys
import os
import base64
import re
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Tuple[bool, Optional[Dict]]:
    """Make a GET request to GitHub API and return (success, response)."""
    url = f"https://api.github.com/repos/{org}/{repo}/{endpoint}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True, response.json()
        if response.status_code == 404:
            return False, "API error", None
        print(f"API error for {endpoint}: {response.status_code}", file=sys.stderr)
        return False, "API error", None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Exception for {endpoint}: {e}", file=sys.stderr)
        return False, "API error", None


def _get_file_content(
    file_path: str,
    headers: Dict[str, str],
    org: str,
    repo: str = "claude-code",
    ref: str = "main",
) -> Optional[str]:
    """Get the content of a file from the repository."""
    success, result = _get_github_api(
        f"contents/{file_path}?ref={ref}", headers, org, repo
    )
    if not success or not result:
        return None

    try:
        content = base64.b64decode(result.get("content", "")).decode("utf-8")
        return content
    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"Content decode error for {file_path}: {e}", file=sys.stderr)
        return None


def _verify_commit_exists(
    commit_sha: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Tuple[bool, Optional[Dict]]:
    """Verify that a commit exists and return its details."""
    success, commit_data = _get_github_api(f"commits/{commit_sha}", headers, org, repo)
    return success, commit_data


def _parse_feature_table(content: str) -> List[Dict]:
    """Parse the feature commit table from markdown content."""
    features = []

    lines = content.split("\n")
    in_table = False

    for line in lines:
        # Look for table header
        header = ("| Feature Name | Commit SHA | Author | Branch | Date | "
                  "Files Changed | Commit Message |")
        if header in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue

        # Parse table rows
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 8:  # Should have 7 columns plus empty parts at start/end
                feature_name = parts[1].strip()
                commit_sha = parts[2].strip()
                author = parts[3].strip()
                branch = parts[4].strip()
                date = parts[5].strip()
                files_changed = parts[6].strip()
                commit_message = parts[7].strip()

                if feature_name and commit_sha and author and branch and date:
                    features.append(
                        {
                            "name": feature_name,
                            "sha": commit_sha,
                            "author": author,
                            "branch": branch,
                            "date": date,
                            "files_changed": files_changed,
                            "commit_message": commit_message,
                        }
                    )

        # Stop at end of table section
        if in_table and line and not line.startswith("|") and "##" in line:
            break

    return features


def verify() -> tuple[bool, str]:
    """Verify the feature commit tracking task."""
    # Load environment variables from .mcp_env
    load_dotenv(".mcp_env")

    # Get GitHub token and org
    github_token = os.environ.get("MCP_GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_EVAL_ORG")

    if not github_token:
        print("Error: MCP_GITHUB_TOKEN environment variable not set", file=sys.stderr)
        return False, "MCP_GITHUB_TOKEN environment variable not set"

    if not github_org:
        print("Error: GITHUB_EVAL_ORG environment variable not set", file=sys.stderr)
        return False, "GITHUB_EVAL_ORG environment variable not set"

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Expected feature commits based on exploration
    expected_features = {
        "Shell Completion Scripts": "8a0febdd09bda32f38c351c0881784460d69997d",
        "CHANGELOG Version 1.0.65": "94dcaca5d71ad82644ae97f3a2b0c5eb8b63eae0",
        "Rust Extraction Improvements": "50e58affdf1bfc7d875202bc040ebe0dcfb7d332",
    }

    # Expected authors for each commit
    expected_authors = {
        "8a0febdd09bda32f38c351c0881784460d69997d": "gitmpr",
        "94dcaca5d71ad82644ae97f3a2b0c5eb8b63eae0": "QwertyJack",
        "50e58affdf1bfc7d875202bc040ebe0dcfb7d332": "alokdangre",
    }

    # Expected commit messages for each commit
    expected_messages = {
        "8a0febdd09bda32f38c351c0881784460d69997d": "feat: add shell completions (bash, zsh, fish)",
        "94dcaca5d71ad82644ae97f3a2b0c5eb8b63eae0": "Merge branch 'anthropics:main' into main",
        "50e58affdf1bfc7d875202bc040ebe0dcfb7d332": (
            "Enhance Rust extraction and output handling in workflows"
        ),
    }

    # Expected dates for each commit (YYYY-MM-DD format)
    expected_dates = {
        "8a0febdd09bda32f38c351c0881784460d69997d": "2025-08-01",
        "94dcaca5d71ad82644ae97f3a2b0c5eb8b63eae0": "2025-08-02",
        "50e58affdf1bfc7d875202bc040ebe0dcfb7d332": "2025-08-09",
    }

    print("Verifying feature commit tracking task...")

    # 1. Check if FEATURE_COMMITS.md exists in main branch
    print("1. Checking if FEATURE_COMMITS.md exists...")
    content = _get_file_content("FEATURE_COMMITS.md", headers, github_org)
    if not content:
        print("Error: FEATURE_COMMITS.md not found in main branch", file=sys.stderr)
        return False, "FEATURE_COMMITS.md not found in main branch"
    print("✓ FEATURE_COMMITS.md found")

    # 2. Check required sections exist
    print("2. Checking required sections...")
    required_sections = [
        "# Feature Development Tracking",
        "## Overview",
        "## Feature Commit History",
    ]

    for section in required_sections:
        if section not in content:
            print(f"Error: Missing required section '{section}'", file=sys.stderr)
            return False, f"Missing required section '{section}'"
    print("✓ All required sections present")

    # 3. Parse and validate feature table
    print("3. Parsing and validating feature table...")
    features = _parse_feature_table(content)

    if len(features) < 3:
        print(
            f"Error: Expected at least 3 features, found {len(features)}",
            file=sys.stderr,
        )
        return False, f"Expected at least 3 features, found {len(features)}"

    # 4. Verify each expected feature is present with correct commit SHA
    print("4. Verifying feature commit SHAs...")
    found_features = {}
    for feature in features:
        found_features[feature["name"]] = feature["sha"]

    for feature_name, expected_sha in expected_features.items():
        if feature_name not in found_features:
            print(
                f"Error: Feature '{feature_name}' not found in table", file=sys.stderr
            )
            return False, f"Feature '{feature_name}' not found in table"

        actual_sha = found_features[feature_name]
        if actual_sha != expected_sha:
            msg = (f"Error: Wrong SHA for '{feature_name}'. "
                   f"Expected: {expected_sha}, Got: {actual_sha}")
            print(msg, file=sys.stderr)
            return False, (f"Wrong SHA for '{feature_name}'. "
                          f"Expected: {expected_sha}, Got: {actual_sha}")

    print("✓ All feature commit SHAs are correct")

    # 5. Verify each commit exists and has correct author
    print("5. Verifying commit details...")
    for feature in features:
        if feature["sha"] in expected_features.values():
            success, commit_data = _verify_commit_exists(
                feature["sha"], headers, github_org
            )
            if not success:
                print(f"Error: Commit {feature['sha']} not found", file=sys.stderr)
                return False, f"Commit {feature['sha']} not found"

            # Check author
            expected_author = expected_authors.get(feature["sha"])
            if expected_author:
                actual_author = commit_data.get("author", {}).get("login", "")
                if actual_author != expected_author:
                    sha = feature['sha']
                    msg = (f"Error: Wrong author for {sha}. "
                           f"Expected: {expected_author}, Got: {actual_author}")
                    print(msg, file=sys.stderr)
                    return False, (f"Wrong author for {sha}. "
                                  f"Expected: {expected_author}, "
                                  f"Got: {actual_author}")

            # Check commit message (compare with table entry)
            expected_message = expected_messages.get(feature["sha"])
            if expected_message and "commit_message" in feature:
                if feature["commit_message"] != expected_message:
                    sha = feature['sha']
                    got_msg = feature['commit_message']
                    msg = (f"Error: Wrong commit message in table for {sha}. "
                           f"Expected: '{expected_message}', Got: '{got_msg}'")
                    print(msg, file=sys.stderr)
                    return False, (f"Wrong commit message in table for {sha}. "
                                  f"Expected: '{expected_message}', "
                                  f"Got: '{got_msg}'")

            # Also verify against actual commit data
            if expected_message:
                actual_message = (
                    commit_data.get("commit", {}).get("message", "").split("\n")[0]
                )  # First line only
                if actual_message != expected_message:
                    sha = feature['sha']
                    msg = (f"Error: Wrong commit message for {sha}. "
                           f"Expected: '{expected_message}', "
                           f"Got: '{actual_message}'")
                    print(msg, file=sys.stderr)
                    return False, (f"Wrong commit message for {sha}. "
                                  f"Expected: '{expected_message}', "
                                  f"Got: '{actual_message}'")

            # Check date format (YYYY-MM-DD)
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", feature["date"]):
                print(
                    f"Error: Invalid date format for {feature['name']}: {feature['date']}",
                    file=sys.stderr,
                )
                name = feature['name']
                date = feature['date']
                return False, f"Invalid date format for {name}: {date}"

            # Check actual date matches expected
            expected_date = expected_dates.get(feature["sha"])
            if expected_date:
                if feature["date"] != expected_date:
                    sha = feature['sha']
                    got_date = feature['date']
                    msg = (f"Error: Wrong date for {sha}. "
                           f"Expected: {expected_date}, Got: {got_date}")
                    print(msg, file=sys.stderr)
                    return False, (f"Wrong date for {sha}. "
                                  f"Expected: {expected_date}, Got: {got_date}")

    print("✓ All commit details verified")

    # 6. Verify the table format is correct
    print("6. Verifying table format...")
    table_header = (
        "| Feature Name | Commit SHA | Author | Branch | Date | "
        "Files Changed | Commit Message |"
    )
    if table_header not in content:
        print("Error: Table header format is incorrect", file=sys.stderr)
        return False, "Table header format is incorrect"

    # Check that all features have complete information
    for feature in features:
        if not all(
            [
                feature["name"],
                feature["sha"],
                feature["author"],
                feature["branch"],
                feature["date"],
                feature.get("commit_message", ""),
            ]
        ):
            print(
                f"Error: Incomplete information for feature: {feature['name']}",
                file=sys.stderr,
            )
            return False, f"Incomplete information for feature: {feature['name']}"

    print("✓ Table format is correct and complete")

    print("\n✅ All verification checks passed!")
    print("Feature commit tracking completed successfully:")
    print("  - File: FEATURE_COMMITS.md created in main branch")
    print(f"  - Features tracked: {len(features)}")
    print("  - All expected commit SHAs verified")
    print("  - All commit authors verified")
    print("  - Analysis summary complete")

    return True, ""


def verify_task() -> bool:
    """Legacy function for backward compatibility."""
    success, _ = verify()
    return success

def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
