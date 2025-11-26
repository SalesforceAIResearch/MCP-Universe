"""Verification module for performance regression investigation in EasyR1 repository."""
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


def _find_main_tracking_issue(headers: Dict[str, str]) -> Optional[Dict]:
    """Find the main tracking issue with exact title and required labels."""
    success, issues = _get_github_api("issues?state=open&per_page=50", headers)
    if not success or not issues:
        return None

    for issue in issues:
        title = issue.get("title", "")
        if title == "Performance Regression Analysis: Data Protocol Changes":
            # Check labels
            labels = [label.get("name", "") for label in issue.get("labels", [])]
            required_labels = {"bug", "performance", "investigation"}
            if required_labels.issubset(set(labels)):
                return issue
    return None


def _check_branches_exist(branch_names: List[str], headers: Dict[str, str]) -> bool:
    """Check if all required branches exist."""
    for branch_name in branch_names:
        success, _ = _get_github_api(f"branches/{branch_name}", headers)
        if not success:
            print(f"Error: Branch '{branch_name}' not found", file=sys.stderr)
            return False
    return True


def _check_sub_issues(
    main_issue_number: int, expected_titles: List[str], headers: Dict[str, str]
) -> bool:
    """Check if sub-issues are created and linked to main issue."""
    success, sub_issues = _get_github_api(
        f"issues/{main_issue_number}/sub_issues", headers
    )
    if not success:
        # If sub_issues endpoint doesn't exist, check for issues mentioning the main issue
        success, all_issues = _get_github_api("issues?state=open&per_page=100", headers)
        if not success:
            return False

        sub_issues = []
        for issue in all_issues:
            body = issue.get("body", "")
            title = issue.get("title", "")
            # Check if issue references main issue or has expected title pattern
            if f"#{main_issue_number}" in body or any(
                expected_title in title for expected_title in expected_titles
            ):
                sub_issues.append(issue)

    if not sub_issues or len(sub_issues) < 3:
        print(
            f"Error: Expected 3 sub-issues linked to main issue #{main_issue_number}",
            file=sys.stderr,
        )
        return False

    # Check if sub-issues have expected titles
    found_titles = [issue.get("title", "") for issue in sub_issues]
    for expected_title in expected_titles:
        if not any(expected_title in title for title in found_titles):
            print(
                f"Error: Sub-issue with title containing '{expected_title}' not found",
                file=sys.stderr,
            )
            return False

    return True


def _check_issue_comments(issue_number: int, headers: Dict[str, str]) -> bool:
    """Check if main issue has at least 2 comments with file references."""
    success, comments = _get_github_api(f"issues/{issue_number}/comments", headers)
    if not success or not comments:
        print(f"Error: No comments found on issue #{issue_number}", file=sys.stderr)
        return False

    if len(comments) < 2:
        print(
            f"Error: Expected at least 2 comments on issue #{issue_number}",
            file=sys.stderr,
        )
        return False

    # Check if comments reference specific files and commit
    required_refs = [
        "verl/protocol.py",
        "examples/config.yaml",
        "0989315",
    ]
    comment_text = " ".join([comment.get("body", "") for comment in comments])

    for ref in required_refs:
        if ref not in comment_text:
            print(f"Error: Comments missing reference to '{ref}'", file=sys.stderr)
            return False

    return True


def _find_analysis_pr(headers: Dict[str, str]) -> Optional[Dict]:
    """Find the analysis PR with exact title from specific branch."""
    success, prs = _get_github_api("pulls?state=open&per_page=50", headers)
    if not success or not prs:
        return None

    expected_title = "Performance Analysis: Protocol Changes Investigation"
    expected_head = "investigate-protocol-changes"

    for pr in prs:
        title = pr.get("title", "")
        head_ref = pr.get("head", {}).get("ref", "")

        if title == expected_title and head_ref == expected_head:
            return pr

    return None


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the performance regression investigation workflow meets the
    requirements described in description.md.
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

    # Run verification checks
    print("Verifying performance regression investigation workflow completion...")

    # 1. Check main tracking issue exists with exact title and labels
    print("1. Checking main tracking issue with required title and labels...")
    main_issue = _find_main_tracking_issue(headers)
    if not main_issue:
        msg = ("Error: Main tracking issue not found with exact title "
               "'Performance Regression Analysis: Data Protocol Changes' "
               "and labels 'bug', 'performance', 'investigation'")
        print(msg, file=sys.stderr)
        return False, "Main tracking issue not found with exact title and required labels"

    main_issue_number = main_issue.get("number")
    print(f"Found main tracking issue #{main_issue_number}")

    # 2. Check that all 3 investigation branches exist
    print("2. Checking investigation branches exist...")
    required_branches = [
        "investigate-protocol-changes",
        "investigate-batch-processing",
        "investigate-memory-usage",
    ]
    if not _check_branches_exist(required_branches, headers):
        return False, "Required investigation branches not found"

    # 3. Check sub-issues are created and linked
    print("3. Checking sub-issues are created and linked...")
    expected_sub_titles = [
        "Test Performance Impact: fix multi modal data oom",
        "Test Performance Impact: upgrade vllm to 0.10",
        "Test Performance Impact: non blocking false by default",
    ]
    if not _check_sub_issues(main_issue_number, expected_sub_titles, headers):
        return False, "Sub-issues not created or linked properly"

    # 4. Check issue comments document file changes
    print("4. Checking issue comments document file changes...")
    if not _check_issue_comments(main_issue_number, headers):
        return False, "Issue comments missing required file references"

    # 5. Check analysis PR exists with exact title from correct branch
    print("5. Checking analysis PR exists with exact title and branch...")
    analysis_pr = _find_analysis_pr(headers)
    if not analysis_pr:
        msg = ("Error: Analysis PR not found with title "
               "'Performance Analysis: Protocol Changes Investigation' "
               "from branch 'investigate-protocol-changes'")
        print(msg, file=sys.stderr)
        return False, "Analysis PR not found with required title and branch"

    print(f"Found analysis PR #{analysis_pr.get('number')}")

    print("\n✓ Task completed successfully!")
    print(
        f"Main tracking issue #{main_issue_number} created with proper labels and documentation"
    )
    print("All 3 investigation branches created for different investigation tracks")
    print("3 sub-issues created and linked to main tracking issue")
    print("Issue comments document file changes with commit SHA references")
    print(f"Analysis PR #{analysis_pr.get('number')} created from correct branch")
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
