"""Verification module for multi-branch commit aggregation in harmony repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import os
import base64
import json
from typing import Dict, Optional, Tuple
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], org: str
) -> Tuple[bool, Optional[Dict]]:
    """Make a GET request to GitHub API and return (success, response)."""
    url = f"https://api.github.com/repos/{org}/harmony/{endpoint}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True, response.json()
        if response.status_code == 404:
            print(f"API error for {endpoint}: {response.status_code}", file=sys.stderr)
            return False, None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Exception for {endpoint}: {e}", file=sys.stderr)
        return False, None


def _check_branch_exists(branch_name: str, headers: Dict[str, str], org: str) -> bool:
    """Verify that a branch exists in the repository."""
    success, _ = _get_github_api(f"branches/{branch_name}", headers, org)
    return success


def _get_file_content(
    branch: str, file_path: str, headers: Dict[str, str], org: str
) -> Optional[str]:
    """Get the content of a file from a specific branch."""
    success, result = _get_github_api(f"contents/{file_path}?ref={branch}", headers, org)
    if not success or not result:
        return None

    try:
        content = base64.b64decode(result.get("content", "")).decode("utf-8")
        return content
    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"Content decode error for {file_path}: {e}", file=sys.stderr)
        return None


def _check_branch_commits_json(content: str) -> bool:
    """Verify BRANCH_COMMITS.json has correct structure and expected data."""
    expected_data = {
        "pr/45-googlefan256-main": [
            {
                "sha": "9fa3f54cf2a2501c7dcbf554d5fbdd0de619fdda",
                "author": "googlefan256",
                "message": "Update format.md",
                "files_changed": 1,
            },
            {
                "sha": "3efbf742533a375fc148d75513597e139329578b",
                "author": "scott-oai",
                "message": "Merge pull request #29 from axion66/improve-readme-and-checks",
                "files_changed": 1,
            },
            {
                "sha": "9d653a4c7382abc42d115014d195d9354e7ad357",
                "author": "scott-oai",
                "message": "Merge pull request #30 from Yuan-ManX/harmony-format",
                "files_changed": 1,
            },
        ],
        "pr/25-neuralsorcerer-patch-1": [
            {
                "sha": "c505a03e9c9a388a511b6125756097eee523742a",
                "author": "neuralsorcerer",
                "message": "fix: `meta_sep` token and add to registry",
                "files_changed": 1,
            },
            {
                "sha": "c044bf33f7e835ca6a723ccc97848de25dba5164",
                "author": "neuralsorcerer",
                "message": "fix: `meta_sep` token in `encoding.rs`",
                "files_changed": 1,
            },
            {
                "sha": "b255cbeb6274adbea774f26fd9590922ce8874ed",
                "author": "scott-oai",
                "message": "Merge pull request #18 from openai/dev/scl/better-ci",
                "files_changed": 6,
            },
        ],
        "pr/41-amirhosseinghanipour-fix-race-conditions-and-offline-api": [
            {
                "sha": "1dca6392934bf4e3c403b2ecc2104e8ff3f67f45",
                "author": "amirhosseinghanipour",
                "message": "fix race conditions and add offline tokenizer loading api",
                "files_changed": 8,
            },
            {
                "sha": "9528c7b4a00a3307fd9685fc1328aee11c3d9c90",
                "author": "scott-oai",
                "message": "version bump",
                "files_changed": 2,
            },
            {
                "sha": "82b3afb9eb043343f322c937262cc50405e892c3",
                "author": "scott-oai",
                "message": (
                    "Merge pull request #26 from "
                    "jordan-wu-97/jordan/fix-function-call-atomic-bool"
                ),
                "files_changed": 6,
            },
        ],
    }

    try:
        data = json.loads(content)

        # Check if all required branches are present
        for branch in expected_data:
            if branch not in data:
                print(
                    f"Missing branch {branch} in BRANCH_COMMITS.json", file=sys.stderr
                )
                return False

        # Verify the exact content matches expected data
        for branch, expected_commits in expected_data.items():
            actual_commits = data.get(branch, [])
            if len(actual_commits) != 3:
                print(
                    f"Branch {branch} should have exactly 3 commits, found {len(actual_commits)}",
                    file=sys.stderr,
                )
                return False

            for i, expected_commit in enumerate(expected_commits):
                if i >= len(actual_commits):
                    print(
                        f"Missing commit {i + 1} for branch {branch}", file=sys.stderr
                    )
                    return False

                actual_commit = actual_commits[i]
                for field in ["sha", "author", "files_changed"]:
                    if actual_commit.get(field) != expected_commit.get(field):
                        print(
                            f"Mismatch in {field} for commit {i + 1} in branch {branch}",
                            file=sys.stderr,
                        )
                        expected_val = expected_commit.get(field)
                        actual_val = actual_commit.get(field)
                        msg = f"Expected: {expected_val}, Got: {actual_val}"
                        print(msg, file=sys.stderr)
                        return False

                # For message field, use substring matching to be more flexible
                expected_message = expected_commit.get("message", "")
                actual_message = actual_commit.get("message", "")
                if expected_message not in actual_message:
                    print(
                        f"Mismatch in message for commit {i + 1} in branch {branch}",
                        file=sys.stderr,
                    )
                    print(
                        f"Expected: {expected_message}, Got: {actual_message}",
                        file=sys.stderr,
                    )
                    return False

        return True
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in BRANCH_COMMITS.json: {e}", file=sys.stderr)
        return False
    except (
        requests.RequestException,
        IOError,
        OSError,
        ValueError,
        AttributeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
    ) as e:
        print(f"Error checking BRANCH_COMMITS.json: {e}", file=sys.stderr)
        return False


def _check_cross_branch_analysis(content: str) -> bool:
    """Verify CROSS_BRANCH_ANALYSIS.md contains required sections and data."""
    # Check for required section header
    if "## Top Contributors" not in content:
        print(
            "Missing section '## Top Contributors' in CROSS_BRANCH_ANALYSIS.md",
            file=sys.stderr,
        )
        return False

    # Check for required keyword
    if "contributors" not in content.lower():
        print(
            "Missing keyword 'contributors' in CROSS_BRANCH_ANALYSIS.md",
            file=sys.stderr,
        )
        return False

    # Verify the top 3 contributors with correct counts from main branch (order matters)
    expected_contributors = [
        "scott-oai: 35 commits",
        "egorsmkv: 4 commits",
        "axion66: 2 commits",
    ]

    for contributor in expected_contributors:
        if contributor not in content:
            print(
                f"Missing or incorrect contributor entry: {contributor}",
                file=sys.stderr,
            )
            return False

    return True


def _check_merge_timeline(content: str) -> bool:
    """Verify MERGE_TIMELINE.txt has correct format and expected merge commits."""
    expected_timeline = [
        ("2025-08-06 | Merge pull request #29 from "
         "axion66/improve-readme-and-checks | "
         "3efbf742533a375fc148d75513597e139329578b"),
        ("2025-08-06 | Merge pull request #30 from "
         "Yuan-ManX/harmony-format | "
         "9d653a4c7382abc42d115014d195d9354e7ad357"),
        ("2025-08-06 | Merge pull request #28 from "
         "dkqjrm/fix-typo-format-md | "
         "161e5fe2a57c63e9f8353c4c5b8faa3c3854bb5f"),
        ("2025-08-05 | Merge pull request #26 from "
         "jordan-wu-97/jordan/fix-function-call-atomic-bool | "
         "82b3afb9eb043343f322c937262cc50405e892c3"),
        ("2025-08-05 | Merge pull request #18 from "
         "openai/dev/scl/better-ci | "
         "b255cbeb6274adbea774f26fd9590922ce8874ed"),
        ("2025-08-05 | Merge pull request #21 from Tialo/main | "
         "058ef3257c24fb099aac7960c10ce51c8e55d9fe"),
        ("2025-08-05 | Merge branch 'main' into dev/scl/better-ci | "
         "6375a15ea1b0a486cbb1468964cf8f5800ff5a5c"),
        ("2025-08-05 | Merge pull request #8 from RustedBytes/main | "
         "f6179119ca894eda4124c86d408c01fdbf5281f0"),
        ("2025-08-05 | Merge branch 'main' into main | "
         "eb86106b6980790b94f5702dc510483c66027277"),
        ("2025-08-05 | Merge pull request #17 from "
         "openai/dev/scl/add-docs-to-cargo | "
         "64bca4cf327ebeafa0bbd0345650d86e2d02142f"),
    ]

    # Verify each expected timeline entry exists in the content
    for i, expected_line in enumerate(expected_timeline):
        if expected_line not in content:
            msg = f"Missing expected timeline entry {i + 1} in MERGE_TIMELINE.txt"
            print(msg, file=sys.stderr)
            print(f"Expected: {expected_line}", file=sys.stderr)
            return False

    return True


def verify() -> tuple[bool, str]:
    """Verify the multi-branch commit aggregation task."""
    # Get GitHub token from environment
    load_dotenv(".mcp_env")
    github_token = os.environ.get("MCP_GITHUB_TOKEN")
    if not github_token:
        print("Error: MCP_GITHUB_TOKEN environment variable not set", file=sys.stderr)
        return False, "MCP_GITHUB_TOKEN environment variable not set"

    # Get GitHub organization from environment
    github_org = os.environ.get("GITHUB_EVAL_ORG")
    if not github_org:
        print("Error: GITHUB_EVAL_ORG environment variable not set", file=sys.stderr)
        return False, "GITHUB_EVAL_ORG environment variable not set"

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 1. Check if branch 'history-report-2025' exists
    if not _check_branch_exists("history-report-2025", headers, github_org):
        print("Branch 'history-report-2025' does not exist", file=sys.stderr)
        return False, "Branch 'history-report-2025' does not exist"
    print("✓ Branch 'history-report-2025' exists")

    # 2. Check BRANCH_COMMITS.json
    content = _get_file_content("history-report-2025", "BRANCH_COMMITS.json", headers, github_org)
    if not content:
        print(
            "File 'BRANCH_COMMITS.json' not found in 'history-report-2025' branch",
            file=sys.stderr,
        )
        return False, "File 'BRANCH_COMMITS.json' not found in 'history-report-2025' branch"

    if not _check_branch_commits_json(content):
        return False, "BRANCH_COMMITS.json has incorrect structure or data"
    print("✓ BRANCH_COMMITS.json has correct structure and data")

    # 3. Check CROSS_BRANCH_ANALYSIS.md
    content = _get_file_content(
        "history-report-2025", "CROSS_BRANCH_ANALYSIS.md", headers, github_org
    )
    if not content:
        print(
            "File 'CROSS_BRANCH_ANALYSIS.md' not found in 'history-report-2025' branch",
            file=sys.stderr,
        )
        return False, "File 'CROSS_BRANCH_ANALYSIS.md' not found in 'history-report-2025' branch"

    if not _check_cross_branch_analysis(content):
        return False, "CROSS_BRANCH_ANALYSIS.md missing required sections or data"
    print("✓ CROSS_BRANCH_ANALYSIS.md contains required sections and data")

    # 4. Check MERGE_TIMELINE.txt
    content = _get_file_content("history-report-2025", "MERGE_TIMELINE.txt", headers, github_org)
    if not content:
        print(
            "File 'MERGE_TIMELINE.txt' not found in 'history-report-2025' branch",
            file=sys.stderr,
        )
        return False, "File 'MERGE_TIMELINE.txt' not found in 'history-report-2025' branch"

    if not _check_merge_timeline(content):
        return False, "MERGE_TIMELINE.txt has incorrect format or data"
    print("✓ MERGE_TIMELINE.txt has correct format and data")


    print("\nAll verification checks passed! ✅")
    return True, ""


def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
