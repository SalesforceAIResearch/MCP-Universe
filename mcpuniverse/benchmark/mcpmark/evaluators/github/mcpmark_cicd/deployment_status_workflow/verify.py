"""Verification module for deployment status workflow in mcpmark-cicd repository."""
# pylint: disable=R0912,R1702,astroid-error,duplicate-code,import-error
import datetime
import sys
import os
import time
from typing import Dict, List, Optional, Tuple
import re
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
    print("⏳ Waiting for deployment status workflows to complete...")

    start_time = time.time()
    no_workflow_check_count = 0

    while time.time() - start_time < max_wait:
        try:
            # Check workflow runs for deployment-status.yml
            success, response = _get_github_api(
                "actions/workflows/deployment-status.yml/runs?per_page=10",
                headers,
                owner,
                repo,
            )

            if success and response:
                runs = response.get("workflow_runs", [])
                if len(runs) > 0:
                    # Check status of recent runs
                    running_count = 0
                    completed_count = 0
                    failed_count = 0

                    for run in runs[:3]:  # Check recent runs
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

                    # Wait until NO workflows are running
                    if running_count == 0:
                        if failed_count > 0:
                            msg = (f"⚠️ Warning: {failed_count} workflow runs "
                                   f"failed, but continuing verification...")
                            print(msg)

                        print(
                            f"✅ All workflows completed. Found {completed_count} completed runs."
                        )
                        # Additional wait to ensure all processing is done
                        print(
                            "⏳ Additional wait for deployment processing to complete..."
                        )
                        time.sleep(5)
                        return True
                else:
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

            print(f"⏳ Still waiting... ({int(time.time() - start_time)}s elapsed)")
            time.sleep(5)

        except (requests.RequestException, IOError, OSError, ValueError, KeyError, TypeError) as e:
            print(f"⚠️ Error checking workflow status: {e}")
            time.sleep(5)

    print(f"⚠️ Workflow completion wait timed out after {max_wait}s")
    return False


def _verify_workflow_runs(
    headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, List[str], Optional[Dict]]:
    """Verify that the deployment status workflow runs have the correct jobs."""
    print("\n⚙️ Verifying deployment status workflow runs...")
    errors = []

    # Get the most recent workflow run
    success, response = _get_github_api(
        "actions/workflows/deployment-status.yml/runs?per_page=5",
        headers,
        owner,
        repo,
    )

    if not success or not response:
        return False, ["Failed to fetch workflow runs"], None

    runs = response.get("workflow_runs", [])
    if not runs:
        return False, ["No workflow runs found for deployment-status.yml"], None

    # Find the most recent successful run
    latest_successful_run = None
    for run in runs:
        if run.get("conclusion") == "success":
            latest_successful_run = run
            break

    if not latest_successful_run:
        return False, ["No successful workflow runs found"], None

    run_id = latest_successful_run["id"]
    print(f"   Found successful workflow run #{run_id}")

    # Get jobs for this run
    success, jobs_response = _get_github_api(
        f"actions/runs/{run_id}/jobs", headers, owner, repo
    )

    if not success:
        return False, ["Failed to fetch workflow jobs"], None

    jobs = jobs_response.get("jobs", [])
    expected_jobs = ["pre-deployment", "rollback-preparation", "post-deployment"]

    found_jobs = [job["name"] for job in jobs]
    missing_jobs = [job for job in expected_jobs if job not in found_jobs]

    if missing_jobs:
        errors.append(f"Missing jobs: {missing_jobs}. Found: {found_jobs}")
    else:
        print(f"   ✅ All 3 required jobs found: {found_jobs}")

    # Verify all jobs succeeded
    failed_jobs = [job["name"] for job in jobs if job["conclusion"] != "success"]
    if failed_jobs:
        errors.append(f"Failed jobs: {failed_jobs}")
    else:
        print("   ✅ All jobs completed successfully")

    # Verify sequential execution (each job should start after the previous one)
    if len(jobs) >= 3:
        job_times = {}
        for job in jobs:
            if job["name"] in expected_jobs and job["started_at"]:
                job_times[job["name"]] = job["started_at"]

        if len(job_times) >= 3:
            # Check that jobs ran in correct sequence

            times = {
                name: datetime.datetime.fromisoformat(time.replace("Z", "+00:00"))
                for name, time in job_times.items()
            }

            # pre-deployment should start first
            # rollback-preparation should start after pre-deployment
            # post-deployment should start after rollback-preparation
            if all(job in times for job in expected_jobs):
                if (
                    times["rollback-preparation"] <= times["pre-deployment"]
                    or times["post-deployment"] <= times["rollback-preparation"]
                ):
                    errors.append("Jobs did not run in correct sequential order")
                else:
                    print("   ✅ Jobs ran in correct sequential order")
            else:
                errors.append(
                    "Not enough job timing data to verify sequential execution"
                )

    return len(errors) == 0, errors, latest_successful_run


