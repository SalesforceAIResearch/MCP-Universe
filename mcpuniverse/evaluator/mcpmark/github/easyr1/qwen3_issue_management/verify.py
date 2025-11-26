"""Verification module for Qwen3 issue management in EasyR1 repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import os
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

load_dotenv(".mcp_env")


def _get_github_api(
    endpoint: str, headers: Dict[str, str]
) -> Tuple[bool, Optional[Dict]]:
    """Make a GET request to GitHub API and return (success, response)."""
    github_org = os.environ.get("GITHUB_EVAL_ORG")
    url = f"https://api.github.com/repos/{github_org}/EasyR1/{endpoint}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True, response.json()
        if response.status_code == 404:
            return False, None
        print(f"API error for {endpoint}: {response.status_code}", file=sys.stderr)
        return False, None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Exception for {endpoint}: {e}", file=sys.stderr)
        return False, None


def _search_github_issues(
    query: str, headers: Dict[str, str]
) -> Tuple[bool, Optional[List]]:
    """Search GitHub issues using the search API."""
    url = f"https://api.github.com/search/issues?q={query}&per_page=100"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("items", [])
        print(f"Search API error: {response.status_code}", file=sys.stderr)
        return False, None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Search exception: {e}", file=sys.stderr)
        return False, None


def _check_qwen3_issues_reopened(headers: Dict[str, str]) -> Tuple[bool, List]:
    """Check if all Qwen3 issues have been reopened and tagged."""
    # Search for all issues mentioning qwen3 (both open and closed)
    github_org = os.environ.get("GITHUB_EVAL_ORG")
    success, all_qwen3_issues = _search_github_issues(
        f"repo:{github_org}/EasyR1 qwen3", headers
    )

    if not success or not all_qwen3_issues:
        print("Error: Could not search for Qwen3 issues", file=sys.stderr)
        return False, []

    reopened_issues = []
    issues_not_reopened = []
    issues_not_tagged = []

    for issue in all_qwen3_issues:
        issue_number = issue.get("number")
        issue_state = issue.get("state")
        issue_title = issue.get("title", "")

        # Check if the issue is open (should be reopened)
        if issue_state == "closed":
            issues_not_reopened.append(f"#{issue_number}: {issue_title}")
            continue

        # Check if issue has qwen3-related label
        labels = [label.get("name") for label in issue.get("labels", [])]
        if "qwen3-related" not in labels:
            issues_not_tagged.append(f"#{issue_number}: {issue_title}")
        else:
            reopened_issues.append(issue)

    # Report any issues not properly processed
    if issues_not_reopened:
        print("Error: The following Qwen3 issues are still closed:", file=sys.stderr)
        for issue in issues_not_reopened:
            print(f"  - {issue}", file=sys.stderr)
        return False, []

    if issues_not_tagged:
        print(
            "Error: The following reopened issues are missing 'qwen3-related' label:",
            file=sys.stderr,
        )
        for issue in issues_not_tagged:
            print(f"  - {issue}", file=sys.stderr)
        return False, reopened_issues

    return True, reopened_issues


def _check_summary_issue(
    headers: Dict[str, str], reopened_issues: List
) -> Optional[Dict]:
    """Check if the summary issue exists with proper content."""
    success, issues = _get_github_api("issues?state=all", headers)
    if not success or not issues:
        print("Error: Could not fetch issues for summary check", file=sys.stderr)
        return None

    expected_title = "Reopened Qwen3 Issues Summary"

    for issue in issues:
        title = issue.get("title", "")
        if title == expected_title:
            body = issue.get("body", "")

            # Check for required content
            if "# Qwen3 Issues Reopened" not in body:
                print("Error: Summary issue missing header", file=sys.stderr)
                return None

            if (
                "The following closed issues containing 'qwen3' have been reopened:"
                not in body
            ):
                print("Error: Summary issue missing description", file=sys.stderr)
                return None

            if "Total issues reopened:" not in body:
                print("Error: Summary issue missing total count", file=sys.stderr)
                return None

            if (
                "All reopened issues have been tagged with the `qwen3-related` label"
                not in body
            ):
                print("Error: Summary issue missing tagging note", file=sys.stderr)
                return None

            # Check if all reopened issues are listed
            for reopened_issue in reopened_issues:
                issue_num = reopened_issue.get("number")
                if f"#{issue_num}" not in body:
                    print(
                        f"Error: Summary issue missing reference to issue #{issue_num}",
                        file=sys.stderr,
                    )
                    return None

            # Check if summary issue has the label
            labels = [label.get("name") for label in issue.get("labels", [])]
            if "qwen3-related" not in labels:
                print(
                    "Error: Summary issue missing 'qwen3-related' label",
                    file=sys.stderr,
                )
                return None

            return issue

    print(
        "Error: Summary issue 'Reopened Qwen3 Issues Summary' not found",
        file=sys.stderr,
    )
    return None


def verify() -> tuple[bool, str]:
    """
    Verify that all Qwen3-related closed issues have been reopened and tagged.
    """
    # Get GitHub token
    github_token = os.environ.get("MCP_GITHUB_TOKEN")
    if not github_token:
        print("Error: MCP_GITHUB_TOKEN environment variable not set", file=sys.stderr)
        return False, "MCP_GITHUB_TOKEN environment variable not set"

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    print("Verifying Qwen3 issue reopening workflow...")

    # 1. Check if all Qwen3 issues have been reopened and tagged
    print("1. Checking if Qwen3 issues are reopened and tagged...")
    all_reopened, reopened_issues = _check_qwen3_issues_reopened(headers)

    if not all_reopened:
        return False, "Qwen3 issues not properly reopened and tagged"

    if not reopened_issues:
        print("Error: No Qwen3 issues found or reopened", file=sys.stderr)
        return False, "No Qwen3 issues found or reopened"

    # 2. Check if summary issue exists
    print("2. Checking summary issue...")
    summary_issue = _check_summary_issue(headers, reopened_issues)
    if not summary_issue:
        return False, "Summary issue not found or missing required content"

    print("\n✓ Qwen3 issue reopening workflow successfully completed!")
    print(f"✓ Reopened Issues: {len(reopened_issues)} Qwen3-related issues reopened")
    print("✓ Tagging: All reopened issues tagged with 'qwen3-related' label")
    summary_issue_num = summary_issue.get('number')
    print(f"✓ Summary: Issue #{summary_issue_num} created with complete "
          f"list of reopened issues")
    print("\nAll Qwen3-related closed issues have been reopened and properly tagged!")
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
