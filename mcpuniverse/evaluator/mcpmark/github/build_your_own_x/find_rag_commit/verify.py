"""Verification module for finding RAG commit in build-your-own-x repository."""
# pylint: disable=duplicate-code,import-error,astroid-error
import sys
import os
import base64
from typing import Dict, Optional, Tuple
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
    """Verify the find RAG commit SHA task."""
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

    print("Verifying RAG commit SHA task...")

    # Expected commit SHA for RAG for Document Search
    expected_sha = "048cd3b3de70e4b429057891576ea394a50cdf48"

    # 1. Check if ANSWER.md exists in the repository
    print("1. Checking if ANSWER.md exists...")
    content = _get_file_content("ANSWER.md", headers, github_org)
    if not content:
        print("Error: ANSWER.md not found in repository", file=sys.stderr)
        return False, "ANSWER.md not found in repository"
    print("✓ ANSWER.md found")

    # 2. Check the content matches expected SHA
    print("2. Checking commit SHA...")
    content = content.strip()

    if content != expected_sha:
        msg = (f"Error: Incorrect commit SHA. Expected {expected_sha}, "
               f"got: {content}")
        print(msg, file=sys.stderr)
        return False, f"Incorrect commit SHA. Expected {expected_sha}, got: {content}"
    print("✓ Commit SHA is correct")

    # 3. Verify the commit exists
    print("3. Verifying the commit exists...")
    success, commit_data = _get_github_api(f"commits/{content}", headers, github_org)
    if not success or not commit_data:
        print(f"Error: Commit {content} not found in repository", file=sys.stderr)
        return False, f"Commit {content} not found in repository"
    print(f"✓ Commit {content} exists")

    print("\n✅ All verification checks passed!")
    print("Task completed successfully:")
    print(f"  - ANSWER.md created with correct commit SHA: {content}")
    print("  - Commit exists in the repository")
    commit_msg = commit_data.get('commit', {}).get('message', '')
    print(f"  - Commit message: {commit_msg}")

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
