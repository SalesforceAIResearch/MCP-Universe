"""Verification module for linting CI workflow in mcpmark-cicd repository."""
# pylint: disable=R0911,R0912,R0914,R0915,astroid-error,duplicate-code,import-error
import sys
import os
import time
import json
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
    branch_name: str, headers: Dict[str, str], org: str, repo: str = "mcpmark-cicd"
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
    keyword: str, headers: Dict[str, str], org: str, repo: str = "mcpmark-cicd"
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


def _get_workflow_runs_for_pr(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "mcpmark-cicd"
) -> List[Dict]:
    """Get workflow runs for a specific PR."""
    success, runs = _get_github_api(
        "actions/runs?event=pull_request&per_page=100", headers, org, repo
    )
    if not success or not runs:
        return []

    pr_runs = []
    for run in runs.get("workflow_runs", []):
        # Check if this run is associated with our PR
        for pr in run.get("pull_requests", []):
            if pr.get("number") == pr_number:
                pr_runs.append(run)
                break

    return pr_runs


def _get_pr_commits(
    pr_number: int, headers: Dict[str, str], org: str, repo: str = "mcpmark-cicd"
) -> List[Dict]:
    """Get commits for a specific PR."""
    success, commits = _get_github_api(f"pulls/{pr_number}/commits", headers, org, repo)
    if not success or not commits:
        return []
    return commits


def _get_workflow_runs_for_commit(
    commit_sha: str, headers: Dict[str, str], org: str, repo: str = "mcpmark-cicd"
) -> List[Dict]:
    """Get workflow runs for a specific commit."""
    success, runs = _get_github_api(
        f"actions/runs?head_sha={commit_sha}&per_page=100", headers, org, repo
    )
    if not success or not runs:
        return []
    return runs.get("workflow_runs", [])


