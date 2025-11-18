"""
GitHub State Manager for MCPMark
=================================

This module handles GitHub repository state management for consistent task evaluation.
Manages test repositories, branches, and cleanup after evaluation.
"""
# pylint: disable=import-error
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urlparse

import requests

from src.base.state_manager import BaseStateManager, InitialStateInfo
from src.base.task_manager import BaseTask
from src.logger import get_logger
from src.mcp_services.github.token_pool import GitHubTokenPool

logger = get_logger(__name__)


class GitHubStateManager(BaseStateManager):  # pylint: disable=too-many-instance-attributes
    """
    Manages GitHub repository state for task evaluation.
    """

    def __init__(
        self,
        github_token: Union[str, List[str]],
        # Name of the evaluation organisation / user where temporary test repositories are created
        eval_org: str = "mcpmark-eval",
        # Local directory that stores *exported* repository templates (produced by repo_exporter.py)
        templates_root: str = "./github_state",
    ):
        """
        Initialize GitHub state manager.

        Args:
            github_token: GitHub Personal Access Token(s). Can be a single token
                string or a list of tokens for round-robin usage.
            eval_org: Organisation / user used to host **ephemeral evaluation
                repositories**.
        """
        super().__init__(service_name="github")

        # Track repos created via template import so we can delete them afterwards
        self._repos_to_cleanup: list[tuple[str, str]] = []  # (owner, repo_name)
        # Cache for authenticated user (lazy initialization)
        self._auth_user: Optional[str] = None

        # Initialize token pool
        if isinstance(github_token, str):
            # Single token - create pool with one token
            self.token_pool = GitHubTokenPool([github_token])
            self.github_token = github_token  # Keep for backward compatibility
        else:
            # Multiple tokens - use token pool
            self.token_pool = GitHubTokenPool(github_token)
            self.github_token = (
                self.token_pool.get_current_token()
            )  # For backward compatibility

        # Store evaluation context (consistent naming)
        self.eval_org = eval_org  # evaluation organisation / user

        # Local path that contains exported repository templates
        self.templates_root = Path(templates_root).expanduser().resolve()

        # Set up HTTP session for GitHub API
        self.session = requests.Session()
        # Note: We'll update the Authorization header before each request
        self.session.headers.update(
            {
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "MCPMark/1.0",
            }
        )

        # Validate GitHub configuration during initialization
        try:
            # Set initial token for validation
            self._update_session_token()

            response = self.session.get("https://api.github.com/user")
            if response.status_code != 200:
                raise ValueError(
                    f"Invalid GitHub token: {response.status_code} {response.text}"
                )

            user_info = response.json()
            logger.info("GitHub authenticated as: %s", user_info['login'])
            logger.info(
                "Using token pool with %d token(s)",
                self.token_pool.pool_size
            )

            # Check if evaluation organisation exists (optional)
            if self.eval_org:
                org_response = self.session.get(
                    f"https://api.github.com/orgs/{self.eval_org}"
                )
                if org_response.status_code == 200:
                    logger.info(
                        "Using evaluation organisation: %s",
                        self.eval_org
                    )
                else:
                    logger.warning(
                        "Evaluation organisation %s not accessible, "
                        "using user account",
                        self.eval_org
                    )
                    # Fall back to user account
                    self.eval_org = user_info["login"]

            logger.info("GitHub state manager initialized successfully")

        except Exception as exc:
            raise RuntimeError(f"GitHub initialization failed: {exc}") from exc

        # Initial state mapping - categories to initial state repositories
        self.initial_state_mapping = {
            "build_your_own_x": "codecrafters-io-build-your-own-x",
            "missing-semester": "missing-semester-missing-semester",
            "mcpmark-cicd": "zjwu0522-mcpmark-cicd",
            "harmony": "openai-harmony",
            "claude-code": "anthropics-claude-code",
            "easyr1": "hiyouga-EasyR1",
        }

        # CDN URL mapping for downloading GitHub templates
        self.github_template_url_mapping = {
            "codecrafters-io-build-your-own-x": (
                "https://storage.mcpmark.ai/github/"
                "codecrafters-io-build-your-own-x.zip"
            ),
            "missing-semester-missing-semester": (
                "https://storage.mcpmark.ai/github/"
                "missing-semester-missing-semester.zip"
            ),
            "zjwu0522-mcpmark-cicd": (
                "https://storage.mcpmark.ai/github/"
                "zjwu0522-mcpmark-cicd.zip"
            ),
            "openai-harmony": (
                "https://storage.mcpmark.ai/github/openai-harmony.zip"
            ),
            "anthropics-claude-code": (
                "https://storage.mcpmark.ai/github/"
                "anthropics-claude-code.zip"
            ),
            "hiyouga-EasyR1": (
                "https://storage.mcpmark.ai/github/hiyouga-EasyR1.zip"
            ),
        }

    # =========================================================================
    # Core Template Methods (Required by BaseStateManager)
    # =========================================================================

    # ---------------------------------------------------------------------
    # Internal helper – template importer (replicates repo_importer logic)
    # ---------------------------------------------------------------------

    def _import_template_repo(  # pylint: disable=too-many-locals, too-many-statements
        self, template_dir: Path, owner: str, private: bool = True
    ) -> str:
        """Import repository from local template directory to GitHub (simplified)."""

        # ------------------------------------------------------------------
        # Helper functions (stripped-down versions of repo_importer utilities)
        # ------------------------------------------------------------------

        def _list_refs(repo_dir: str) -> list[str]:
            result = subprocess.run(
                ["git", "-C", repo_dir, "for-each-ref", "--format=%(refname)"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().splitlines()

        def _push_repo(
            repo_path: Path, repo_owner: str, repo_name: str, required_refs: list[str]
        ):
            """Push repo to GitHub: try mirror, else per-ref."""
            token = self.github_token
            dst_url = f"https://x-access-token:{token}@github.com/{repo_owner}/{repo_name}.git"

            try:
                subprocess.run(
                    ["git", "-C", str(repo_path), "push", "--mirror", dst_url],
                    check=True,
                    capture_output=True,
                )
                return
            except subprocess.CalledProcessError as err:
                logger.warning(
                    "| [push] Mirror push failed – falling back: %s",
                    err.stderr.decode(errors="ignore"),
                )

            refs = required_refs or _list_refs(str(repo_path))
            for ref in refs:
                for attempt in range(3):
                    try:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(repo_path),
                                "push",
                                dst_url,
                                f"{ref}:{ref}",
                            ],
                            check=True,
                            capture_output=True,
                        )
                        break
                    except subprocess.CalledProcessError as ref_err:
                        if attempt == 2:
                            raise RuntimeError(
                                f"Failed to push ref {ref}: {ref_err.stderr}"
                            ) from ref_err
                        time.sleep(2 * (attempt + 1))

        # ------------------------------------------------------------------
        # Phase 0 – read template metadata
        # ------------------------------------------------------------------
        meta = json.loads((template_dir / "meta.json").read_text())
        repo_name: str = meta["repo"]
        pr_head_refs = meta.get("pr_head_refs", [])
        default_branch = meta.get("default_branch", "main")

        pulls_data = json.loads((template_dir / "pulls.json").read_text())
        fork_branches = [
            pr["local_branch"]
            for pr in pulls_data
            if pr.get("is_from_fork") and "local_branch" in pr
        ]
        needed_refs = (
            [f"refs/heads/{default_branch}"]
            + [f"refs/heads/{h}" for h in pr_head_refs]
            + [f"refs/heads/{b}" for b in fork_branches]
        )

        # ------------------------------------------------------------------
        # Phase 1 – create empty repo under owner
        # ------------------------------------------------------------------
        create_payload = {
            "name": repo_name,
            "description": f"Restored template repo {repo_name}",
            "private": private,
            "auto_init": False,
            "has_issues": True,
            "has_projects": True,
            "has_wiki": False,
            "default_branch": default_branch,  # Set the correct default branch
        }

        auth_user = self._get_authenticated_user()
        create_url = (
            "https://api.github.com/user/repos"
            if owner == auth_user
            else f"https://api.github.com/orgs/{owner}/repos"
        )

        resp = self._request_with_retry("POST", create_url, json=create_payload)
        if resp.status_code == 422 and "name already exists" in resp.text:
            # Attempt to delete and recreate
            self._delete_repository(owner, repo_name)
            resp = self._request_with_retry("POST", create_url, json=create_payload)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create repo: {resp.status_code} {resp.text}")

        html_url = resp.json()["html_url"]
        logger.info("| [import] Target repository created: %s", html_url)

        # Immediately disable GitHub Actions for ALL repositories to prevent any accidental triggers
        # We'll re-enable it later only for mcpmark-cicd
        # logger.info(
        #     "| [import] Disabling GitHub Actions immediately after repo creation..."
        # )
        # self._disable_github_actions(owner, repo_name)

        # ------------------------------------------------------------------
        # Phase 2 – push git history
        # ------------------------------------------------------------------
        repo_path = template_dir / "repo"

        logger.info("| [import] Pushing git history …")
        _push_repo(repo_path, owner, repo_name, needed_refs)

        # Remove .github directory after pushing with a new commit

        github_dir = repo_path / ".github"
        if github_dir.exists():
            logger.info("| [import] Removing .github directory after push …")
            shutil.rmtree(github_dir)
            # Commit the deletion
            subprocess.run(
                ["git", "-C", str(repo_path), "add", "-A"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "commit",
                    "-m",
                    "Remove .github directory",
                ],
                check=False,  # Git commit may fail if nothing to commit
                capture_output=True,
            )
            # Push the new commit
            token = self.github_token
            dst_url = (
                f"https://x-access-token:{token}@github.com/{owner}/{repo_name}.git"
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "push", dst_url],
                check=True,
                capture_output=True,
            )

        # ------------------------------------------------------------------
        # Phase 3 – recreate issues & PRs
        # ------------------------------------------------------------------

        def _create_comment(issue_number: int, body: str):
            self._request_with_retry(
                "POST",
                (
                    f"https://api.github.com/repos/{owner}/{repo_name}/"
                    f"issues/{issue_number}/comments"
                ),
                json={"body": body},
            )

        def _create_issue(item: dict) -> Optional[int]:
            data = {
                "title": item["title"],
                "body": item.get("body", ""),
                "labels": item.get("labels", []),
            }
            r = self._request_with_retry(
                "POST",
                f"https://api.github.com/repos/{owner}/{repo_name}/issues",
                json=data,
            )
            if r.status_code not in (200, 201):
                return None
            new_no = r.json()["number"]
            if item.get("state") == "closed":
                self._request_with_retry(
                    "PATCH",
                    f"https://api.github.com/repos/{owner}/{repo_name}/issues/{new_no}",
                    json={"state": "closed"},
                )
            return new_no

        def _create_pull(pr_itm: dict) -> Optional[int]:
            body = pr_itm.get("body", "")
            if pr_itm.get("is_from_fork", False):
                fork_owner = pr_itm.get('fork_owner')
                fork_repo = pr_itm.get('fork_repo')
                fork_branch = pr_itm['head']
                fork_note = (
                    f"\n\n---\n_This PR was originally from a fork: "
                    f"**{fork_owner}/{fork_repo}** (branch: `{fork_branch}`)_"
                )
                body = body + fork_note if body else fork_note[2:]
            payload = {
                "title": pr_itm["title"],
                "body": body,
                "head": pr_itm.get("local_branch", pr_itm["head"]),
                "base": pr_itm["base"],
            }
            r = self._request_with_retry(
                "POST",
                f"https://api.github.com/repos/{owner}/{repo_name}/pulls",
                json=payload,
            )
            if r.status_code not in (200, 201):
                return None
            return r.json()["number"]

        # Issues
        issues_data = json.loads((template_dir / "issues.json").read_text())
        created_issues = 0
        logger.info("| [phase] Re-creating issues …")
        for itm in issues_data:
            new_no = _create_issue(itm)
            if new_no:
                created_issues += 1
                for c in itm.get("comments", []):
                    _create_comment(
                        new_no, f"*Original author: @{c['user']}*\n\n{c['body']}"
                    )
        logger.info(
            "| [phase] Created %d out of %d issues", created_issues, len(issues_data)
        )

        # Pull requests
        logger.info("| [phase] Re-creating pull requests …")
        created_prs = 0
        skipped_prs = 0
        for pr in pulls_data:
            new_pr_no = _create_pull(pr)
            if new_pr_no:
                created_prs += 1
                for c in pr.get("comments", []):
                    _create_comment(
                        new_pr_no, f"*Original author: @{c['user']}*\n\n{c['body']}"
                    )
                for rc in pr.get("review_comments", []):
                    _create_comment(
                        new_pr_no,
                        f"*Original author: @{rc['user']}* (review)\n\n{rc['body']}",
                    )
            else:
                skipped_prs += 1
        logger.info(
            "| [phase] Created %d PRs, skipped %d PRs", created_prs, skipped_prs
        )

        # Re-enable GitHub Actions ONLY for mcpmark-cicd repository
        # All other repos remain disabled (as set immediately after creation)
        if "mcpmark-cicd" in template_dir.name:
            logger.info("| [import] Re-enabling GitHub Actions for CI/CD repository…")
            self._enable_github_actions(owner, repo_name)

        # Disable notifications to prevent email spam
        logger.info("| [import] Disabling repository notifications …")
        self._disable_repository_notifications(owner, repo_name)

        logger.info("| [import] Repository import complete: %s", html_url)
        return html_url

    # ---------------------------------------------------------------------
    # Public – create initial state using local template import
    # ---------------------------------------------------------------------

    def _create_initial_state(self, task: "BaseTask") -> Optional[InitialStateInfo]:
        """
        Set up GitHub environment for a specific task.

        This may involve:
        1. Creating/forking test repositories
        2. Setting up branches
        3. Creating issues or PRs if needed
        """
        try:
            logger.info("| Setting up GitHub state for task: %s", task.name)

            template_name = self.select_initial_state_for_task(task.category_id)
            if template_name is None:
                raise RuntimeError(
                    f"No template configured for task category: {task.category_id}"
                )

            template_dir = (self.templates_root / template_name).resolve()
            if not template_dir.exists():
                logger.warning(
                    "| Template directory %s not found locally, attempting to download from CDN",
                    template_dir,
                )
                if not self._download_and_extract_github_template(template_name):
                    logger.error(
                        "| Failed to download template %s from CDN", template_name
                    )
                    return None
                logger.info("| Template %s downloaded successfully", template_name)

            logger.info("| Importing repository template from %s …", template_dir)
            owner = (
                self.eval_org
                if self.eval_org
                else self._get_authenticated_user()
            )

            if "mcpmark-cicd" in template_name:
                repo_url = self._import_template_repo(template_dir, owner, False)
            else:
                repo_url = self._import_template_repo(template_dir, owner, True)

            # Record for cleanup later
            repo_name = repo_url.rstrip("/").split("/")[-1]
            self._repos_to_cleanup.append((owner, repo_name))

            # Build InitialStateInfo
            return InitialStateInfo(
                state_id=f"{owner}/{repo_name}",
                state_url=repo_url,
                metadata={
                    "owner": owner,
                    "repo_name": repo_name,
                    "category": task.category_id,
                    "task_id": task.task_id,
                },
            )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("| GitHub setup failed for %s: %s", task.name, exc)
            return None

    # ---------------------------------------------------------------------
    # BaseStateManager required hooks
    # ---------------------------------------------------------------------

    def _store_initial_state_info(  # type: ignore[override]
        self, task, state_info: InitialStateInfo
    ) -> None:
        if hasattr(task, "repository_url"):
            task.repository_url = state_info.state_url

    def _cleanup_task_initial_state(  # type: ignore[override]
        self, task  # pylint: disable=unused-argument
    ) -> bool:
        """No-op – cleanup is handled by self.clean_up which deletes imported repos."""
        return True

    def _cleanup_single_resource(  # type: ignore[override]
        self, resource  # pylint: disable=unused-argument
    ) -> bool:
        """No-op – we don't use BaseStateManager's tracked_resources anymore."""
        return True

    # ---------------------------------------------------------------------
    def clean_up(self, task=None, **_kwargs) -> bool:  # pylint: disable=unused-argument
        """Delete repositories that were imported for tasks."""
        success = True
        for owner, repo_name in self._repos_to_cleanup:
            try:
                self._delete_repository(owner, repo_name)
                logger.info("| Deleted repository: %s/%s", owner, repo_name)
            except Exception as err:  # pylint: disable=broad-exception-caught
                logger.error(
                    "| Failed to delete repository %s/%s: %s",
                    owner,
                    repo_name,
                    err
                )
                success = False

        self._repos_to_cleanup.clear()
        return success

    # =========================================================================
    # Repository Creation and Setup Operations
    # =========================================================================

    def _delete_repository(self, owner: str, repo_name: str):
        """Delete a repository (use with caution)."""
        delete_url = f"https://api.github.com/repos/{owner}/{repo_name}"
        response = self.session.delete(delete_url)

        if response.status_code not in [200, 204]:
            logger.warning(
                "| Failed to delete repository %s/%s: %s",
                owner,
                repo_name,
                response.text
            )
            raise RuntimeError(  # pylint: disable=broad-exception-raised
                f"| Failed to delete repository {owner}/{repo_name}: "
                f"{response.status_code} {response.text}"
            )
        logger.info(
            "| Successfully deleted repository %s/%s",
            owner,
            repo_name
        )

    # ---------------------------------------------------------------------
    # Helper utilities (organisation vs user)
    # ---------------------------------------------------------------------

    def _get_authenticated_user(self) -> str:
        """Return cached authenticated username or fetch once from GitHub."""
        if hasattr(self, "_auth_user") and self._auth_user:
            return self._auth_user

        response = self.session.get("https://api.github.com/user")
        if response.status_code == 200:
            self._auth_user = response.json()["login"]  # pylint: disable=attribute-defined-outside-init
            return self._auth_user
        return None

    # ---------------------------------------------------------------------
    # Token management helpers
    # ---------------------------------------------------------------------
    def _update_session_token(self):
        """Update the session Authorization header with the current token."""
        current_token = self.token_pool.get_current_token()
        self.session.headers.update({"Authorization": f"Bearer {current_token}"})
        # Update backward compatibility attribute
        self.github_token = current_token

    def _rotate_token(self):
        """Rotate to the next token in the pool and update session."""
        next_token = self.token_pool.get_next_token()
        self.session.headers.update({"Authorization": f"Bearer {next_token}"})
        # Update backward compatibility attribute
        self.github_token = next_token
        logger.debug("| Rotated to next token in pool")

    # ---------------------------------------------------------------------
    # Generic request helper with rate-limit (403) retry handling
    # ---------------------------------------------------------------------
    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 2,
        sleep_seconds: int = 120,
        **kwargs,
    ):
        """Send a GitHub API request with basic rate-limit handling and token rotation.

        If a request receives HTTP 403 (rate limit):
        1. First try rotating to the next token in the pool
        2. If still rate limited, sleep and retry
        3. After max_retries are exhausted, raise RuntimeError
        """
        attempt = 0
        tokens_tried = 0

        while True:
            # Ensure we have the current token set
            self._update_session_token()

            resp = self.session.request(method, url, **kwargs)
            # Successful or non-rate-limited response – return immediately
            if resp.status_code != 403:
                return resp

            # 403 – very likely rate-limited
            # First, try rotating tokens if we have multiple
            if (
                self.token_pool.pool_size > 1
                and tokens_tried < self.token_pool.pool_size
            ):
                logger.warning(
                    "| GitHub API rate limit encountered. "
                    "Rotating to next token (tried %d/%d tokens)",
                    tokens_tried + 1,
                    self.token_pool.pool_size,
                )
                self._rotate_token()
                tokens_tried += 1
                continue

            # All tokens exhausted or single token, resort to sleep/retry
            if attempt >= max_retries:
                raise RuntimeError(
                    f"GitHub API rate limited after {attempt + 1} attempts "
                    f"with {self.token_pool.pool_size} token(s): "
                    f"{resp.status_code} {resp.text}"
                )

            logger.warning(
                "| All tokens rate limited (attempt %d/%d). Sleeping %d seconds before retrying …",
                attempt + 1,
                max_retries + 1,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            attempt += 1
            tokens_tried = 0  # Reset token counter for next attempt

    # =========================================================================
    # Initial State Selection and Repository Creation
    # =========================================================================

    # Initial state for each task category is resolved via self.initial_state_mapping
    def select_initial_state_for_task(self, task_category: str) -> Optional[str]:
        """Select initial state template for a task category."""
        return self.initial_state_mapping.get(task_category)

    def extract_repo_info_from_url(self, repo_url: str) -> tuple[str, str]:
        """Extract owner and repo name from GitHub URL."""
        try:
            # Support https://github.com/owner/repo format
            if "github.com" in repo_url:
                path = urlparse(repo_url).path.strip("/")
                parts = path.split("/")
                if len(parts) >= 2:
                    return parts[0], parts[1]

            raise ValueError(f"Invalid GitHub URL format: {repo_url}")

        except Exception as exc:
            logger.error(
                "| Failed to extract repo info from URL %s: %s",
                repo_url,
                exc
            )
            raise

    def get_service_config_for_agent(self) -> dict:
        """
        Get service-specific configuration for agent execution.

        Rotates to the next token in the pool before returning config
        to distribute load across tokens.

        Returns:
            Dictionary containing configuration needed by the agent/MCP server
        """
        service_config = {}

        # Add GitHub token if available
        if self.github_token:
            service_config["github_token"] = self.github_token

        return service_config

    def set_verification_environment(self, messages_path: str = None) -> None:
        """
        Set GitHub-specific environment variables for verification scripts.

        This ensures verification scripts use the same token as the current
        agent execution, maintaining consistency across the evaluation flow.

        Args:
            messages_path: Optional path to messages.json file for verification
        """
        # Set common MCP_MESSAGES if provided
        if messages_path:
            os.environ["MCP_MESSAGES"] = str(messages_path)

        # Set GitHub-specific token
        current_token = self.token_pool.get_current_token()
        os.environ["MCP_GITHUB_TOKEN"] = current_token
        logger.info("| Set MCP_GITHUB_TOKEN for verification scripts")

    def _enable_github_actions(self, owner: str, repo_name: str):
        """Enable GitHub Actions for the repository using REST API."""
        try:
            # Enable GitHub Actions
            url = (
                f"https://api.github.com/repos/{owner}/{repo_name}/actions/permissions"
            )
            response = self.session.put(
                url, json={"enabled": True, "allowed_actions": "all"}
            )

            if response.status_code in [200, 204]:
                logger.info(
                    "| Successfully enabled GitHub Actions for %s/%s", owner, repo_name
                )
            else:
                logger.warning(
                    "| Failed to enable GitHub Actions: %s %s",
                    response.status_code,
                    response.text,
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("| Failed to enable GitHub Actions: %s", exc)

    def _disable_github_actions(self, owner: str, repo_name: str):
        """Disable GitHub Actions for the repository using REST API."""
        try:
            # Disable GitHub Actions
            url = (
                f"https://api.github.com/repos/{owner}/{repo_name}/actions/permissions"
            )
            response = self.session.put(url, json={"enabled": False})

            if response.status_code in [200, 204]:
                logger.info(
                    "| Successfully disabled GitHub Actions for %s/%s", owner, repo_name
                )
            else:
                logger.warning(
                    "| Failed to disable GitHub Actions: %s %s",
                    response.status_code,
                    response.text,
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("| Failed to disable GitHub Actions: %s", exc)

    def _disable_repository_notifications(self, owner: str, repo_name: str):
        """Disable repository notifications to prevent email spam."""
        try:
            # Set repository notification subscription to ignore
            url = f"https://api.github.com/repos/{owner}/{repo_name}/subscription"
            response = self.session.put(
                url, json={"subscribed": False, "ignored": True}
            )

            if response.status_code in [200, 201]:
                logger.info(
                    "| Successfully disabled notifications for %s/%s", owner, repo_name
                )
            elif response.status_code == 403:
                # This is expected if the token doesn't have notifications scope
                logger.debug(
                    "| Cannot disable notifications for %s/%s "
                    "(token lacks notifications scope - this is OK)",
                    owner,
                    repo_name,
                )
            else:
                logger.warning(
                    "| Failed to disable repository notifications: %s %s",
                    response.status_code,
                    response.text,
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("| Failed to disable repository notifications: %s", exc)

    def _download_and_extract_github_template(self, template_name: str) -> bool:
        """
        Download and extract GitHub template from CDN using wget and unzip commands.

        This approach preserves original file timestamps and is simpler than Python zipfile.

        Args:
            template_name: Name of the template to download (e.g., "anthropics-claude-code")

        Returns:
            bool: True if download and extraction successful
        """
        try:
            # Get the URL from mapping
            if template_name not in self.github_template_url_mapping:
                logger.error(
                    "| No URL mapping found for template: %s",
                    template_name
                )
                return False

            template_url = self.github_template_url_mapping[template_name]
            # Allow override via environment variable
            template_url = os.getenv("GITHUB_TEMPLATE_URL", template_url)

            logger.info("| ○ Downloading GitHub template from: %s", template_url)

            # Create a temporary directory for the download
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                zip_path = temp_path / "github_template.zip"

                # Step 1: Download using wget/curl
                logger.info("| ○ Downloading GitHub template zip file...")
                try:
                    # Use wget if available, otherwise fall back to curl
                    if sys.platform == "win32":
                        # Windows: try wget, fall back to curl
                        try:
                            subprocess.run(
                                ["wget", "-O", str(zip_path), template_url],
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            # Fall back to curl
                            subprocess.run(
                                ["curl", "-L", "-o", str(zip_path), template_url],
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                    else:
                        # Unix-like systems: try wget, fall back to curl
                        try:
                            subprocess.run(
                                ["wget", "-O", str(zip_path), template_url],
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            # Fall back to curl
                            subprocess.run(
                                ["curl", "-L", "-o", str(zip_path), template_url],
                                capture_output=True,
                                text=True,
                                check=True,
                            )

                    logger.info("| ✓ Download completed successfully")
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("| Download failed: %s", exc)
                    return False

                # Step 2: Extract using unzip
                logger.info("| ○ Extracting GitHub template...")
                try:
                    # Extract to templates root directory
                    subprocess.run(
                        ["unzip", "-o", str(zip_path), "-d", str(self.templates_root)],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    logger.info("| ✓ Extraction completed successfully")
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("| Extraction failed: %s", exc)
                    return False

                # Step 3: Remove __MACOSX folder if it exists
                macosx_path = self.templates_root / "__MACOSX"
                self._remove_macosx_folder(macosx_path)

                # Verify the extracted template directory exists
                template_path = self.templates_root / template_name
                if not template_path.exists():
                    logger.error(
                        "| Extracted template directory not found at "
                        "expected path: %s",
                        template_path
                    )
                    return False

                logger.info(
                    f"| ✓ Successfully downloaded and extracted GitHub template to: {template_path}"
                )
                return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "| Failed to download and extract GitHub template: %s",
                exc
            )
            return False
