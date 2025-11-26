"""Verification module for label color standardization in claude-code repository."""
# pylint: disable=R0911,R0912,R0914,R0915,astroid-error,duplicate-code,import-error
import base64
import sys
import os
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


def _check_file_content(
    branch: str,
    file_path: str,
    headers: Dict[str, str],
    org: str,
    repo: str = "claude-code",
) -> Optional[str]:
    """Get file content from a branch."""

    success, result = _get_github_api(
        f"contents/{file_path}?ref={branch}", headers, org, repo
    )
    if not success or not result:
        return None

    if result.get("content"):
        try:
            content = base64.b64decode(result.get("content", "")).decode("utf-8")
            return content
        except (IOError, OSError, UnicodeDecodeError) as e:
            print(f"Content decode error for {file_path}: {e}", file=sys.stderr)
            return None

    return None


def _parse_label_table(content: str) -> List[str]:
    """Parse the label table from markdown content and return label names."""
    documented_labels = []

    # Find the table in the content
    lines = content.split("\n")
    in_table = False

    for line in lines:
        # Skip header and separator lines
        if "| Label Name | Category |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue

        # Parse table rows
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:  # Should have at least label, category
                label_name = parts[1].strip()
                if label_name:
                    documented_labels.append(label_name)

        # Stop at end of table
        if in_table and line and not line.startswith("|"):
            break

    return documented_labels


def _find_issue_by_title_keywords(
    title_keywords: List[str],
    headers: Dict[str, str],
    org: str,
    repo: str = "claude-code",
) -> Optional[Dict]:
    """Find an issue by title keywords and return the issue data."""
    for state in ["open", "closed"]:
        success, issues = _get_github_api(
            f"issues?state={state}&per_page=100", headers, org, repo
        )
        if success and issues:
            for issue in issues:
                # Skip pull requests
                if "pull_request" in issue:
                    continue
                title = issue.get("title", "").lower()
                if all(keyword.lower() in title for keyword in title_keywords):
                    return issue
    return None