def verify() -> tuple[bool, str]:
    """
    Programmatically verify that the ESLint CI workflow setup
    meets the requirements described in description.md.
    """
    # Configuration constants
    branch_name = "ci/add-eslint-workflow"
    pr_keyword = "eslint workflow"

    # Expected files and their content checks
    eslint_config_path = ".eslintrc.json"
    workflow_path = ".github/workflows/lint.yml"
    example_file_path = "src/example.js"

    # Expected workflow content keywords
    workflow_keywords = [
        "Code Linting",
        "ubuntu-latest",
        "actions/setup-node",
        "npm ci",
        "eslint",
        "src/",
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
    print("Verifying ESLint CI workflow setup...")

    # 1. Check that branch exists
    print("1. Verifying CI branch exists...")
    if not _check_branch_exists(branch_name, headers, github_org):
        print(f"Error: Branch '{branch_name}' not found", file=sys.stderr)
        return False, f"Branch '{branch_name}' not found"
    print("✓ CI branch created")

    # 2. Check ESLint configuration file
    print("2. Verifying .eslintrc.json...")
    eslint_content = _get_file_content(
        eslint_config_path, headers, github_org, "mcpmark-cicd", branch_name
    )
    if not eslint_content:
        print("Error: .eslintrc.json not found", file=sys.stderr)
        return False, ".eslintrc.json not found"

    # Validate ESLint config is valid JSON and contains required rules
    try:
        eslint_config = json.loads(eslint_content)
        rules = eslint_config.get("rules", {})

        required_rules = ["no-unused-vars", "semi", "quotes"]
        missing_rules = [rule for rule in required_rules if rule not in rules]
        if missing_rules:
            print(
                f"Error: .eslintrc.json missing rules: {missing_rules}", file=sys.stderr
            )
            return False, f".eslintrc.json missing rules: {missing_rules}"

    except json.JSONDecodeError:
        print("Error: .eslintrc.json is not valid JSON", file=sys.stderr)
        return False, ".eslintrc.json is not valid JSON"

    print("✓ ESLint configuration created with proper rules")

    # 3. Check GitHub Actions workflow file
    print("3. Verifying .github/workflows/lint.yml...")
    workflow_content = _get_file_content(
        workflow_path, headers, github_org, "mcpmark-cicd", branch_name
    )
    if not workflow_content:
        print("Error: .github/workflows/lint.yml not found", file=sys.stderr)
        return False, ".github/workflows/lint.yml not found"

    # Check workflow contains required keywords
    missing_keywords = [kw for kw in workflow_keywords if kw not in workflow_content]
    if missing_keywords:
        print(f"Error: Workflow missing keywords: {missing_keywords}", file=sys.stderr)
        return False, f"Workflow missing keywords: {missing_keywords}"

    # Check trigger configuration
    if "pull_request" not in workflow_content or "push" not in workflow_content:
        print("Error: Workflow missing proper triggers", file=sys.stderr)
        return False, "Workflow missing proper triggers"

    print("✓ GitHub Actions workflow created with proper configuration")

    # 4. Check example file with linting errors initially exists
    print("4. Verifying src/example.js...")
    example_content = _get_file_content(
        example_file_path, headers, github_org, "mcpmark-cicd", branch_name
    )
    if not example_content:
        print("Error: src/example.js not found", file=sys.stderr)
        return False, "src/example.js not found"

    print("✓ Example file created")

    # 5. Find and verify the linting PR
    print("5. Verifying linting pull request...")
    lint_pr = _find_pr_by_title_keyword(pr_keyword, headers, github_org)
    if not lint_pr:
        # Try alternative keywords
        lint_pr = _find_pr_by_title_keyword("eslint", headers, github_org)

    if not lint_pr:
        print("Error: Linting PR not found", file=sys.stderr)
        return False, "Linting PR not found"

    pr_body = lint_pr.get("body", "")
    pr_number = lint_pr.get("number")

    # Check PR body sections
    required_sections = ["## Summary", "## Changes", "## Testing"]
    missing_sections = [
        section for section in required_sections if section not in pr_body
    ]
    if missing_sections:
        print(
            f"Error: Linting PR missing sections: {missing_sections}", file=sys.stderr
        )
        return False, f"Linting PR missing sections: {missing_sections}"

    print("✓ Linting PR created with proper structure")

    # 6. Check workflow runs and status changes
    print("6. Verifying workflow execution and status...")

    # First get the commits for this PR
    commits = _get_pr_commits(pr_number, headers, github_org)
    if len(commits) != 2:
        print(
            f"Error: Expected exactly 2 commits, found {len(commits)}", file=sys.stderr
        )
        return False, f"Expected exactly 2 commits, found {len(commits)}"

    print("✓ Found exactly 2 commits as expected")

    # Sort commits chronologically (oldest first)
    commits.sort(key=lambda x: x.get("commit", {}).get("author", {}).get("date", ""))

    first_commit_sha = commits[0].get("sha")
    second_commit_sha = commits[1].get("sha")

    print(f"First commit (should fail): {first_commit_sha[:7]}")
    print(f"Second commit (should pass): {second_commit_sha[:7]}")

    # Wait for workflows on both commits to complete
    print("Waiting for workflow completion on first commit...")
    first_commit_runs = []
    second_commit_runs = []

    start_time = time.time()
    timeout = 90
    no_workflow_check_count = 0

    while time.time() - start_time < timeout:
        first_commit_runs = _get_workflow_runs_for_commit(
            first_commit_sha, headers, github_org
        )
        second_commit_runs = _get_workflow_runs_for_commit(
            second_commit_sha, headers, github_org
        )

        # Check if any workflows exist
        if not first_commit_runs and not second_commit_runs:
            no_workflow_check_count += 1
            if no_workflow_check_count == 1:
                print(
                    "No workflow runs found yet, waiting 5 seconds and checking once more..."
                )
                time.sleep(5)
                continue
            if no_workflow_check_count >= 2:
                print("⚠️ No workflow runs detected after 2 checks. "
                      "Workflows may not have been triggered.")
                print("   Continuing with verification...")
                break

        # Check if workflows are completed
        first_completed = any(
            run.get("status") == "completed" for run in first_commit_runs
        )
        second_completed = any(
            run.get("status") == "completed" for run in second_commit_runs
        )

        if first_completed and second_completed:
            break

        print("Waiting for workflows to complete...")
        time.sleep(10)

    # Verify first commit workflow failed
    first_commit_status = None
    for run in first_commit_runs:
        if run.get("status") == "completed":
            conclusion = run.get("conclusion")
            if conclusion in ["failure", "cancelled"]:
                first_commit_status = "failed"
                print("✓ First commit workflow failed as expected")
                break
            if conclusion == "success":
                first_commit_status = "passed"
                break

    if first_commit_status != "failed":
        print(
            "Error: First commit workflow should have failed due to linting errors",
            file=sys.stderr,
        )
        return False, "First commit workflow should have failed due to linting errors"

    # Verify second commit workflow succeeded
    second_commit_status = None
    for run in second_commit_runs:
        if run.get("status") == "completed":
            conclusion = run.get("conclusion")
            if conclusion == "success":
                second_commit_status = "passed"
                print("✓ Second commit workflow passed as expected")
                break
            if conclusion in ["failure", "cancelled"]:
                second_commit_status = "failed"
                break

    if second_commit_status != "passed":
        print(
            "Error: Second commit workflow should have passed after fixing linting errors",
            file=sys.stderr,
        )
        return False, "Second commit workflow should have passed after fixing linting errors"

    print(
        "✓ Workflow status sequence verified: first commit failed → second commit passed"
    )

    # 7. Verify the final state shows clean code
    print("7. Verifying final file state...")
    final_example_content = _get_file_content(
        example_file_path, headers, github_org, "mcpmark-cicd", branch_name
    )

    if final_example_content:
        # Check that obvious linting errors are fixed
        if (
            "unusedVariable" in final_example_content
            or 'console.log("Hello World")' in final_example_content
        ):
            print(
                "Warning: Example file may still contain linting errors",
                file=sys.stderr,
            )
        else:
            print("✓ Linting errors appear to be fixed")

    print("\n✅ All verification checks passed!")
    print("ESLint CI workflow setup completed successfully:")
    print(f"  - Linting PR #{pr_number}")
    print(f"  - Branch: {branch_name}")
    print(
        "  - Files created: .eslintrc.json, .github/workflows/lint.yml, src/example.js"
    )
    print("  - Workflow configured for pull_request and push triggers")
    print(
        f"  - Total workflow runs found: {len(first_commit_runs) + len(second_commit_runs)}"
    )
    first_count = len(first_commit_runs)
    second_count = len(second_commit_runs)
    print(f"  - First commit runs: {first_count}, "
          f"Second commit runs: {second_count}")

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
