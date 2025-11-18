"""Verification module for fixing conflicts in harmony repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import os
from typing import Dict, Optional, Tuple
import re
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


def _check_ci_file_exists(
    file_path: str, headers: Dict[str, str], org: str, repo: str = "harmony"
) -> bool:
    """Check if CI file exists in main branch."""
    success, _ = _get_github_api(f"contents/{file_path}?ref=main", headers, org, repo)
    return success


def _check_pr_comments(
    pr_number: int,
    infra_pr_number: int,
    headers: Dict[str, str],
    org: str,
    repo: str = "harmony",
) -> bool:
    """Check if PR has a comment linking to the infrastructure PR using 'PR #[NUMBER]' format."""
    success, comments = _get_github_api(
        f"issues/{pr_number}/comments", headers, org, repo
    )
    if not success or not comments:
        return False

    # Look for "PR #123" pattern (case insensitive)

    for comment in comments:
        body = comment.get("body", "")
        if re.search(rf"PR\s*#{infra_pr_number}", body, re.IGNORECASE):
            return True
    return False


def _find_infrastructure_pr(
    headers: Dict[str, str], org: str, repo: str = "harmony"
) -> Optional[Dict]:
    """Find the infrastructure PR by checking title and body content."""
    success, prs = _get_github_api("pulls?state=all&per_page=50", headers, org, repo)
    if success and prs:
        for pr in prs:
            title = pr.get("title", "").lower()
            body = pr.get("body", "").lower()

            # Check title contains required keywords
            title_ok = "add ci infrastructure" in title and "resolve conflicts" in title

            # Check body contains required elements
            has_reference = "fixes #" in body or "resolves #" in body
            has_prep_text = "prepares infrastructure" in body
            has_github_text = "missing .github directory" in body
            has_workflow_text = "workflow conflicts" in body

            body_ok = (
                has_reference
                and has_prep_text
                and has_github_text
                and has_workflow_text
            )

            if title_ok and body_ok:
                return pr
    return None


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the merge conflict resolution workflow meets the
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

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Run verification checks
    print("Verifying merge conflict resolution workflow completion...")

    # 1. Check that CI infrastructure file exists in main (extracted from conflicted PR)
    print("1. Checking CI infrastructure was added to main...")
    # Check for both CI.yml and ci.yml (case-insensitive)
    ci_exists = _check_ci_file_exists(".github/workflows/CI.yml", headers, github_org)
    if not ci_exists:
        ci_exists = _check_ci_file_exists(".github/workflows/ci.yml", headers, github_org)

    if not ci_exists:
        msg = ("Error: Neither .github/workflows/CI.yml nor "
               ".github/workflows/ci.yml found in main")
        print(msg, file=sys.stderr)
        return False, msg

    # 2. Find infrastructure PR with required title and body content
    print("2. Finding infrastructure PR with required content...")
    infra_pr = _find_infrastructure_pr(headers, github_org)
    if not infra_pr:
        print(
            "Error: No infrastructure PR found with required title and body content",
            file=sys.stderr,
        )
        print(
            "Required title: 'Add CI infrastructure' and 'resolve conflicts'",
            file=sys.stderr,
        )
        print("Required body: reference with 'Fixes #' or 'Resolves #', "
              "'prepares infrastructure', 'missing .github directory', "
              "'workflow conflicts'", file=sys.stderr)
        return False, "No infrastructure PR found with required title and body content"

    print(f"Found infrastructure PR #{infra_pr.get('number')}: {infra_pr.get('title')}")

    # 3. Check that infrastructure PR is merged
    if not infra_pr.get("merged_at"):
        print(
            f"Error: Infrastructure PR #{infra_pr.get('number')} not merged yet",
            file=sys.stderr,
        )
        return False, f"Infrastructure PR #{infra_pr.get('number')} not merged yet"

    # 4. Check that PR #24 is merged
    print("3. Checking that PR #24 is merged...")
    success, pr24 = _get_github_api("pulls/24", headers, github_org)
    if not success or not pr24:
        print("Error: PR #24 not found", file=sys.stderr)
        return False, "PR #24 not found"

    if not pr24.get("merged_at"):
        print("Error: PR #24 is not merged yet", file=sys.stderr)
        return False, "PR #24 is not merged yet"

    # 5. Check that PR #24 has a comment linking to the infrastructure PR
    print("4. Checking that PR #24 has comment linking to infrastructure PR...")
    if not _check_pr_comments(24, infra_pr.get("number"), headers, github_org):
        print(
            f"Error: PR #24 missing comment linking to infrastructure PR #{infra_pr.get('number')}",
            file=sys.stderr,
        )
        infra_pr_num = infra_pr.get('number')
        return False, (f"PR #24 missing comment linking to infrastructure "
                      f"PR #{infra_pr_num}")

    print("\n✓ Task completed successfully!")
    infra_pr_num = infra_pr.get('number')
    print(f"Infrastructure PR #{infra_pr_num} extracted content from "
          f"PR #24 and resolved conflicts")
    print(
        "PR #24 is now merged cleanly and has a comment linking to the infrastructure PR"
    )
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
