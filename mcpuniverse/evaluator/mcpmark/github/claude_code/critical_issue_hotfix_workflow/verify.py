"""Verification module for critical issue hotfix workflow in claude-code repository."""
# pylint: disable=R0911,R0914,R0915,astroid-error,duplicate-code,import-error
import sys
import os
import base64
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


def _check_branch_exists(
    branch_name: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> bool:
    """Verify that a branch exists in the repository."""
    success, _ = _get_github_api(f"branches/{branch_name}", headers, org, repo)
    return success


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


def _find_issue_by_title_keyword(
    keyword: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Optional[Dict]:
    """Find an issue by title keyword and return the issue data."""
    # Check both open and closed issues
    for state in ["open", "closed"]:
        success, issues = _get_github_api(
            f"issues?state={state}&per_page=100", headers, org, repo
        )
        if success and issues:
            for issue in issues:
                if keyword.lower() in issue.get("title", "").lower():
                    return issue
    return None


def _find_pr_by_title_keyword(
    keyword: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Optional[Dict]:
    """Find a PR by title keyword and return the PR data."""
    # Check both open and closed PRs
    for state in ["open", "closed"]:
        success, prs = _get_github_api(
            f"pulls?state={state}&per_page=100", headers, org, repo
        )
        if success and prs:
            for pr in prs:
                if keyword.lower() in pr.get("title", "").lower():
                    return pr
    return None


def _get_pr_by_number(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Optional[Dict]:
    """Get a specific PR by number."""
    success, pr = _get_github_api(f"pulls/{pr_number}", headers, org, repo)
    if success:
        return pr
    return None


def _check_issue_references(text: str, reference_numbers: List[str]) -> bool:
    """Check if text contains references to specified issue numbers."""
    if not text:
        return False, "API error"

    return all(f"#{ref}" in text for ref in reference_numbers)


def _check_addresses_pattern(pr_body: str, issue_numbers: List[str]) -> bool:
    """Check if PR body contains 'Addresses #X' pattern for specified issues."""
    if not pr_body:
        return False, "API error"

    return all(
        f"Addresses #{num}" in pr_body or f"addresses #{num}" in pr_body
        for num in issue_numbers
    )


def _get_issue_comments(
    issue_number: int, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> List[Dict]:
    """Get all comments for an issue."""
    success, comments = _get_github_api(
        f"issues/{issue_number}/comments", headers, org, repo
    )
    if success and comments:
        return comments
    return []


def _get_pr_reviews(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> List[Dict]:
    """Get all reviews for a PR."""
    success, reviews = _get_github_api(f"pulls/{pr_number}/reviews", headers, org, repo)
    if success and reviews:
        return reviews
    return []


def _check_title_keywords(title: str, required_keywords: List[str]) -> bool:
    """Check if title contains all required keywords."""
    return all(keyword.lower() in title.lower() for keyword in required_keywords)


def _check_headings_and_keywords(
    body: str, headings: List[str], keywords: List[str]
) -> bool:
    """Check if body contains required headings and keywords."""
    has_headings = all(heading in body for heading in headings)
    has_keywords = all(keyword.lower() in body.lower() for keyword in keywords)
    return has_headings and has_keywords


def _check_exact_file_content(content: str, expected_sections: List[str]) -> bool:
    """Check if file content contains expected sections."""
    return all(section in content for section in expected_sections)


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the critical issue hotfix workflow meets the
    requirements described in description.md.
    """
    # Configuration constants
    hotfix_branch_name = "hotfix/memory-optimization-v1.0.72"
    tracking_issue_keyword = "Memory and Context Management Issues"
    hotfix_pr_keyword = "HOTFIX: Critical memory optimization"

    # Expected file content sections
    memory_doc_sections = [
        "# Memory Optimization Guide for Claude Code v1.0.72",
        "## Overview",
        "### Context Auto-Compact Problem (Issue #49)",
        "### JavaScript Heap Exhaustion (Issue #46)",
        "## Optimization Strategies",
        "### Immediate Fixes",
        "### Configuration Options",
        "## Related Issues",
    ]

    # Issue content requirements
    tracking_issue_title_keywords = [
        "CRITICAL",
        "Memory",
        "Context Management",
        "Hotfix Tracking",
    ]
    tracking_issue_reference_numbers = ["49", "46", "47"]
    tracking_issue_headings = [
        "## Critical Issues",
        "## Impact Assessment",
        "## Resolution Strategy",
    ]
    tracking_issue_keywords = [
        "memory exhaustion",
        "context auto-compact",
        "JavaScript heap",
        "hotfix priority",
    ]

    # PR content requirements
    hotfix_pr_title_keywords = [
        "HOTFIX",
        "Critical memory optimization",
        "issues #49",
        "#46",
    ]
    hotfix_pr_addresses_numbers = ["49", "46"]
    hotfix_pr_headings = [
        "## Summary",
        "## Critical Issues Addressed",
        "## Documentation Changes",
    ]
    hotfix_pr_keywords = [
        "memory optimization",
        "context management",
        "heap exhaustion",
        "v1.0.72 hotfix",
    ]

    # PR #51 update requirements
    pr51_update_keywords = [
        "Technical Implementation",
        "event logging integration",
        "workflow enhancement",
    ]

    # Issue comment requirements
    issue_comment_keywords = [
        "context buffer management",
        "streaming optimization",
        "progressive cleanup",
    ]

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

    # Run verification checks
    print("Verifying critical issue hotfix workflow completion...")

    # 1. Check that hotfix branch exists
    print("1. Verifying hotfix branch exists...")
    if not _check_branch_exists(hotfix_branch_name, headers, github_org):
        print(f"Error: Branch '{hotfix_branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{hotfix_branch_name}' not found"
    print("✓ Hotfix branch created")

    # 2. Check that the memory optimization documentation exists with exact content
    print("2. Verifying MEMORY_OPTIMIZATION.md documentation...")
    memory_doc_content = _get_file_content(
        "docs/MEMORY_OPTIMIZATION.md",
        headers,
        github_org,
        "claude-code",
        hotfix_branch_name,
    )
    if not memory_doc_content:
        print(
            "Error: docs/MEMORY_OPTIMIZATION.md not found in hotfix branch",
            file=sys.stderr,
        )
        return False, "docs/MEMORY_OPTIMIZATION.md not found in hotfix branch"

    if not _check_exact_file_content(memory_doc_content, memory_doc_sections):
        print(
            "Error: MEMORY_OPTIMIZATION.md missing required sections or content",
            file=sys.stderr,
        )
        return False, "MEMORY_OPTIMIZATION.md missing required sections or content"
    print("✓ Memory optimization documentation created with correct content")

    # 3. Find and verify the tracking issue
    print("3. Verifying tracking issue creation and content...")
    tracking_issue = _find_issue_by_title_keyword(
        tracking_issue_keyword, headers, github_org
    )
    if not tracking_issue:
        print(
            f"Error: Tracking issue with keyword '{tracking_issue_keyword}' not found",
            file=sys.stderr,
        )
        return False, f"Tracking issue with keyword '{tracking_issue_keyword}' not found"

    tracking_issue_number = tracking_issue.get("number")
    tracking_issue_title = tracking_issue.get("title", "")
    tracking_issue_body = tracking_issue.get("body", "")

    # Check tracking issue title keywords
    if not _check_title_keywords(tracking_issue_title, tracking_issue_title_keywords):
        print("Error: Tracking issue title missing required keywords", file=sys.stderr)
        return False, "Tracking issue title missing required keywords"

    # Check tracking issue headings, content and references
    if not _check_headings_and_keywords(
        tracking_issue_body, tracking_issue_headings, tracking_issue_keywords
    ):
        print(
            "Error: Tracking issue missing required headings or keywords",
            file=sys.stderr,
        )
        return False, "Tracking issue missing required headings or keywords"

    if not _check_issue_references(
        tracking_issue_body, tracking_issue_reference_numbers
    ):
        print(
            "Error: Tracking issue does not reference required issues #49, #46, #47",
            file=sys.stderr,
        )
        return False, "Tracking issue does not reference required issues #49, #46, #47"
    print("✓ Tracking issue created with correct content and references")

    # 4. Find and verify the hotfix PR
    print("4. Verifying hotfix pull request creation and content...")
    hotfix_pr = _find_pr_by_title_keyword(hotfix_pr_keyword, headers, github_org)
    if not hotfix_pr:
        print(
            f"Error: Hotfix PR with keyword '{hotfix_pr_keyword}' not found",
            file=sys.stderr,
        )
        return False, f"Hotfix PR with keyword '{hotfix_pr_keyword}' not found"

    hotfix_pr_number = hotfix_pr.get("number")
    hotfix_pr_title = hotfix_pr.get("title", "")
    hotfix_pr_body = hotfix_pr.get("body", "")

    # Check hotfix PR title keywords
    if not _check_title_keywords(hotfix_pr_title, hotfix_pr_title_keywords):
        print("Error: Hotfix PR title missing required keywords", file=sys.stderr)
        return False, "Hotfix PR title missing required keywords"

    # Check hotfix PR headings and content
    if not _check_headings_and_keywords(
        hotfix_pr_body, hotfix_pr_headings, hotfix_pr_keywords
    ):
        print("Error: Hotfix PR missing required headings or keywords", file=sys.stderr)
        return False, "Hotfix PR missing required headings or keywords"

    # Check hotfix PR addresses pattern
    if not _check_addresses_pattern(hotfix_pr_body, hotfix_pr_addresses_numbers):
        print(
            "Error: Hotfix PR does not properly address issues #49 and #46",
            file=sys.stderr,
        )
        return False, "Hotfix PR does not properly address issues #49 and #46"

    # Check reference to tracking issue
    if f"#{tracking_issue_number}" not in hotfix_pr_body:
        print(
            f"Error: Hotfix PR does not reference tracking issue #{tracking_issue_number}",
            file=sys.stderr,
        )
        return False, f"Hotfix PR does not reference tracking issue #{tracking_issue_number}"
    print("✓ Hotfix PR created with correct content and references")

    # 5. Check PR #51 has been updated and merged
    print("5. Verifying PR #51 update and merge...")
    pr51 = _get_pr_by_number(51, headers, github_org)
    if not pr51:
        print("Error: PR #51 not found", file=sys.stderr)
        return False, "PR #51 not found"

    pr51_body = pr51.get("body", "")
    pr51_state = pr51.get("state", "")

    # Check PR #51 has been updated with required content
    if not _check_headings_and_keywords(
        pr51_body, ["## Technical Implementation"], pr51_update_keywords
    ):
        print(
            "Error: PR #51 missing updated technical implementation section",
            file=sys.stderr,
        )
        return False, "PR #51 missing updated technical implementation section"

    # Check PR #51 has been merged
    if pr51_state != "closed" or not pr51.get("merged_at"):
        print("Error: PR #51 has not been merged", file=sys.stderr)
        return False, "PR #51 has not been merged"
    print("✓ PR #51 updated and merged successfully")

    # 6. Check tracking issue has implementation comment
    print("6. Verifying tracking issue implementation comment...")
    tracking_issue_comments = _get_issue_comments(
        tracking_issue_number, headers, github_org
    )

    has_implementation_comment = False
    for comment in tracking_issue_comments:
        body = comment.get("body", "")
        has_pr_ref = f"PR #{hotfix_pr_number}" in body
        has_pr51_ref = "PR #51" in body
        has_keywords = all(
            keyword.lower() in body.lower() for keyword in issue_comment_keywords
        )
        if has_pr_ref and has_pr51_ref and has_keywords:
            has_implementation_comment = True
            break

    if not has_implementation_comment:
        msg = (f"Error: Tracking issue #{tracking_issue_number} missing "
               f"implementation comment with required references and keywords")
        print(msg, file=sys.stderr)
        return False, msg
    print("✓ Tracking issue has implementation comment with PR references")

    # 7. Check tracking issue is closed
    print("7. Verifying tracking issue closure...")
    if tracking_issue.get("state") != "closed":
        print(
            f"Error: Tracking issue #{tracking_issue_number} is not closed",
            file=sys.stderr,
        )
        return False, f"Tracking issue #{tracking_issue_number} is not closed"
    print("✓ Tracking issue closed successfully")

    print("\n✅ All verification checks passed!")
    print("Critical issue hotfix workflow completed successfully:")
    print(f"  - Tracking Issue #{tracking_issue_number}: {tracking_issue.get('title')}")
    print(f"  - Hotfix PR #{hotfix_pr_number}: {hotfix_pr.get('title')}")
    print(f"  - Branch: {hotfix_branch_name}")
    print("  - PR #51 merged: ✓")
    print("  - Memory optimization documentation: ✓")

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
