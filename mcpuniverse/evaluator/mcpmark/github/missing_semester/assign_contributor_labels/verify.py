"""Verification module for assigning contributor labels in missing-semester repository."""
# pylint: disable=duplicate-code,import-error,astroid-error
import sys
import os
from typing import Dict, Optional, Tuple, List
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], org: str, repo: str = "missing-semester"
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


def _get_issue_labels(
    issue_number: int,
    headers: Dict[str, str],
    org: str,
    repo: str = "missing-semester"
) -> Optional[List[str]]:
    """Get labels for a specific issue/PR."""
    success, result = _get_github_api(f"issues/{issue_number}", headers, org, repo)
    if not success or not result:
        return None

    labels = result.get("labels", [])
    return [label["name"] for label in labels]


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the labels were assigned correctly to issues and PRs.
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
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    print("Verifying contributor labels assignment task completion...")

    # Expected labels configuration
    expected_labels = {
        # Issues
        9: ["assigned-jonhoo", "assigned-anishathalye"],  # Issue #9
        14: ["assigned-jonhoo", "assigned-anishathalye"],  # Issue #14
        15: ["assigned-anishathalye"],  # Issue #15
        # PRs
        21: ["assigned-anishathalye"],  # PR #21
        22: ["assigned-anishathalye"],  # PR #22
        23: ["assigned-anishathalye"],  # PR #23
        24: ["assigned-anishathalye"],  # PR #24
    }

    for item_number, expected in expected_labels.items():
        item_type = "Issue" if item_number in [9, 14, 15] else "PR"
        print(f"\nChecking {item_type} #{item_number}...")

        labels = _get_issue_labels(item_number, headers, github_org, "missing-semester")

        if labels is None:
            print(f"  ❌ Failed to retrieve {item_type} #{item_number}", file=sys.stderr)
            return False, f"Failed to retrieve {item_type} #{item_number}"

        # Sort both lists for comparison
        labels_sorted = sorted(labels)
        expected_sorted = sorted(expected)

        if labels_sorted == expected_sorted:
            print(f"  ✅ {item_type} #{item_number} has correct labels: {labels_sorted}")
        else:
            print(f"  ❌ {item_type} #{item_number} has incorrect labels", file=sys.stderr)
            print(f"     Expected: {expected_sorted}", file=sys.stderr)
            print(f"     Found: {labels_sorted}", file=sys.stderr)
            msg = (f"{item_type} #{item_number} has incorrect labels. "
                   f"Expected: {expected_sorted}, Found: {labels_sorted}")
            return False, msg

    print("\n✅ All verification checks passed!")
    print("Contributor labels assignment task completed successfully:")
    print("  - Issues #9 and #14 have both 'assigned-jonhoo' and 'assigned-anishathalye' labels")
    print("  - Issue #15 and all 4 open PRs have 'assigned-anishathalye' label")
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
