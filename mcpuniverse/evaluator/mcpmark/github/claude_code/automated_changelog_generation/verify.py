"""Verification module for automated changelog generation in claude-code repository."""
# pylint: disable=R0911,R0912,R0915,astroid-error,duplicate-code,import-error
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
            return False, None
        print(f"API error for {endpoint}: {response.status_code}", file=sys.stderr)
        return False, None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Exception for {endpoint}: {e}", file=sys.stderr)
        return False, None


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


def _find_pr_by_title_keyword(
    keyword: str, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Optional[Dict]:
    """Find a PR by title keyword and return the PR data."""
    for state in ["open", "closed"]:
        success, prs = _get_github_api(
            f"pulls?state={state}&per_page=100", headers, org, repo
        )
        if success and prs:
            for pr in prs:
                if keyword.lower() in pr.get("title", "").lower():
                    return pr
    return None


def _get_pr_merge_commit(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "claude-code"
) -> Optional[Dict]:
    """Get the merge commit for a PR to check merge method."""
    success, pr = _get_github_api(f"pulls/{pr_number}", headers, org, repo)
    if success and pr:
        merge_commit_sha = pr.get("merge_commit_sha")
        if merge_commit_sha:
            success, commit = _get_github_api(
                f"commits/{merge_commit_sha}", headers, org, repo
            )
            if success:
                return commit
    return None


def _check_file_sections(content: str, required_sections: List[str]) -> bool:
    """Check if file content contains required sections."""
    if not content:
        return False
    return all(section in content for section in required_sections)


def _check_issue_references(text: str, issue_numbers: List[int]) -> int:
    """Count how many of the specified issue numbers are referenced in the text."""
    if not text:
        return 0
    count = 0
    for num in issue_numbers:
        if f"#{num}" in text:
            count += 1
    return count


def _check_pr_references(text: str, pr_numbers: List[int]) -> int:
    """Count how many of the specified PR numbers are referenced in the text."""
    if not text:
        return 0
    count = 0
    for num in pr_numbers:
        if f"#{num}" in text or f"PR #{num}" in text:
            count += 1
    return count


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the changelog and migration documentation workflow
    meets the requirements described in description.md.
    """
    # Configuration constants - these are known to us but not explicitly told to the model
    docs_branch_name = "docs/changelog-and-migration"
    docs_pr_keyword = "Generated changelog and migration"

    # Known issue and PR numbers for verification
    expected_bug_issues = [12, 13, 15, 21, 22, 23, 25, 37, 39, 48, 50]
    expected_open_prs = [51, 52, 53]

    # Expected file sections
    changelog_sections = [
        "# Changelog - Recent Fixes",
        "### 🐛 Bug Fixes",
        "### 📚 Documentation",
        "### 🔄 Duplicates",
        "### 📊 Statistics",
    ]

    migration_guide_sections = ["# Migration Guide for Pending Features"]

    issue_analysis_sections = [
        "# Issue Analysis Report",
        "## Closed Issues by Category",
        "## Resolution Patterns",
        "## Platform Impact Analysis",
    ]

    pr_integration_sections = [
        "# Pull Request Integration Strategy",
        "## Open PRs Overview",
        "## Dependencies and Conflicts",
        "## Recommended Merge Order",
        "## Risk Assessment",
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
    print("Verifying changelog and migration documentation workflow...")

    # 1. Check that documentation branch exists
    print("1. Verifying documentation branch exists...")
    if not _check_branch_exists(docs_branch_name, headers, github_org):
        print(f"Error: Branch '{docs_branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{docs_branch_name}' not found"
    print("✓ Documentation branch created")

    # 2. Check changelog file
    print("2. Verifying CHANGELOG-GENERATED.md...")
    changelog_content = _get_file_content(
        "CHANGELOG-GENERATED.md", headers, github_org, "claude-code", docs_branch_name
    )
    if not changelog_content:
        print("Error: CHANGELOG-GENERATED.md not found", file=sys.stderr)
        return False, "CHANGELOG-GENERATED.md not found"

    if not _check_file_sections(changelog_content, changelog_sections):
        print(
            "Error: CHANGELOG-GENERATED.md missing required sections", file=sys.stderr
        )
        return False, "CHANGELOG-GENERATED.md missing required sections"

    # Check that bug issues are referenced
    bug_refs = _check_issue_references(changelog_content, expected_bug_issues)
    if bug_refs < 8:  # At least 8 of the bug issues
        msg = (f"Error: CHANGELOG-GENERATED.md only references "
               f"{bug_refs} bug issues, expected at least 8")
        print(msg, file=sys.stderr)
        return False, (f"CHANGELOG-GENERATED.md only references "
                       f"{bug_refs} bug issues, expected at least 8")

    # Check for platform and area statistics
    if (
        "platform:" not in changelog_content.lower()
        or "area:" not in changelog_content.lower()
    ):
        print(
            "Error: CHANGELOG-GENERATED.md missing platform or area distribution",
            file=sys.stderr,
        )
        return False, "CHANGELOG-GENERATED.md missing platform or area distribution"

    print("✓ Changelog created with proper content")

    # 3. Check migration guide
    print("3. Verifying MIGRATION_GUIDE.md...")
    migration_content = _get_file_content(
        "docs/MIGRATION_GUIDE.md", headers, github_org, "claude-code", docs_branch_name
    )
    if not migration_content:
        print("Error: docs/MIGRATION_GUIDE.md not found", file=sys.stderr)
        return False, "docs/MIGRATION_GUIDE.md not found"

    if not _check_file_sections(migration_content, migration_guide_sections):
        print("Error: MIGRATION_GUIDE.md missing required sections", file=sys.stderr)
        return False, "MIGRATION_GUIDE.md missing required sections"

    # Check that all expected open PRs are mentioned
    pr_refs = _check_pr_references(migration_content, expected_open_prs)
    if pr_refs < 3:
        print(
            f"Error: MIGRATION_GUIDE.md only references {pr_refs}/3 open PRs",
            file=sys.stderr,
        )
        return False, f"MIGRATION_GUIDE.md only references {pr_refs}/3 open PRs"

    print("✓ Migration guide created with proper content")

    # 4. Check issue analysis report
    print("4. Verifying ISSUE_ANALYSIS.md...")
    issue_analysis_content = _get_file_content(
        "reports/ISSUE_ANALYSIS.md",
        headers,
        github_org,
        "claude-code",
        docs_branch_name,
    )
    if not issue_analysis_content:
        print("Error: reports/ISSUE_ANALYSIS.md not found", file=sys.stderr)
        return False, "reports/ISSUE_ANALYSIS.md not found"

    if not _check_file_sections(issue_analysis_content, issue_analysis_sections):
        print("Error: ISSUE_ANALYSIS.md missing required sections", file=sys.stderr)
        return False, "ISSUE_ANALYSIS.md missing required sections"

    # Check for cross-project and memory issue mentions
    if "#50" not in issue_analysis_content and "#48" not in issue_analysis_content:
        print(
            "Warning: ISSUE_ANALYSIS.md may be missing cross-project issue references",
            file=sys.stderr,
        )

    print("✓ Issue analysis report created")

    # 5. Check PR integration plan
    print("5. Verifying PR_INTEGRATION_PLAN.md...")
    pr_plan_content = _get_file_content(
        "reports/PR_INTEGRATION_PLAN.md",
        headers,
        github_org,
        "claude-code",
        docs_branch_name,
    )
    if not pr_plan_content:
        print("Error: reports/PR_INTEGRATION_PLAN.md not found", file=sys.stderr)
        return False, "reports/PR_INTEGRATION_PLAN.md not found"

    if not _check_file_sections(pr_plan_content, pr_integration_sections):
        print(
            "Error: PR_INTEGRATION_PLAN.md missing required sections", file=sys.stderr
        )
        return False, "PR_INTEGRATION_PLAN.md missing required sections"

    # Check that all open PRs are analyzed
    pr_refs_in_plan = _check_pr_references(pr_plan_content, expected_open_prs)
    if pr_refs_in_plan < 3:
        print(
            f"Error: PR_INTEGRATION_PLAN.md only references {pr_refs_in_plan}/3 open PRs",
            file=sys.stderr,
        )
        return False, f"PR_INTEGRATION_PLAN.md only references {pr_refs_in_plan}/3 open PRs"

    print("✓ PR integration plan created")

    # 6. Find and verify the documentation PR
    print("6. Verifying documentation pull request...")
    docs_pr = _find_pr_by_title_keyword(docs_pr_keyword, headers, github_org)
    if not docs_pr:
        # Try alternative keyword
        docs_pr = _find_pr_by_title_keyword(
            "changelog and migration", headers, github_org
        )

    if not docs_pr:
        print("Error: Documentation PR not found", file=sys.stderr)
        return False, "Documentation PR not found"

    pr_body = docs_pr.get("body", "")
    pr_number = docs_pr.get("number")

    # Check PR body sections
    required_sections = [
        "## Summary",
        "## Files Created",
        "## Issues Processed",
        "## PRs Analyzed",
    ]
    missing_sections = []
    for section in required_sections:
        if section not in pr_body:
            missing_sections.append(section)

    if len(missing_sections) > 1:  # Allow 1 missing section for flexibility
        print(
            f"Error: Documentation PR missing sections: {missing_sections}",
            file=sys.stderr,
        )
        return False, f"Documentation PR missing sections: {missing_sections}"

    print("✓ Documentation PR created")

    # 7. Check that the documentation PR has been merged with squash method
    print("7. Verifying documentation PR merge with squash method...")
    if docs_pr.get("state") != "closed" or not docs_pr.get("merged_at"):
        print("Error: Documentation PR has not been merged", file=sys.stderr)
        return False, "Documentation PR has not been merged"

    # Check merge method was squash by examining the merge commit
    merge_commit = _get_pr_merge_commit(pr_number, headers, github_org)
    if merge_commit:
        # Squash merges typically have only one parent (the base branch)
        parents = merge_commit.get("parents", [])
        if len(parents) != 1:
            print(
                f"Warning: Merge commit has {len(parents)} parents, may not be squash merge",
                file=sys.stderr,
            )

        # Check commit message pattern typical of squash merges
        commit_message = merge_commit.get("commit", {}).get("message", "")
        if f"#{pr_number}" not in commit_message:
            print(
                "Warning: Merge commit message may not follow squash merge pattern",
                file=sys.stderr,
            )
    else:
        print("Warning: Could not retrieve merge commit details", file=sys.stderr)

    merged_at = docs_pr.get("merged_at")
    if not merged_at:
        print("Error: Documentation PR merge timestamp not found", file=sys.stderr)
        return False, "Documentation PR merge timestamp not found"

    print("✓ Documentation PR merged successfully")

    print("\n✅ All verification checks passed!")
    print("Changelog and migration documentation completed successfully:")
    print(f"  - Documentation PR #{pr_number} (merged)")
    print(f"  - Branch: {docs_branch_name}")
    print("  - Files created: 4 documentation files")
    print(f"  - Bug issues referenced: {bug_refs}/{len(expected_bug_issues)}")
    print(f"  - Open PRs analyzed: {pr_refs}/{len(expected_open_prs)}")

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
