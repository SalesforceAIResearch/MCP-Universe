import sys
import os
import requests
import base64
from typing import Dict, Optional, Tuple
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
        elif response.status_code == 404:
            return False, None
        else:
            print(f"API error for {endpoint}: {response.status_code}", file=sys.stderr)
            return False, None
    except Exception as e:
        print(f"Exception for {endpoint}: {e}", file=sys.stderr)
        return False, None


def _get_file_content(
    file_path: str,
    headers: Dict[str, str],
    org: str,
    repo: str = "missing-semester",
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
    except Exception as e:
        print(f"Content decode error for {file_path}: {e}", file=sys.stderr)
        return None


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the most frequently modified file was identified correctly.
    Checks for ANSWER.md file in master branch with the correct content.
    """
    # Expected answer content (excluding GitHub Actions files)
    EXPECTED_CONTENT = "index.md"
    
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
    print("Verifying salient file identification task completion...")

    # 1. Check that ANSWER.md exists in master branch
    print("1. Checking ANSWER.md exists in master branch...")
    answer_content = _get_file_content("ANSWER.md", headers, github_org, "missing-semester", "master")
    
    if not answer_content:
        print("Error: ANSWER.md not found in master branch", file=sys.stderr)
        return False, "ANSWER.md not found in master branch"

    print("✅ ANSWER.md found in master branch")

    # 2. Check that the content matches expected answer
    print("2. Verifying ANSWER.md content...")
    answer_content = answer_content.strip()
    
    if answer_content != EXPECTED_CONTENT:
        print(f"Error: ANSWER.md content does not match expected answer", file=sys.stderr)
        print(f"Expected: {EXPECTED_CONTENT}", file=sys.stderr)
        print(f"Found: {answer_content}", file=sys.stderr)
        return False, f"ANSWER.md content does not match expected answer. Expected: {EXPECTED_CONTENT}, Found: {answer_content}"

    print("✅ ANSWER.md contains correct filename")

    print("\n✅ All verification checks passed!")
    print("Salient file identification task completed successfully:")
    print(f"  - ANSWER.md created in master branch")
    print(f"  - Content: {EXPECTED_CONTENT}")

    return True, ""


def main():
    """Main verification function."""
    success, error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()