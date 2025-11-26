"""Verification module for issue management workflow in mcpmark-cicd repository."""
# pylint: disable=R1702,astroid-error,duplicate-code,import-error
import sys
import os
import time
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv


def _get_github_api(
    endpoint: str, headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, Optional[Dict]]:
    """Make a GET request to GitHub API and return (success, response)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/{endpoint}"
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


def _search_github_issues(
    query: str, headers: Dict[str, str]
) -> Tuple[bool, Optional[List]]:
    """Search GitHub issues using the search API."""
    url = f"https://api.github.com/search/issues?q={query}&per_page=100"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("items", [])
        print(f"Search API error: {response.status_code}", file=sys.stderr)
        return False, None
    except (requests.RequestException, IOError, OSError, ValueError) as e:
        print(f"Search exception: {e}", file=sys.stderr)
        return False, None


def _wait_for_workflow_completion(
    headers: Dict[str, str], owner: str, repo: str, max_wait: int = 90
) -> bool:
    """Wait for GitHub Actions workflows to complete processing."""
    print("⏳ Waiting for GitHub Actions workflows to complete...")

    start_time = time.time()
    expected_runs = 3  # We created 3 test issues
    no_workflow_check_count = 0

    while time.time() - start_time < max_wait:
        try:
            # Check workflow runs
            success, response = _get_github_api(
                "actions/workflows/issue-automation.yml/runs?per_page=20",
                headers,
                owner,
                repo,
            )

            if success and response:
                runs = response.get("workflow_runs", [])
                if len(runs) >= expected_runs:
                    # Check status of recent runs
                    recent_runs = runs[:expected_runs]

                    running_count = 0
                    completed_count = 0
                    failed_count = 0

                    for run in recent_runs:
                        status = run["status"]
                        conclusion = run.get("conclusion")

                        if status == "completed":
                            completed_count += 1
                            if conclusion == "failure":
                                failed_count += 1
                        elif status in ["in_progress", "queued"]:
                            running_count += 1

                    print(
                        f"   Status: {completed_count} completed, {running_count} running/queued"
                    )

                    # Wait until NO workflows are running and we have enough completed runs
                    if running_count == 0 and completed_count >= expected_runs:
                        if failed_count > 0:
                            msg = (f"⚠️ Warning: {failed_count} workflow runs "
                                   f"failed, but continuing verification...")
                            print(msg)

                        print(
                            f"✅ All workflows completed. Found {completed_count} completed runs."
                        )
                        # Additional wait to ensure all issue processing is done
                        print("⏳ Additional wait for issue processing to complete...")
                        time.sleep(5)
                        return True
                elif len(runs) == 0:
                    # No workflow runs found
                    no_workflow_check_count += 1
                    if no_workflow_check_count == 1:
                        print("   No workflow runs found yet, waiting 5 "
                              "seconds and checking once more...")
                        time.sleep(5)
                        continue
                    if no_workflow_check_count >= 2:
                        print("⚠️ No workflow runs detected after 2 checks. "
                              "Workflow may not have been triggered.")
                        print("   Continuing with verification...")
                        return False
                else:
                    print(f"   Waiting for workflow runs... Found {len(runs)}, "
                          f"expected {expected_runs}")

            print(f"⏳ Still waiting... ({int(time.time() - start_time)}s elapsed)")
            time.sleep(5)

        except (requests.RequestException, IOError, OSError, ValueError, KeyError, TypeError) as e:
            print(f"⚠️ Error checking workflow status: {e}")
            time.sleep(5)

    print(f"⚠️ Workflow completion wait timed out after {max_wait}s")
    return False


def _find_issue_by_title(
    title: str, headers: Dict[str, str], owner: str, repo: str
) -> Optional[Dict]:
    """Find an issue by exact title match."""
    success, issues = _search_github_issues(
        f'repo:{owner}/{repo} "{title}" is:issue', headers
    )

    if success and issues:
        for issue in issues:
            if issue.get("title") == title:
                return issue
    return None


def _check_issue_labels(
    issue: Dict, expected_labels: List[str]
) -> Tuple[bool, List[str]]:
    """Check if issue has the expected labels."""
    actual_labels = [label["name"] for label in issue.get("labels", [])]
    missing_labels = [label for label in expected_labels if label not in actual_labels]

    if missing_labels:
        return False, [f"Missing labels: {missing_labels}. Found: {actual_labels}"]
    return True, []


def _check_issue_milestone(
    issue: Dict, expected_milestone: str
) -> Tuple[bool, List[str]]:
    """Check if issue has the expected milestone."""
    milestone = issue.get("milestone")
    if not milestone:
        if expected_milestone:
            return False, [f"No milestone found. Expected: {expected_milestone}"]
        return True, []

    if milestone.get("title") != expected_milestone:
        return False, [
            f"Wrong milestone: {milestone.get('title')}. Expected: {expected_milestone}"
        ]

    return True, []


def _check_issue_comments(
    issue_number: int,
    expected_content: str,
    headers: Dict[str, str],
    owner: str,
    repo: str,
) -> Tuple[bool, List[str]]:
    """Check if issue has a comment containing expected content."""
    success, comments = _get_github_api(
        f"issues/{issue_number}/comments", headers, owner, repo
    )

    if not success:
        return False, ["Failed to get issue comments"]

    if not comments:
        return False, [f"No comments found. Expected comment with: {expected_content}"]

    for comment in comments:
        if expected_content in comment.get("body", ""):
            return True, []

    return False, [f"Expected content '{expected_content}' not found in comments"]


def _find_epic_sub_issues(
    parent_issue_number: int, headers: Dict[str, str], owner: str, repo: str
) -> Tuple[List[Dict], List[str]]:
    """Find sub-issues created for an epic."""
    # Search for each expected sub-task by exact title
    expected_subtasks = [
        "[SUBTASK] Epic: Redesign user dashboard interface - Task 1: Requirements Analysis",
        "[SUBTASK] Epic: Redesign user dashboard interface - Task 2: Design and Architecture",
        "[SUBTASK] Epic: Redesign user dashboard interface - Task 3: Implementation",
        "[SUBTASK] Epic: Redesign user dashboard interface - Task 4: Testing and Documentation",
    ]

    subtasks = []
    errors = []

    for expected_title in expected_subtasks:
        # Search for exact title
        success, issues = _search_github_issues(
            f'repo:{owner}/{repo} "{expected_title}" is:issue', headers
        )

        if not success:
            errors.append(f"Failed to search for sub-issue: {expected_title}")
            continue

        # Find exact match
        found = False
        for issue in issues:
            if issue.get("title") == expected_title:
                # Verify it references the parent issue
                body = issue.get("body", "")
                if (
                    f"#{parent_issue_number}" in body
                    or f"Related to #{parent_issue_number}" in body
                ):
                    subtasks.append(issue)
                    found = True
                    break

        if not found:
            errors.append(
                f"Sub-issue not found or doesn't reference parent: {expected_title}"
            )

    return subtasks, errors


def _check_epic_checklist(
    issue: Dict, subtask_numbers: List[int]
) -> Tuple[bool, List[str]]:
    """Check if epic issue has the Epic Tasks checklist with correct issue references."""
    body = issue.get("body", "")
    errors = []

    if "## Epic Tasks" not in body:
        return False, ["Epic Tasks section not found in issue body"]

    # Check that all subtask issue numbers are referenced in checkbox format
    for number in subtask_numbers:
        # Check for checkbox format: - [ ] #number
        if f"- [ ] #{number}" not in body:
            msg = (f"Sub-issue #{number} not found in Epic Tasks "
                   f"checklist format (expected: '- [ ] #{number}')")
            errors.append(msg)

    # Also verify the expected task names are present
    expected_tasks = [
        "Requirements Analysis",
        "Design and Architecture",
        "Implementation",
        "Testing and Documentation",
    ]

    for task in expected_tasks:
        if task not in body:
            errors.append(f"Task name '{task}' not found in Epic Tasks section")

    if errors:
        return False, errors

    return True, []


def _verify_bug_issue(
    headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, List[str]]:
    """Verify the bug issue requirements."""
    print("\n🐛 Verifying Bug Issue...")
    errors = []

    # Find bug issue
    bug_issue = _find_issue_by_title(
        "Bug: Login form validation not working", headers, owner, repo
    )
    if not bug_issue:
        return False, ["Bug issue 'Bug: Login form validation not working' not found"]

    issue_number = bug_issue["number"]
    print(f"   Found bug issue #{issue_number}")

    # Check labels (including first-time-contributor since it's the first issue)
    expected_labels = ["bug", "priority-high", "needs-review", "first-time-contributor"]
    labels_ok, label_errors = _check_issue_labels(bug_issue, expected_labels)
    if not labels_ok:
        errors.extend(label_errors)
    else:
        print(f"   ✅ Labels verified: {expected_labels}")

    # Check milestone
    milestone_ok, milestone_errors = _check_issue_milestone(bug_issue, "v1.0.0")
    if not milestone_ok:
        errors.extend(milestone_errors)
    else:
        print("   ✅ Milestone verified: v1.0.0")

    # Check comment
    comment_ok, comment_errors = _check_issue_comments(
        issue_number, "Bug Report Guidelines", headers, owner, repo
    )
    if not comment_ok:
        errors.extend(comment_errors)
    else:
        print("   ✅ Bug Report Guidelines comment found")

    return len(errors) == 0, errors


def _verify_epic_issue(
    headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, List[str]]:
    """Verify the epic issue requirements."""
    print("\n🚀 Verifying Epic Issue...")
    errors = []

    # Find epic issue
    epic_issue = _find_issue_by_title(
        "Epic: Redesign user dashboard interface", headers, owner, repo
    )
    if not epic_issue:
        return False, ["Epic issue 'Epic: Redesign user dashboard interface' not found"]

    issue_number = epic_issue["number"]
    print(f"   Found epic issue #{issue_number}")

    # Check labels
    expected_labels = ["epic", "priority-high", "needs-review"]
    labels_ok, label_errors = _check_issue_labels(epic_issue, expected_labels)
    if not labels_ok:
        errors.extend(label_errors)
    else:
        print(f"   ✅ Labels verified: {expected_labels}")

    # Check milestone
    milestone_ok, milestone_errors = _check_issue_milestone(epic_issue, "v1.0.0")
    if not milestone_ok:
        errors.extend(milestone_errors)
    else:
        print("   ✅ Milestone verified: v1.0.0")

    # Check comment
    comment_ok, comment_errors = _check_issue_comments(
        issue_number, "Feature Request Process", headers, owner, repo
    )
    if not comment_ok:
        errors.extend(comment_errors)
    else:
        print("   ✅ Feature Request Process comment found")

    # Find and verify sub-issues
    sub_issues, sub_errors = _find_epic_sub_issues(issue_number, headers, owner, repo)
    if sub_errors:
        errors.extend(sub_errors)
    elif len(sub_issues) != 4:
        errors.append(f"Expected 4 sub-issues, found {len(sub_issues)}")
    else:
        print(f"   ✅ Found {len(sub_issues)} sub-issues")

        # Collect sub-issue numbers for checklist verification
        subtask_numbers = []

        # Verify each sub-issue has correct labels and link to parent
        for sub_issue in sub_issues:
            sub_number = sub_issue["number"]
            subtask_numbers.append(sub_number)

            # Check labels
            sub_labels = [label["name"] for label in sub_issue.get("labels", [])]
            expected_sub_labels = ["enhancement", "needs-review"]

            missing_sub_labels = [
                label for label in expected_sub_labels if label not in sub_labels
            ]
            if missing_sub_labels:
                errors.append(
                    f"Sub-issue #{sub_number} missing labels: {missing_sub_labels}"
                )

            # Verify parent reference in body
            sub_body = sub_issue.get("body", "")
            if (
                f"#{issue_number}" not in sub_body
                and f"Related to #{issue_number}" not in sub_body
            ):
                errors.append(
                    f"Sub-issue #{sub_number} doesn't reference parent issue #{issue_number}"
                )

        if not errors:
            print(
                "   ✅ All 4 sub-tasks created with correct labels and parent references"
            )

        # Check Epic Tasks checklist with correct issue numbers
        checklist_ok, checklist_errors = _check_epic_checklist(
            epic_issue, subtask_numbers
        )
        if not checklist_ok:
            errors.extend(checklist_errors)
        else:
            print(
                f"   ✅ Epic Tasks checklist verified with correct "
                f"issue references: {subtask_numbers}"
            )

    return len(errors) == 0, errors


def _verify_maintenance_issue(
    headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, List[str]]:
    """Verify the maintenance issue requirements."""
    print("\n🔧 Verifying Maintenance Issue...")
    errors = []

    # Find maintenance issue
    maintenance_issue = _find_issue_by_title(
        "Weekly maintenance cleanup and refactor", headers, owner, repo
    )
    if not maintenance_issue:
        return False, [
            "Maintenance issue 'Weekly maintenance cleanup and refactor' not found"
        ]

    issue_number = maintenance_issue["number"]
    print(f"   Found maintenance issue #{issue_number}")

    # Check labels
    expected_labels = ["maintenance", "priority-medium", "needs-review"]
    labels_ok, label_errors = _check_issue_labels(maintenance_issue, expected_labels)
    if not labels_ok:
        errors.extend(label_errors)
    else:
        print(f"   ✅ Labels verified: {expected_labels}")

    # Check NO milestone (maintenance issues shouldn't get v1.0.0)
    milestone_ok, milestone_errors = _check_issue_milestone(maintenance_issue, None)
    if not milestone_ok:
        errors.extend(milestone_errors)
    else:
        print("   ✅ No milestone assigned (correct for maintenance issue)")

    # Check comment
    comment_ok, comment_errors = _check_issue_comments(
        issue_number, "Maintenance Guidelines", headers, owner, repo
    )
    if not comment_ok:
        errors.extend(comment_errors)
    else:
        print("   ✅ Maintenance Guidelines comment found")

    return len(errors) == 0, errors


def verify() -> tuple[bool, str]:
    """
    Verify that the issue management workflow automation is working correctly.
    """
    # Load environment variables
    load_dotenv(".mcp_env")

    github_token = os.environ.get("MCP_GITHUB_TOKEN")
    if not github_token:
        print("Error: MCP_GITHUB_TOKEN environment variable not set", file=sys.stderr)
        return False, "MCP_GITHUB_TOKEN environment variable not set"

    # Get GitHub organization
    github_org = os.environ.get("GITHUB_EVAL_ORG")
    if not github_org:
        print("Error: GITHUB_EVAL_ORG environment variable not set", file=sys.stderr)
        return False, "GITHUB_EVAL_ORG environment variable not set"

    # Repository configuration
    owner = github_org
    repo = "mcpmark-cicd"

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    print("🔍 Starting Issue Management Workflow Verification")
    print("=" * 60)

    # Wait for workflows to complete
    workflows_completed = _wait_for_workflow_completion(headers, owner, repo)
    if not workflows_completed:
        print(
            "⚠️ Warning: Workflows may still be running. Continuing with verification..."
        )

    # Verify each test issue
    all_passed = True

    # 1. Verify bug issue
    bug_ok, bug_errors = _verify_bug_issue(headers, owner, repo)
    if not bug_ok:
        all_passed = False
        print("❌ Bug Issue Verification Failed:")
        for error in bug_errors:
            print(f"   - {error}")
    else:
        print("✅ Bug Issue Verification Passed")

    # 2. Verify epic issue
    epic_ok, epic_errors = _verify_epic_issue(headers, owner, repo)
    if not epic_ok:
        all_passed = False
        print("❌ Epic Issue Verification Failed:")
        for error in epic_errors:
            print(f"   - {error}")
    else:
        print("✅ Epic Issue Verification Passed")

    # 3. Verify maintenance issue
    maintenance_ok, maintenance_errors = _verify_maintenance_issue(headers, owner, repo)
    if not maintenance_ok:
        all_passed = False
        print("❌ Maintenance Issue Verification Failed:")
        for error in maintenance_errors:
            print(f"   - {error}")
    else:
        print("✅ Maintenance Issue Verification Passed")

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 All Issue Management Workflow verifications PASSED!")
        print("\n📋 Summary:")
        print("   ✅ Bug issue: labels (including first-time-contributor), "
              "milestone, and auto-response verified")
        print("   ✅ Epic issue: labels, milestone, 4 sub-issues with "
              "checklist, and correct issue references verified")
        print("   ✅ Maintenance issue: labels, no milestone, and "
              "auto-response verified")
        print("\n🤖 The GitHub Actions workflow automation is working correctly!")
        return True, ""
    print("❌ Issue Management Workflow verification FAILED!")
    print("   Some issues did not meet the expected automation requirements.")
    return False, "Issue Management Workflow verification failed"


def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