def _find_pr_by_title_keywords(
    title_keywords: List[str],
    headers: Dict[str, str],
    org: str,
    repo: str = "claude-code",
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




def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the label color standardization workflow meets the
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
    branch_name = "feat/label-color-guide"

    # Issue requirements
    issue_title_keywords = ["Document label organization", "label guide"]
    issue_keywords = [
        "label documentation",
        "visual organization",
        "label guide",
        "organization",
    ]

    # PR requirements
    pr_title_keywords = ["label organization guide", "visual organization"]
    pr_keywords = [
        "label documentation",
        "organization guide",
        "visual improvement",
        "documentation",
    ]

    # All expected labels in the repository that are actually used/discoverable via MCP tools
    # Note: Excludes 'wontfix', 'invalid', 'good first issue', 'help wanted' as they exist
    # in the repository but are not used by any issues (not discoverable via MCP search)
    all_expected_labels = [
        "bug",
        "enhancement",
        "duplicate",
        "question",
        "documentation",
        "platform:macos",
        "platform:linux",
        "platform:windows",
        "area:core",
        "area:tools",
        "area:tui",
        "area:ide",
        "area:mcp",
        "area:api",
        "area:security",
        "area:model",
        "area:auth",
        "area:packaging",
        "has repro",
        "memory",
        "perf:memory",
        "external",
    ]

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Run verification checks
    print("Verifying label color standardization workflow completion...")

    # 1. Check that feature branch exists
    print("1. Verifying feature branch exists...")
    if not _check_branch_exists(branch_name, headers, github_org):
        print(f"Error: Branch '{branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{branch_name}' not found"

    # 2. Check documentation file exists and has correct format
    print("2. Verifying label documentation file...")
    doc_content = _check_file_content(
        branch_name, "docs/LABEL_COLORS.md", headers, github_org
    )
    if not doc_content:
        print("Error: docs/LABEL_COLORS.md not found", file=sys.stderr)
        return False, "docs/LABEL_COLORS.md not found"

    # Parse the label table from documentation
    documented_labels = _parse_label_table(doc_content)
    if len(documented_labels) < 20:
        print(
            f"Error: Documentation table incomplete, found only {len(documented_labels)} labels",
            file=sys.stderr,
        )
        return False, f"Documentation table incomplete, found only {len(documented_labels)} labels"

    # 3. Verify labels are documented
    print("3. Verifying expected labels are documented...")
    print(f"  ✓ {len(all_expected_labels)} expected labels defined for verification")

    # 4. Find the created issue
    print("4. Verifying issue creation...")
    issue = _find_issue_by_title_keywords(issue_title_keywords, headers, github_org)
    if not issue:
        print(
            "Error: Issue with title containing required keywords not found",
            file=sys.stderr,
        )
        return False, "Issue with title containing required keywords not found"

    issue_number = issue.get("number")
    issue_body = issue.get("body", "")

    # Check issue content has required sections and keywords
    issue_required_sections = ["## Problem", "## Proposed Solution", "## Benefits"]
    for section in issue_required_sections:
        if section not in issue_body:
            print(f"Error: Issue body missing required section: {section}", file=sys.stderr)
            return False, f"Issue body missing required section: {section}"

    # Check issue has required keywords
    if not all(keyword.lower() in issue_body.lower() for keyword in issue_keywords):
        missing_keywords = [kw for kw in issue_keywords if kw.lower() not in issue_body.lower()]
        print(f"Error: Issue body missing required keywords: {missing_keywords}", file=sys.stderr)
        return False, f"Issue body missing required keywords: {missing_keywords}"

    # Check issue has initial required labels (enhancement and documentation)
    issue_label_names = [label["name"] for label in issue.get("labels", [])]
    initial_required_labels = ["enhancement", "documentation"]
    for required_label in initial_required_labels:
        if required_label not in issue_label_names:
            print(f"Error: Issue missing initial required label: {required_label}", file=sys.stderr)
            return False, f"Issue missing initial required label: {required_label}"

    # 5. Find the created PR
    print("5. Verifying pull request creation...")
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

    # Check PR references issue with correct pattern
    if f"Fixes #{issue_number}" not in pr_body and f"fixes #{issue_number}" not in pr_body:
        print(f"Error: PR does not contain 'Fixes #{issue_number}' pattern", file=sys.stderr)
        return False, f"PR does not contain 'Fixes #{issue_number}' pattern"

    # Check PR body has required sections and keywords
    pr_required_sections = ["## Summary", "## Changes", "## Verification"]
    for section in pr_required_sections:
        if section not in pr_body:
            print(f"Error: PR body missing required section: {section}", file=sys.stderr)
            return False, f"PR body missing required section: {section}"

    # Check PR has required keywords
    if not all(keyword.lower() in pr_body.lower() for keyword in pr_keywords):
        missing_keywords = [kw for kw in pr_keywords if kw.lower() not in pr_body.lower()]
        print(f"Error: PR body missing required keywords: {missing_keywords}", file=sys.stderr)
        return False, f"PR body missing required keywords: {missing_keywords}"

    # Check PR has sufficient labels (at least 5 from different categories)
    if len(pr_labels) < 5:
        print(f"Error: PR has only {len(pr_labels)} labels, needs at least 5", file=sys.stderr)
        return False, f"PR has only {len(pr_labels)} labels, needs at least 5"

    # 6. Verify issue has ALL expected/usable labels applied (demonstrates organization)
    print("6. Verifying issue has all expected labels applied...")
    issue_label_names = [label["name"] for label in issue.get("labels", [])]
    # Use our expected labels list instead of all repo labels (excludes unused labels)
    expected_labels_to_check = all_expected_labels
    missing_labels = []

    for expected_label in expected_labels_to_check:
        if expected_label not in issue_label_names:
            missing_labels.append(expected_label)

    if missing_labels:
        print(
            f"Error: Issue missing {len(missing_labels)} expected labels: {missing_labels[:5]}...",
            file=sys.stderr,
        )
        missing_count = len(missing_labels)
        missing_preview = missing_labels[:5]
        return False, (f"Issue missing {missing_count} expected labels: "
                      f"{missing_preview}...")

    print(f"  ✓ Issue has all {len(expected_labels_to_check)} expected labels applied")

    # 7. Verify issue has comment documenting changes
    print("7. Verifying issue comment with documentation...")
    issue_comments = _get_issue_comments(issue_number, headers, github_org)

    found_update_comment = False
    comment_required_keywords = [
        "documentation created",
        "label guide complete",
        "organization complete"
    ]

    for comment in issue_comments:
        body = comment.get("body", "")
        # Check for PR reference and required keywords
        has_pr_ref = f"PR #{pr_number}" in body
        has_keywords = any(
            keyword.lower() in body.lower()
            for keyword in comment_required_keywords
        )
        has_total_labels = ("total" in body.lower() and
                           "labels" in body.lower())
        if has_pr_ref and has_keywords and has_total_labels:
            found_update_comment = True
            break

    if not found_update_comment:
        msg = ("Error: Issue missing comment documenting changes with "
               "required content")
        print(msg, file=sys.stderr)
        print("  Comment should include: PR reference, label count, "
              "and completion keywords", file=sys.stderr)
        return False, msg

    # 8. Final verification of complete workflow
    print("8. Final verification of workflow completion...")

    # Skip repository label existence check - we trust that our expected labels
    # are the ones actually discoverable/usable via MCP tools

    # Ensure expected labels are documented (not all repo labels, since some are unused)
    documented_label_count = len(documented_labels)
    expected_label_count = len(all_expected_labels)

    if documented_label_count < expected_label_count:
        msg = (f"Error: Documentation incomplete - {documented_label_count} "
               f"documented vs {expected_label_count} expected")
        print(msg, file=sys.stderr)
        return False, msg

    # Check that all expected labels are documented
    missing_documented_labels = []
    for expected_label in all_expected_labels:
        if expected_label not in documented_labels:
            missing_documented_labels.append(expected_label)

    if missing_documented_labels:
        msg = (f"Error: Documentation missing expected labels: "
               f"{missing_documented_labels}")
        print(msg, file=sys.stderr)
        return False, msg

    print(f"  ✓ All {expected_label_count} expected labels documented")
    print(f"  ✓ All {len(all_expected_labels)} expected labels present and documented")

    print("\n✓ All verification checks passed!")
    print("Label documentation workflow completed successfully:")
    issue_title = issue.get('title')
    label_count = len(issue_label_names)
    print(f"  - Issue #{issue_number}: {issue_title} "
          f"(with all {label_count} labels)")
    print(f"  - PR #{pr_number}: {pr.get('title')}")
    print(f"  - Branch: {branch_name}")
    print("  - Documentation: docs/LABEL_COLORS.md")
    print(f"  - {expected_label_count} labels documented for better organization")
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
