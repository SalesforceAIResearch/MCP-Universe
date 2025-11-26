"""Verification module for config parameter audit in EasyR1 repository."""
# pylint: disable=duplicate-code,import-error,astroid-error
import base64
import sys
import os
import json
import re
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


def _get_analysis_results(headers: Dict[str, str]) -> Optional[Dict]:
    """Get ANALYSIS_RESULTS.json file content."""
    success, file_data = _get_github_api("contents/ANALYSIS_RESULTS.json", headers)
    if not success:
        return None

    # Decode base64 content

    content = file_data.get("content", "")
    if content:
        try:
            decoded_content = base64.b64decode(content).decode("utf-8")
            return json.loads(decoded_content)
        except (
            requests.RequestException,
            IOError,
            OSError,
            ValueError,
            AttributeError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
        ) as e:
            print(f"Error parsing JSON: {e}", file=sys.stderr)
            return None
    return None


def _verify_commit_data(results: Dict, headers: Dict[str, str]) -> bool:
    """Verify the commit data is accurate."""
    commit_sha = results.get("target_commit_sha")

    # Validate SHA format
    if not re.match(r"^[a-f0-9]{40}$", commit_sha, re.IGNORECASE):
        print(f"Error: Invalid commit SHA format: {commit_sha}", file=sys.stderr)
        return False

    # Get commit details
    success, commit_data = _get_github_api(f"commits/{commit_sha}", headers)
    if not success:
        print(f"Error: Commit {commit_sha} not found in repository", file=sys.stderr)
        return False

    # Verify author
    expected_author = results.get("commit_author")
    actual_author = commit_data.get("author", {}).get("login")
    if expected_author != actual_author:
        print(
            f"Error: Commit author mismatch. Expected: {expected_author}, Actual: {actual_author}",
            file=sys.stderr,
        )
        return False

    # Verify date format
    commit_date = results.get("commit_date")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", commit_date):
        print(
            f"Error: Invalid date format: {commit_date}. Expected YYYY-MM-DD",
            file=sys.stderr,
        )
        return False

    return True


def _verify_parameter_changes(results: Dict, _headers: Dict[str, str]) -> bool:
    """Verify the parameter changes are accurate."""
    param_changes = results.get("parameter_changes", {})

    # Check required parameters exist
    required_params = [
        "micro_batch_size_per_device_for_update",
        "micro_batch_size_per_device_for_experience",
    ]
    for param in required_params:
        if param not in param_changes:
            print(f"Error: Missing parameter change data for: {param}", file=sys.stderr)
            return False

        change_data = param_changes[param]
        if not all(key in change_data for key in ["before", "after", "line_number"]):
            print(
                f"Error: Incomplete change data for parameter: {param}", file=sys.stderr
            )
            return False

    # Verify specific expected values based on known repository state
    update_param = param_changes.get("micro_batch_size_per_device_for_update", {})
    if update_param.get("before") != 4 or update_param.get("after") != 1:
        print(
            "Error: Incorrect values for micro_batch_size_per_device_for_update",
            file=sys.stderr,
        )
        return False

    experience_param = param_changes.get(
        "micro_batch_size_per_device_for_experience", {}
    )
    if experience_param.get("before") != 16 or experience_param.get("after") != 2:
        print(
            "Error: Incorrect values for micro_batch_size_per_device_for_experience",
            file=sys.stderr,
        )
        return False

    return True


def _get_all_issues_with_keywords(headers: Dict[str, str]) -> set:
    """Find all issues in repository that contain the required keywords."""
    required_keywords = ["oom", "memory", "batch", "显存"]
    keyword_issues = set()

    # Get all issues from repository (both open and closed)
    page = 1
    while True:
        success, issues = _get_github_api(
            f"issues?state=all&per_page=100&page={page}", headers
        )
        if not success or not issues:
            break

        for issue in issues:
            issue_number = issue.get("number")
            title = issue.get("title", "").lower()
            body = issue.get("body", "").lower() if issue.get("body") else ""
            issue_text = title + " " + body

            # Check if any keyword appears in title or body
            for keyword in required_keywords:
                if keyword.lower() in issue_text:
                    keyword_issues.add(issue_number)
                    break

        # If we got less than 100 issues, we're done
        if len(issues) < 100:
            break
        page += 1

    return keyword_issues