def _verify_deployment_issue(
    run_data: Dict, headers: Dict[str, str], owner: str, repo: str
) -> Tuple[bool, List[str]]:
    """Verify that a deployment tracking issue was created and closed properly."""
    print("\n📋 Verifying deployment tracking issue...")
    errors = []

    # Extract commit SHA from the workflow run
    head_sha = run_data.get("head_sha")
    if not head_sha:
        return False, ["Could not determine head SHA from workflow run"]

    short_sha = head_sha[:7]
    expected_title = f"Deployment Tracking - {short_sha}"

    # Search for the deployment tracking issue
    success, issues = _search_github_issues(
        f'repo:{owner}/{repo} "{expected_title}" is:issue', headers
    )

    if not success:
        return False, ["Failed to search for deployment tracking issue"]

    # Find the exact issue
    deployment_issue = None
    for issue in issues:
        if issue.get("title") == expected_title:
            deployment_issue = issue
            break

    if not deployment_issue:
        return False, [f"Deployment tracking issue '{expected_title}' not found"]

    issue_number = deployment_issue["number"]
    print(f"   Found deployment tracking issue #{issue_number}: {expected_title}")

    # Check that issue is closed
    if deployment_issue.get("state") != "closed":
        errors.append(
            f"Deployment issue #{issue_number} is not closed "
            f"(state: {deployment_issue.get('state')})"
        )
    else:
        print(f"   ✅ Deployment issue #{issue_number} is closed")

    # Check required labels
    expected_labels = ["deployment", "completed"]
    actual_labels = [label["name"] for label in deployment_issue.get("labels", [])]
    missing_labels = [label for label in expected_labels if label not in actual_labels]

    if missing_labels:
        errors.append(
            f"Missing labels on deployment issue: {missing_labels}. Found: {actual_labels}"
        )
    else:
        print(f"   ✅ Required labels found: {expected_labels}")

    # Get issue comments to verify GitHub Actions bot comments
    success, comments = _get_github_api(
        f"issues/{issue_number}/comments", headers, owner, repo
    )

    if not success:
        errors.append("Failed to get deployment issue comments")
        return len(errors) == 0, errors

    # Filter for GitHub Actions bot comments only
    bot_comments = [
        comment
        for comment in comments
        if comment.get("user", {}).get("login") == "github-actions[bot]"
    ]

    if not bot_comments:
        errors.append("No comments found from GitHub Actions bot")
        return len(errors) == 0, errors

    print(f"   Found {len(bot_comments)} comment(s) from GitHub Actions bot")

    # Get all bot comment bodies
    bot_comment_bodies = [comment.get("body", "") for comment in bot_comments]
    all_bot_comments = " ".join(bot_comment_bodies)

    # Check for required GitHub Actions bot comment indicators
    required_comment_indicators = [
        "Pre-deployment checks completed",
        "🔄 Rollback Plan Ready",
        "Deployment Completed Successfully",
    ]

    for indicator in required_comment_indicators:
        if indicator not in all_bot_comments:
            errors.append(
                f"Missing required GitHub Actions bot comment indicator: '{indicator}'"
            )
        else:
            print(f"   ✅ Found GitHub Actions bot comment indicator: '{indicator}'")

    # Find and verify the rollback plan comment from GitHub Actions bot
    rollback_comment = None
    for comment in bot_comments:
        if "🔄 Rollback Plan Ready" in comment.get("body", ""):
            rollback_comment = comment.get("body", "")
            break

    if rollback_comment:
        print("   ✅ Found rollback plan comment from GitHub Actions bot")

        # Check for required rollback plan elements
        required_elements = [
            "**Previous Commit**:",
            "**Current Commit**:",
            "**Package Version**:",
            "✅ Executable rollback script created",
            "✅ Configuration backups saved",
            "✅ Dependency verification script prepared",
            "✅ Comprehensive rollback documentation generated",
            "✅ Compressed rollback package created",
            "**SHA256**:",
            "**Artifact**:",
            "Quick Rollback Commands",
        ]

        for element in required_elements:
            if element not in rollback_comment:
                errors.append(f"Missing element in rollback plan: '{element}'")
            else:
                print(f"   ✅ Found rollback plan element: '{element}'")

        # Verify commit SHAs in rollback comment
        if f"**Current Commit**: {head_sha}" in rollback_comment:
            print(f"   ✅ Current commit SHA verified: {head_sha}")
        else:
            errors.append(
                f"Current commit SHA {head_sha} not found in rollback comment"
            )

        # Extract and verify previous commit SHA
        if "**Previous Commit**:" in rollback_comment:

            prev_sha_match = re.search(
                r"\*\*Previous Commit\*\*:\s*([a-f0-9]{40})", rollback_comment
            )
            if prev_sha_match:
                prev_sha = prev_sha_match.group(1)
                print(f"   ✅ Previous commit SHA found: {prev_sha}")

                # Verify it's a valid 40-character SHA
                if len(prev_sha) != 40:
                    errors.append(
                        f"Previous commit SHA has invalid length: {len(prev_sha)}"
                    )
            else:
                errors.append(
                    "Previous commit SHA format not found in rollback comment"
                )
        else:
            errors.append("Previous commit SHA not found in rollback comment")

        # Verify SHA256 checksum is present
        sha256_match = re.search(r"\*\*SHA256\*\*:\s*([a-f0-9]{64})", rollback_comment)
        if sha256_match:
            sha256_value = sha256_match.group(1)
            print(f"   ✅ SHA256 checksum found: {sha256_value[:16]}...")
        else:
            errors.append(
                "SHA256 checksum not found or invalid format in rollback comment"
            )

    else:
        errors.append("Rollback plan comment not found from GitHub Actions bot")

    return len(errors) == 0, errors


