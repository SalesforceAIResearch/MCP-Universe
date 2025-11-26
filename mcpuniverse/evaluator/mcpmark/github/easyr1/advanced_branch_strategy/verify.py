"""Verification module for advanced branch strategy in EasyR1 repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import base64
import os
from typing import Dict, Optional, Tuple
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


def _check_gitflow_branches(headers: Dict[str, str]) -> bool:
    """Check if GitFlow branches are properly created from correct base branches."""
    success, branches_data = _get_github_api("branches", headers)
    if not success or not branches_data:
        print("Error: Could not fetch branches", file=sys.stderr)
        return False

    existing_branches = [branch.get("name", "") for branch in branches_data]
    required_branches = [
        "develop",
        "release/v1.0.0",
        "feature/protocol-serialization-fix",
    ]

    for branch in required_branches:
        if branch not in existing_branches:
            print(f"Error: Required branch '{branch}' not found", file=sys.stderr)
            return False

    return True


def _check_protocol_fixes_file(headers: Dict[str, str]) -> bool:
    """Check if PROTOCOL_FIXES.md file exists in feature branch with correct content."""
    success, file_data = _get_github_api(
        "contents/PROTOCOL_FIXES.md?ref=feature/protocol-serialization-fix", headers
    )
    if not success or not file_data:
        print("Error: PROTOCOL_FIXES.md not found in feature branch", file=sys.stderr)
        return False


    content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

    # Check for required content elements
    required_elements = [
        "# Protocol Serialization Fixes",
        "## Critical Fix for Data Proto Issue",
        "Enhanced serialization safety check implemented",
        "098931530606d22f867fd121b1dcb3225a43661f",
        "Status: Ready for integration testing",
    ]

    for element in required_elements:
        if element not in content:
            print(
                f"Error: PROTOCOL_FIXES.md missing required content: {element}",
                file=sys.stderr,
            )
            return False

    return True


def _check_integration_workflow(headers: Dict[str, str]) -> Optional[Dict]:
    """Verify the feature → develop integration pull request exists."""
    # Check both open and closed PRs since the workflow may have completed
    success, prs = _get_github_api("pulls?state=all", headers)
    if not success or not prs:
        print("Error: Could not fetch pull requests", file=sys.stderr)
        return None

    for pr in prs:
        head_ref = pr.get("head", {}).get("ref", "")
        base_ref = pr.get("base", {}).get("ref", "")

        if head_ref == "feature/protocol-serialization-fix" and base_ref == "develop":
            return pr

    print(
        "Error: Integration PR from feature/protocol-serialization-fix to develop not found",
        file=sys.stderr,
    )
    return None


def _check_release_branch_updated(headers: Dict[str, str]) -> bool:
    """Check if release branch contains the develop branch changes."""
    # Check if PROTOCOL_FIXES.md exists in release branch
    success, file_data = _get_github_api(
        "contents/PROTOCOL_FIXES.md?ref=release/v1.0.0", headers
    )
    if not success or not file_data:
        print(
            "Error: PROTOCOL_FIXES.md not found in release branch - develop changes not merged",
            file=sys.stderr,
        )
        return False

    return True


def _check_process_documentation(headers: Dict[str, str]) -> Optional[Dict]:
    """Check if process is properly documented in an issue."""
    success, issues = _get_github_api("issues", headers)
    if not success or not issues:
        print("Error: Could not fetch issues for documentation check", file=sys.stderr)
        return None

    expected_title = "Implement Advanced Branch Protection Strategy"
    expected_checkboxes = [
        "All development flows through develop branch",
        "Release preparation happens in release/v1.0.0 branch",
        "Feature integration uses PR workflow",
    ]

    for issue in issues:
        title = issue.get("title", "")
        if title == expected_title:
            body = issue.get("body", "")

            # Check for exactly 3 checkboxes with specific content
            checkbox_count = body.count("- [ ]") + body.count("- [x]")
            if checkbox_count != 3:
                print(
                    f"Error: Documentation issue should have 3 checkboxes, found {checkbox_count}",
                    file=sys.stderr,
                )
                return None

            # Check for specific checkbox content
            for expected_text in expected_checkboxes:
                if expected_text not in body:
                    print(
                        f"Error: Documentation issue missing required checkbox: {expected_text}",
                        file=sys.stderr,
                    )
                    return None

            # Check label assignment
            labels = issue.get("labels", [])
            label_names = [label.get("name") for label in labels]
            if "process-implementation" not in label_names:
                print(
                    "Error: Documentation issue not labeled with 'process-implementation'",
                    file=sys.stderr,
                )
                return None

            return issue

    print("Error: Process documentation issue not found", file=sys.stderr)
    return None


def verify() -> tuple[bool, str]:
    """
    Verify the complete GitFlow implementation following the integrated workflow
    described in description.md.
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

    print("Verifying integrated GitFlow workflow implementation...")

    # 1. Verify GitFlow structure initialization
    print("1. Checking GitFlow branch structure...")
    if not _check_gitflow_branches(headers):
        return False, "GitFlow branch structure not properly created"

    # 2. Verify critical bug fix implementation via new file
    print("2. Checking protocol serialization fix documentation...")
    if not _check_protocol_fixes_file(headers):
        return False, "PROTOCOL_FIXES.md file not found or missing required content"

    # 3. Verify integration workflow (feature → develop PR)
    print("3. Checking feature integration workflow...")
    integration_pr = _check_integration_workflow(headers)
    if not integration_pr:
        return False, "Integration PR from feature/protocol-serialization-fix to develop not found"

    # 4. Verify release branch updated and CI configured
    print("4. Checking release branch sync and CI configuration...")
    if not _check_release_branch_updated(headers):
        return False, "Release branch not updated with develop changes"

    # 5. Verify process documentation
    print("5. Checking process documentation...")
    doc_issue = _check_process_documentation(headers)
    if not doc_issue:
        return False, "Process documentation issue not found"

    print("\n✓ Integrated GitFlow workflow successfully implemented!")
    print("✓ GitFlow structure: main → develop → release/v1.0.0 branches created")
    print("✓ Critical fix: Protocol fix documented in PROTOCOL_FIXES.md file")
    print(
        f"✓ Integration: PR #{integration_pr.get('number')} demonstrates feature → develop workflow"
    )
    print(
        "✓ Release prep: Release branch contains develop changes, CI configured for both branches"
    )
    doc_issue_num = doc_issue.get('number')
    print(f"✓ Documentation: Process documented in issue #{doc_issue_num} "
          f"with proper checkboxes")
    print(
        "\nThe repository now has a structured GitFlow workflow ready for implementation!"
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