def _verify_issue_references(results: Dict, headers: Dict[str, str]) -> bool:
    """Verify the issue references contain the required keywords."""
    issue_number_list = results.get("related_issue_number_list")

    if not isinstance(issue_number_list, list) or len(issue_number_list) == 0:
        print(
            "Error: related_issue_number_list must be a non-empty list",
            file=sys.stderr,
        )
        return False

    # Required keywords to search for (case insensitive)
    required_keywords = ["oom", "memory", "batch", "显存"]

    # First, dynamically find all issues that contain the required keywords
    expected_issues = _get_all_issues_with_keywords(headers)
    print(expected_issues)
    provided_issues = set(issue_number_list)

    # Verify each provided issue contains at least one of the required keywords
    for issue_number in issue_number_list:
        if not isinstance(issue_number, int) or issue_number <= 0:
            print(
                f"Error: Invalid issue number format: {issue_number}", file=sys.stderr
            )
            return False

        # Get issue details
        success, issue_data = _get_github_api(f"issues/{issue_number}", headers)
        if not success:
            print(
                f"Error: Issue #{issue_number} not found in repository", file=sys.stderr
            )
            return False

        # Check if issue title or body contains any required keywords
        title = issue_data.get("title", "").lower()
        body = issue_data.get("body", "").lower() if issue_data.get("body") else ""
        issue_text = title + " " + body

        issue_has_keyword = False
        for keyword in required_keywords:
            if keyword.lower() in issue_text:
                issue_has_keyword = True
                break

        if not issue_has_keyword:
            msg = (f"Error: Issue #{issue_number} does not contain any "
                   f"required keywords: {required_keywords}")
            print(msg, file=sys.stderr)
            return False

    # Verify agent found exactly the same issues as our dynamic search
    if provided_issues != expected_issues:
        missing = expected_issues - provided_issues
        extra = provided_issues - expected_issues
        if missing:
            print(
                f"Error: Missing issues that contain required keywords: {missing}",
                file=sys.stderr,
            )
        if extra:
            print(
                f"Error: Extra issues that don't contain required keywords: {extra}",
                file=sys.stderr,
            )
        return False

    issue_count = len(issue_number_list)
    print(f"✓ Found all {issue_count} issues containing required keywords: "
          f"{issue_number_list}")
    return True


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the deep commit analysis meets the requirements.
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

    print("Verifying deep commit analysis completion...")

    # 1. Check ANALYSIS_RESULTS.json exists and is valid JSON
    print("1. Checking ANALYSIS_RESULTS.json exists and is valid...")
    results = _get_analysis_results(headers)
    if not results:
        print("Error: ANALYSIS_RESULTS.json not found or invalid JSON", file=sys.stderr)
        return False, "ANALYSIS_RESULTS.json not found or invalid JSON"

    print("✓ Found valid ANALYSIS_RESULTS.json")

    # 2. Verify commit data accuracy
    print("2. Verifying commit data accuracy...")
    if not _verify_commit_data(results, headers):
        return False, "Commit data verification failed"

    print("✓ Commit SHA, author, and date verified")

    # 3. Verify parameter changes accuracy
    print("3. Verifying parameter changes accuracy...")
    if not _verify_parameter_changes(results, headers):
        return False, "Parameter changes verification failed"

    print("✓ Parameter changes verified with correct before/after values")

    # 4. Verify issue references
    print("4. Verifying issue references...")
    if not _verify_issue_references(results, headers):
        return False, "Issue references verification failed"

    print("\n✓ Task completed successfully!")
    print("Deep commit analysis results verified:")
    print(f"- Found target commit: {results.get('target_commit_sha')}")
    print("- Verified parameter changes: "
          "micro_batch_size_per_device_for_update (4→1), "
          "micro_batch_size_per_device_for_experience (16→2)")
    related_issues = results.get('related_issue_number_list')
    print(f"- Verified memory/performance issue correlations: "
          f"{related_issues}")
    print("- All data obtained through accurate GitHub API analysis")

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
