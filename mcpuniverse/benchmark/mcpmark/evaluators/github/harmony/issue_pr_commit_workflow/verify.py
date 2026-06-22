"""Verification module for issue PR commit workflow in harmony repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import os
import base64
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Tuple[bool, Optional[Dict]]:
    """Make a GET request to GitHub API and return (success, response)."""
    url = f"https://api.github.com/repos/{org}/{repo}/{endpoint}"
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


def _check_branch_exists(
    branch_name: str, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> bool:
    """Verify that a branch exists in the repository."""
    success, _ = _get_github_api(f"branches/{branch_name}", headers, org, repo)
    return success


def _check_file_content(
    branch: str,
    file_path: str,
    keywords: List[str],
    headers: Dict[str, str],
    org: str,
    repo: str = "harmony",
) -> bool:
    """Verify that a file exists in branch and contains required keywords."""
    success, result = _get_github_api(
        f"contents/{file_path}?ref={branch}", headers, org, repo
    )
    if not success or not result:
        return False

    if keywords and result.get("content"):
        try:
            content = base64.b64decode(result.get("content", "")).decode("utf-8")
            return all(keyword in content for keyword in keywords)
        except (IOError, OSError, UnicodeDecodeError) as e:
            print(f"Content decode error for {file_path}: {e}", file=sys.stderr)
            return False

    return True


def _find_issue_by_title(
    title_substring: str, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Optional[Dict]:
    """Find an issue by title substring and return the issue data."""
    # Check both open and closed issues
    for state in ["open", "closed"]:
        success, issues = _get_github_api(
            f"issues?state={state}&per_page=100", headers, org, repo
        )
        if success and issues:
            for issue in issues:
                if title_substring.lower() in issue.get("title", "").lower():
                    return issue
    return None


def _find_pr_by_title(
    title_substring: str, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Optional[Dict]:
    """Find a PR by title substring and return the PR data."""
    # Check both open and closed PRs
    for state in ["open", "closed"]:
        success, prs = _get_github_api(
            f"pulls?state={state}&per_page=100", headers, org, repo
        )
        if success and prs:
            for pr in prs:
                if title_substring.lower() in pr.get("title", "").lower():
                    return pr
    return None


def _check_issue_references(issue_body: str, reference_numbers: List[str]) -> bool:
    """Check if issue body contains references to specified issue numbers."""
    if not issue_body:
        return False

    return all(f"#{ref}" in issue_body for ref in reference_numbers)


def _check_pr_references(
    pr_body: str, issue_number: int, reference_numbers: List[str]
) -> bool:
    """Check if PR body contains proper references."""
    if not pr_body:
        return False

    # Check for "Closes #X" pattern
    closes_pattern = (
        f"Closes #{issue_number}" in pr_body or f"closes #{issue_number}" in pr_body
    )

    # Check for other references
    refs_present = all(f"#{ref}" in pr_body for ref in reference_numbers)

    return closes_pattern and refs_present


def _get_issue_comments(
    issue_number: int, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> List[Dict]:
    """Get all comments for an issue."""
    success, comments = _get_github_api(
        f"issues/{issue_number}/comments", headers, org, repo
    )
    if success and comments:
        return comments
    return []


def _get_pr_reviews(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> List[Dict]:
    """Get all reviews for a PR."""
    success, reviews = _get_github_api(f"pulls/{pr_number}/reviews", headers, org, repo)
    if success and reviews:
        return reviews
    return []


def _check_issue_comment_references(
    comments: List[Dict], pr_number: int, keywords: List[str]
) -> bool:
    """Check if issue has a comment referencing the PR number with required technical keywords."""
    for comment in comments:
        body = comment.get("body", "")
        has_pr_ref = (
            f"PR #{pr_number}" in body
            or f"PR#{pr_number}" in body
            or f"pr #{pr_number}" in body.lower()
        )
        has_keywords = all(keyword.lower() in body.lower() for keyword in keywords)
        if has_pr_ref and has_keywords:
            return True
    return False


def _check_title_keywords(title: str, required_keywords: List[str]) -> bool:
    """Check if title contains all required keywords."""
    return all(keyword.lower() in title.lower() for keyword in required_keywords)


def _check_headings_and_content(
    body: str, headings: List[str], keywords: List[str]
) -> bool:
    """Check if body contains required headings and keywords."""
    has_headings = all(heading in body for heading in headings)
    has_keywords = all(keyword.lower() in body.lower() for keyword in keywords)
    return has_headings and has_keywords


def _check_pr_review_content(reviews: List[Dict], keywords: List[str]) -> bool:
    """Check if PR has review comments containing required keywords."""
    for review in reviews:
        body = review.get("body", "")
        if body and all(keyword.lower() in body.lower() for keyword in keywords):
            return True
    return False


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the issue-PR-commit workflow meets the
    requirements described in description.md.
    """
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

    # Configuration constants
    branch_name = "fix/race-condition-tokenizer-loading"
    issue_title_substring = "race condition in HarmonyEncoding"
    pr_title_substring = "Fix race condition in tokenizer loading"

    # File content checks
    rust_file_keywords = [
        "DOWNLOAD_MUTEX",
        "OnceLock<Mutex<()>>",
        "load_harmony_encoding_safe",
        "load_harmony_encoding_from_file",
        "Thread-safe tokenizer loading",
    ]

    # Issue content requirements
    issue_title_keywords = ["race condition", "HarmonyEncoding", "concurrent access"]
    issue_reference_numbers = ["6", "1"]
    issue_headings = ["## Problem", "## Root Cause", "## Expected Solution"]
    issue_keywords = [
        "multiple threads",
        "tokenizer file downloads",
        "mutex-based file locking",
    ]

    # PR content requirements
    pr_title_keywords = ["Fix race condition", "tokenizer loading", "threading issues"]
    pr_reference_numbers = ["1", "6"]
    pr_headings = ["## Summary", "## Changes", "## Testing"]
    pr_keywords = ["thread-safe", "concurrent downloads", "offline loading API"]

    # Review comment requirements
    review_keywords = ["OnceLock", "mutex", "thread safety", "concurrent access"]

    # Issue comment requirements
    issue_comment_keywords = [
        "std::sync::Mutex",
        "OnceLock",
        "thread-safe initialization",
        "DOWNLOAD_MUTEX",
    ]

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Run verification checks
    print("Verifying GitHub issue-PR-commit workflow completion...")

    # 1. Check that feature branch exists
    print("1. Verifying feature branch exists...")
    if not _check_branch_exists(branch_name, headers, github_org):
        print(f"Error: Branch '{branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{branch_name}' not found"

    # 2. Check that the Rust implementation file exists with required content
    print("2. Verifying concurrent_loading.rs implementation...")
    if not _check_file_content(
        branch_name,
        "src/concurrent_loading.rs",
        rust_file_keywords,
        headers,
        github_org,
    ):
        print(
            "Error: src/concurrent_loading.rs not found or missing required content",
            file=sys.stderr,
        )
        return False, "src/concurrent_loading.rs not found or missing required content"

    # 3. Find the created issue
    print("3. Verifying issue creation and content...")
    issue = _find_issue_by_title(issue_title_substring, headers, github_org)
    if not issue:
        print(
            f"Error: Issue with title containing '{issue_title_substring}' not found",
            file=sys.stderr,
        )
        return False, f"Issue with title containing '{issue_title_substring}' not found"

    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    issue_body = issue.get("body", "")

    # Check issue title keywords
    if not _check_title_keywords(issue_title, issue_title_keywords):
        print("Error: Issue title missing required keywords", file=sys.stderr)
        return False, "Issue title missing required keywords"

    # Check issue headings, content and references
    if not _check_headings_and_content(issue_body, issue_headings, issue_keywords):
        print("Error: Issue missing required headings or keywords", file=sys.stderr)
        return False, "Issue missing required headings or keywords"

    if not _check_issue_references(issue_body, issue_reference_numbers):
        print(
            "Error: Issue does not reference required issues #6 and #1", file=sys.stderr
        )
        return False, "Issue does not reference required issues #6 and #1"

    # 4. Find the created PR
    print("4. Verifying pull request creation and content...")
    pr = _find_pr_by_title(pr_title_substring, headers, github_org)
    if not pr:
        print(
            f"Error: PR with title containing '{pr_title_substring}' not found",
            file=sys.stderr,
        )
        return False, f"PR with title containing '{pr_title_substring}' not found"

    pr_number = pr.get("number")
    pr_title = pr.get("title", "")
    pr_body = pr.get("body", "")

    # Check PR title keywords
    if not _check_title_keywords(pr_title, pr_title_keywords):
        print("Error: PR title missing required keywords", file=sys.stderr)
        return False, "PR title missing required keywords"

    # Check PR headings and content
    if not _check_headings_and_content(pr_body, pr_headings, pr_keywords):
        print("Error: PR missing required headings or keywords", file=sys.stderr)
        return False, "PR missing required headings or keywords"

    # Check PR references
    if not _check_pr_references(pr_body, issue_number, pr_reference_numbers):
        print(
            f"Error: PR does not properly reference issue #{issue_number} or issues #1, #6",
            file=sys.stderr,
        )
        return False, f"PR does not properly reference issue #{issue_number} or issues #1, #6"

    # 5. Check PR review comments
    print("5. Verifying PR review comments...")
    reviews = _get_pr_reviews(pr_number, headers, github_org)
    if not _check_pr_review_content(reviews, review_keywords):
        print(
            "Error: PR missing review comment with required technical keywords",
            file=sys.stderr,
        )
        return False, "PR missing review comment with required technical keywords"

    # 6. Check issue comments for PR reference with technical keywords
    print("6. Verifying issue comment referencing PR...")
    issue_comments = _get_issue_comments(issue_number, headers, github_org)
    if not _check_issue_comment_references(
        issue_comments, pr_number, issue_comment_keywords
    ):
        msg = (f"Error: Issue #{issue_number} missing comment referencing "
               f"PR #{pr_number} with required technical keywords")
        print(msg, file=sys.stderr)
        return False, msg

    # 7. Check issue is closed
    print("7. Verifying issue closure...")
    if issue.get("state") != "closed":
        print(f"Error: Issue #{issue_number} is not closed", file=sys.stderr)
        return False, f"Issue #{issue_number} is not closed"

    print("\n✓ All verification checks passed!")
    print("Issue-PR-commit workflow completed successfully:")
    print(f"  - Issue #{issue_number}: {issue.get('title')}")
    print(f"  - PR #{pr_number}: {pr.get('title')}")
    print(f"  - Branch: {branch_name}")
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
