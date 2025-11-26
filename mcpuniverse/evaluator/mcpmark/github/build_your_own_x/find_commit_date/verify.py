"""Verification module for finding commit date in build-your-own-x repository."""
# pylint: disable=R0911,astroid-error,duplicate-code,import-error
import sys
import os
import base64
from typing import Dict, Optional, Tuple
import re
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], org: str, repo: str = "build-your-own-x"
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


def _get_file_content(
    file_path: str,
    headers: Dict[str, str],
    org: str,
    repo: str = "build-your-own-x",
    ref: str = "master",
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


def verify() -> tuple[bool, str]:
    """Verify the find commit data task for Voxel Engine entries."""
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

    print("Verifying Voxel Engine commit date task...")

    # 1. Check if ANSWER.md exists in the repository
    print("1. Checking if ANSWER.md exists...")
    content = _get_file_content("ANSWER.md", headers, github_org)
    if not content:
        print("Error: ANSWER.md not found in repository", file=sys.stderr)
        return False, "ANSWER.md not found in repository"
    print("✓ ANSWER.md found")

    # 2. Check the content format
    print("2. Checking content format...")
    content = content.strip()

    # The expected date when Daniel Stefanovic added Voxel Engine entries
    # Based on historical records, this should be 2018-07-07
    expected_date = "2018-07-07"

    # Check if the content matches the expected date format (YYYY-MM-DD)
    date_pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(date_pattern, content):
        print(f"Error: Invalid date format. Expected YYYY-MM-DD, got: {content}", file=sys.stderr)
        return False, f"Invalid date format. Expected YYYY-MM-DD, got: {content}"
    print("✓ Date format is correct")

    # 3. Verify the date is correct
    print("3. Verifying the date...")
    if content != expected_date:
        print(f"Error: Incorrect date. Expected {expected_date}, got: {content}", file=sys.stderr)
        return False, f"Incorrect date. Expected {expected_date}, got: {content}"
    print(f"✓ Date is correct: {content}")

    # 4. Verify README.md contains Voxel Engine section
    print("4. Checking if README.md contains Voxel Engine section...")
    readme_content = _get_file_content("README.md", headers, github_org)
    if not readme_content:
        print("Error: README.md not found in repository", file=sys.stderr)
        return False, "README.md not found in repository"

    if "Voxel Engine" not in readme_content:
        print("Error: Voxel Engine section not found in README.md", file=sys.stderr)
        return False, "Voxel Engine section not found in README.md"

    # Check for specific Voxel Engine entries
    voxel_entries = [
        "Let's Make a Voxel Engine",
        "Java Voxel Engine Tutorial"
    ]

    for entry in voxel_entries:
        if entry not in readme_content:
            print(f"Warning: Voxel Engine entry '{entry}' not found in README.md", file=sys.stderr)

    print("✓ Voxel Engine section found in README.md")

    print("\n✅ All verification checks passed!")
    print("Task completed successfully:")
    print(f"  - ANSWER.md created with date: {content}")
    print("  - Date format is correct (YYYY-MM-DD)")
    print("  - Date matches expected creation date for Voxel Engine entries by Daniel Stefanovic")
    print("  - Voxel Engine section exists in README.md")

    return True, ""

def verify_task() -> bool:
    """Legacy function for backward compatibility."""
    success, _ = verify()
    return success


def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