def verify() -> tuple[bool, str]:
    """
    Verify that the deployment status workflow automation is working correctly.
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

    print("🔍 Starting Deployment Status Workflow Verification")
    print("=" * 60)

    # Wait for workflows to complete
    workflows_completed = _wait_for_workflow_completion(headers, owner, repo)
    if not workflows_completed:
        print(
            "⚠️ Warning: Workflows may still be running. Continuing with verification..."
        )

    # Verify workflow runs and jobs
    all_passed = True

    # 1. Verify workflow runs have correct jobs
    runs_ok, runs_errors, run_data = _verify_workflow_runs(headers, owner, repo)
    if not runs_ok:
        all_passed = False
        print("❌ Workflow Runs Verification Failed:")
        for error in runs_errors:
            print(f"   - {error}")
    else:
        print("✅ Workflow Runs Verification Passed")

        # 2. Verify deployment issue if workflow runs passed
        if run_data:
            issue_ok, issue_errors = _verify_deployment_issue(
                run_data, headers, owner, repo
            )
            if not issue_ok:
                all_passed = False
                print("❌ Deployment Issue Verification Failed:")
                for error in issue_errors:
                    print(f"   - {error}")
            else:
                print("✅ Deployment Issue Verification Passed")

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 All Deployment Status Workflow verifications PASSED!")
        print("\n📋 Summary:")
        print(
            "   ✅ Workflow runs with correct 3 sequential jobs: "
            "pre-deployment, rollback-preparation, post-deployment"
        )
        print("   ✅ Deployment tracking issue created and closed with proper labels")
        print("   ✅ Issue contains rollback plan with all required elements")
        print("   ✅ Previous and current commit SHAs are correctly tracked")
        print("   ✅ All workflow automation comments are present")
        print(
            "\n🤖 The GitHub Actions deployment status workflow is working correctly!"
        )
        return True, ""
    print("❌ Deployment Status Workflow verification FAILED!")
    print("   Some components did not meet the expected automation requirements.")
    return False, "Deployment Status Workflow verification failed"


def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
