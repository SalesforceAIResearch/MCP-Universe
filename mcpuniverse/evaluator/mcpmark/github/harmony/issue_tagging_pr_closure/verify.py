"""Verification module for issue tagging PR closure in harmony repository."""
# pylint: disable=R0911,R0915,astroid-error,duplicate-code,import-error
import base64
import sys
import os
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


def _find_issue_by_title_keywords(
    title_keywords: List[str], headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Optional[Dict]:
    """Find an issue by title keywords and return the issue data."""
    for state in ["open", "closed"]:
        success, issues = _get_github_api(
            f"issues?state={state}&per_page=100", headers, org, repo
        )
        if success and issues:
            for issue in issues:
                title = issue.get("title", "").lower()
                if all(keyword.lower() in title for keyword in title_keywords):
                    return issue
    return None


def _find_pr_by_title_keywords(
    title_keywords: List[str], headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Optional[Dict]:
    """Find a PR by title keywords and return the PR data."""
    for state in ["open", "closed"]:
        success, prs = _get_github_api(
            f"pulls?state={state}&per_page=100", headers, org, repo
        )
        if success and prs:
            for pr in prs:
                title = pr.get("title", "").lower()
                if all(keyword.lower() in title for keyword in title_keywords):
                    return pr
    return None


def _check_labels(labels: List[Dict], required_labels: List[str]) -> bool:
    """Check if required labels are present."""
    label_names = [label.get("name", "").lower() for label in labels]
    return all(req_label.lower() in label_names for req_label in required_labels)


def _check_headings_and_keywords(
    body: str, headings: List[str], keywords: List[str]
) -> bool:
    """Check if body contains required headings and keywords."""
    if not body:
        return False
    has_headings = all(heading in body for heading in headings)
    has_keywords = all(keyword.lower() in body.lower() for keyword in keywords)
    return has_headings and has_keywords


def _check_issue_reference(body: str, issue_number: int) -> bool:
    """Check if body contains reference to the issue."""
    if not body:
        return False
    return f"#{issue_number}" in body or f"Addresses #{issue_number}" in body


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


def _get_pr_comments(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> List[Dict]:
    """Get all comments for a PR."""
    success, comments = _get_github_api(
        f"issues/{pr_number}/comments", headers, org, repo
    )
    if success and comments:
        return comments
    return []


def _check_pr_technical_comment(comments: List[Dict], keywords: List[str]) -> bool:
    """Check if PR has a comment with technical analysis containing required keywords."""
    for comment in comments:
        body = comment.get("body", "")
        if body and all(keyword.lower() in body.lower() for keyword in keywords):
            return True
    return False


def _check_issue_comment_with_pr_ref(
    comments: List[Dict], pr_number: int, keywords: List[str]
) -> bool:
    """Check if issue has a comment referencing the PR with required keywords."""
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


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the issue tagging and PR closure workflow meets the
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
    branch_name = "feat/esm-migration-attempt"

    # Issue requirements
    issue_title_keywords = [
        "Upgrade JavaScript demo to use ESM imports",
        "modern module system",
    ]
    issue_headings = ["## Problem", "## Proposed Solution", "## Benefits"]
    issue_keywords = ["CommonJS", "ESM imports", "module bundling", "modern JavaScript"]
    issue_labels = ["enhancement"]

    # PR requirements
    pr_title_keywords = ["Upgrade JavaScript demo to ESM imports", "modern modules"]
    pr_headings = ["## Summary", "## Changes", "## Issues Discovered"]
    pr_keywords = [
        "ESM migration",
        "webpack configuration",
        "module compatibility",
        "breaking changes",
    ]
    pr_labels = ["enhancement", "needs-investigation", "wontfix"]

    # File content requirements
    package_json_keywords = ['"type": "module"', "webpack", "@openai/harmony"]
    main_js_keywords = [
        "import { HarmonyEncoding }",
        "ESM import attempt",
        "harmony core",
    ]

    # Comment requirements
    pr_technical_keywords = [
        "CommonJS required",
        "breaking compatibility",
        "build system constraints",
        "core tokenization",
        "approach is not viable",
    ]
    issue_comment_keywords = [
        "technical constraints",
        "CommonJS dependency",
        "harmony core limitations",
        "build system compatibility",
        "not viable at this time",
    ]
    pr_closure_keywords = [
        "architectural limitations",
        "future consideration",
        "core refactoring required",
        "cannot be merged",
    ]
    issue_closure_keywords = [
        "closing as not planned",
        "architectural constraints",
        "future implementation blocked",
        "requires core redesign",
    ]

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Run verification checks
    print("Verifying issue tagging and PR closure workflow completion...")

    # 1. Check that feature branch exists
    print("1. Verifying feature branch exists...")
    if not _check_branch_exists(branch_name, headers, github_org):
        print(f"Error: Branch '{branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{branch_name}' not found"

    # 2. Check that implementation files exist with required content
    print("2. Verifying ESM implementation files...")
    if not _check_file_content(
        branch_name,
        "javascript/demo/package.json",
        package_json_keywords,
        headers,
        github_org,
    ):
        print(
            "Error: javascript/demo/package.json not found or missing required content",
            file=sys.stderr,
        )
        return False, "javascript/demo/package.json not found or missing required content"

    if not _check_file_content(
        branch_name,
        "javascript/demo/src/main.js",
        main_js_keywords,
        headers,
        github_org,
    ):
        print(
            "Error: javascript/demo/src/main.js not found or missing required content",
            file=sys.stderr,
        )
        return False, "javascript/demo/src/main.js not found or missing required content"

    # 3. Find the created issue
    print("3. Verifying issue creation and content...")
    issue = _find_issue_by_title_keywords(issue_title_keywords, headers, github_org)
    if not issue:
        print(
            "Error: Issue with title containing required keywords not found",
            file=sys.stderr,
        )
        return False, "Issue with title containing required keywords not found"

    issue_number = issue.get("number")
    issue_body = issue.get("body", "")
    issue_labels = issue.get("labels", [])

    # Check issue content
    if not _check_headings_and_keywords(issue_body, issue_headings, issue_keywords):
        print("Error: Issue missing required headings or keywords", file=sys.stderr)
        return False, "Issue missing required headings or keywords"

    # Check issue references #26
    if "#26" not in issue_body:
        print("Error: Issue does not reference issue #26", file=sys.stderr)
        return False, "Issue does not reference issue #26"

    # Check issue labels
    if not _check_labels(issue_labels, issue_labels):
        print(f"Error: Issue missing required labels: {issue_labels}", file=sys.stderr)
        return False, f"Issue missing required labels: {issue_labels}"

    # 4. Find the created PR
    print("4. Verifying pull request creation and content...")
    pr = _find_pr_by_title_keywords(pr_title_keywords, headers, github_org)
    if not pr:
        print(
            "Error: PR with title containing required keywords not found",
            file=sys.stderr,
        )
        return False, "PR with title containing required keywords not found"

    pr_number = pr.get("number")
    pr_body = pr.get("body", "")
    pr_labels = pr.get("labels", [])
    pr_state = pr.get("state")

    # Check PR content
    if not _check_headings_and_keywords(pr_body, pr_headings, pr_keywords):
        print("Error: PR missing required headings or keywords", file=sys.stderr)
        return False, "PR missing required headings or keywords"

    # Check PR references issue
    if not _check_issue_reference(pr_body, issue_number):
        print(f"Error: PR does not reference issue #{issue_number}", file=sys.stderr)
        return False, f"PR does not reference issue #{issue_number}"

    # Check PR labels
    if not _check_labels(pr_labels, pr_labels):
        print(f"Error: PR missing required labels: {pr_labels}", file=sys.stderr)
        return False, f"PR missing required labels: {pr_labels}"

    # 5. Check PR is closed (not merged)
    print("5. Verifying PR is closed without merging...")
    if pr_state != "closed":
        print(f"Error: PR #{pr_number} is not closed", file=sys.stderr)
        return False, f"PR #{pr_number} is not closed"

    if pr.get("merged_at"):
        print(
            f"Error: PR #{pr_number} was merged (should be closed without merging)",
            file=sys.stderr,
        )
        return False, f"PR #{pr_number} was merged (should be closed without merging)"

    # 6. Check PR technical analysis comment
    print("6. Verifying PR technical analysis comment...")
    pr_comments = _get_pr_comments(pr_number, headers, github_org)
    if not _check_pr_technical_comment(pr_comments, pr_technical_keywords):
        print(
            "Error: PR missing technical analysis comment with required keywords",
            file=sys.stderr,
        )
        return False, "PR missing technical analysis comment with required keywords"

    # 7. Check issue comment with PR reference
    print("7. Verifying issue comment referencing PR...")
    issue_comments = _get_issue_comments(issue_number, headers, github_org)
    if not _check_issue_comment_with_pr_ref(
        issue_comments, pr_number, issue_comment_keywords
    ):
        msg = (f"Error: Issue #{issue_number} missing comment referencing "
               f"PR #{pr_number} with required keywords")
        print(msg, file=sys.stderr)
        return False, msg

    # 8. Check PR closure comment with required keywords
    print("8. Verifying PR closure comment...")
    pr_closure_comment_found = False
    for comment in pr_comments:
        body = comment.get("body", "")
        if body and all(
            keyword.lower() in body.lower() for keyword in pr_closure_keywords
        ):
            pr_closure_comment_found = True
            break

    if not pr_closure_comment_found:
        print(
            "Error: PR missing closure comment with required keywords", file=sys.stderr
        )
        return False, "PR missing closure comment with required keywords"

    # 9. Verify issue is closed
    print("9. Verifying issue is closed...")
    if issue.get("state") != "closed":
        print(f"Error: Issue #{issue_number} should be closed", file=sys.stderr)
        return False, f"Issue #{issue_number} should be closed"

    # 10. Check issue closure comment with required keywords
    print("10. Verifying issue closure comment...")
    issue_closure_comment_found = False
    for comment in issue_comments:
        body = comment.get("body", "")
        if body and all(
            keyword.lower() in body.lower() for keyword in issue_closure_keywords
        ):
            issue_closure_comment_found = True
            break

    if not issue_closure_comment_found:
        print(
            "Error: Issue missing closure comment with required keywords",
            file=sys.stderr,
        )
        return False, "Issue missing closure comment with required keywords"

    print("\n✓ All verification checks passed!")
    print("Issue tagging and PR closure workflow completed successfully:")
    print(f"  - Issue #{issue_number}: {issue.get('title')} (closed)")
    print(f"  - PR #{pr_number}: {pr.get('title')} (closed without merging)")
    print(f"  - Branch: {branch_name}")
    print("  - All comments contain required keywords")
    print("  - Technical constraints properly documented and communicated")
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
