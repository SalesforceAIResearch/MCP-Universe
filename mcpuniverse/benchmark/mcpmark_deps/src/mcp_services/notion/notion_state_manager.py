"""
Notion State Manager for MCPMark
=================================

This module handles the duplication and management of Notion initial states
Pages for consistent task evaluation using Playwright automation.
"""

import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from notion_client import Client
from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src.base.state_manager import BaseStateManager, InitialStateInfo
from src.base.task_manager import BaseTask
from src.logger import get_logger
from src.mcp_services.notion.notion_task_manager import NotionTask
import re

# Initialize logger
logger = get_logger(__name__)

# Selectors for Notion UI elements
PAGE_MENU_BUTTON_SELECTOR = '[data-testid="more-button"], div.notion-topbar-more-button, [aria-label="More"], button[aria-label="More"]'
DUPLICATE_MENU_ITEM_SELECTOR = 'text="Duplicate"'
DUPLICATE_WITH_CONTENT_SELECTOR = 'text="Duplicate with content"'
MOVE_TO_MENU_ITEM_SELECTOR = 'text="Move to"'
MOVE_TO_SEARCH_INPUT_SELECTOR = (
    'input[placeholder*="Move page to"], textarea[placeholder*="Move page to"]'
)


class NotionStateManager(BaseStateManager):
    """
    Manages the state of Notion initial states using Playwright and the Notion API.
    """

    def __init__(
        self,
        source_notion_key: str,
        eval_notion_key: str,
        headless: bool = True,
        browser: str = "firefox",
        eval_parent_page_title: str = "MCPMark Eval Hub",
        source_parent_page_title: str = "MCPMark Source Hub",
    ):
        """
        Initializes the Notion state manager.

        Args:
            source_notion_key: The Notion API key for source workspace.
            eval_notion_key: The Notion API key for evaluation workspace.
            headless: Whether to run Playwright in headless mode.
            browser: The browser engine to use ('chromium' or 'firefox').
            eval_parent_page_title: Parent page title for evaluation workspace.
        """
        super().__init__(service_name="notion")
        supported_browsers = {"chromium", "firefox"}
        if browser not in supported_browsers:
            raise ValueError(
                f"Unsupported browser '{browser}'. Supported browsers are: {', '.join(supported_browsers)}"
            )

        self.browser_name = browser

        # Initialize separate Notion clients with provided keys
        if not source_notion_key or not eval_notion_key:
            raise ValueError(
                "Both source_notion_key and eval_notion_key must be provided to NotionStateManager."
            )

        self.source_notion_client = Client(auth=source_notion_key)
        self.eval_notion_client = Client(auth=eval_notion_key)

        self.headless = headless
        self.state_file = Path("notion_state.json")
        # Parent page under which duplicated pages should be moved for evaluation
        self.eval_parent_page_title = eval_parent_page_title
        # Source hub page that contains all initial-state templates
        self.source_parent_page_title = source_parent_page_title

        # Cache resolved parent page IDs to avoid repeated workspace-wide searches
        self._eval_parent_page_id: Optional[str] = None
        self._source_hub_page_id: Optional[str] = None

        # Validate initialization
        if not self.source_notion_client or not self.eval_notion_client:
            raise ValueError(
                "Both source_notion_key and eval_notion_key must be provided and valid"
            )

        if not self.state_file.exists():
            raise FileNotFoundError(
                "Authentication state 'notion_state.json' not found. Run the Notion login helper first."
            )

        logger.info("Notion state manager initialized successfully")

    # =========================================================================
    # Core Template Methods (Required by BaseStateManager)
    # =========================================================================

    def _cleanup_eval_hub_orphans(self) -> None:
        """Clean up all pages in MCPMark Eval Hub before creating new task state."""
        try:
            parent_page_id = self._ensure_eval_parent_page_id()

            if not parent_page_id:
                logger.debug(
                    "| ✗ Parent page '%s' not found in eval workspace, skipping cleanup",
                    self.eval_parent_page_title,
                )
                return

            # Get all child pages and archive them
            children = self.eval_notion_client.blocks.children.list(
                block_id=parent_page_id
            )
            orphan_count = 0
            for child in children.get("results", []):
                if child.get("type") == "child_page":
                    try:
                        self.eval_notion_client.pages.update(
                            page_id=child["id"], archived=True
                        )
                        orphan_count += 1
                        logger.debug("| ✓ Archived orphan page: %s", child["id"])
                    except Exception as e:
                        logger.warning(
                            "| ✗ Failed to archive orphan page %s: %s", child["id"], e
                        )

            if orphan_count > 0:
                logger.info(
                    "| ✓ Cleaned up %d orphan page(s) from MCPMark Eval Hub", orphan_count
                )

        except Exception as e:
            logger.warning("Orphan cleanup failed (non-critical, continuing): %s", e)
            # Don't raise exception - allow execution to continue

    def _ensure_eval_parent_page_id(self) -> Optional[str]:
        """Resolve and cache the evaluation hub parent page ID."""
        if self._eval_parent_page_id:
            return self._eval_parent_page_id

        try:
            response = self.eval_notion_client.search(
                query=self.eval_parent_page_title,
                filter={"property": "object", "value": "page"},
            )

            for result in response.get("results", []):
                props = result.get("properties", {})
                title_prop = props.get("title", {}).get("title") or props.get(
                    "Name", {}
                ).get("title")
                if not title_prop:
                    continue

                title = "".join(t.get("plain_text", "") for t in title_prop).strip()
                if title == self.eval_parent_page_title:
                    self._eval_parent_page_id = result.get("id")
                    break

            if not self._eval_parent_page_id:
                logger.debug(
                    "| ✗ Eval parent page '%s' not found via search",
                    self.eval_parent_page_title,
                )
        except Exception as e:
            logger.error(
                "| ✗ Failed to resolve eval parent page '%s': %s",
                self.eval_parent_page_title,
                e,
            )

        return self._eval_parent_page_id

    def _ensure_source_hub_page_id(self) -> Optional[str]:
        """Resolve and cache the source hub parent page ID used for initial states."""
        if self._source_hub_page_id:
            return self._source_hub_page_id

        try:
            hub_search = self.source_notion_client.search(
                query=self.source_parent_page_title,
                filter={"property": "object", "value": "page"},
            )

            for result in hub_search.get("results", []):
                props = result.get("properties", {})
                title_prop = props.get("title", {}).get("title") or props.get(
                    "Name", {}
                ).get("title")
                current_title = "".join(
                    t.get("plain_text", "") for t in (title_prop or [])
                ).strip()
                if current_title == self.source_parent_page_title:
                    self._source_hub_page_id = result.get("id")
                    break

            if not self._source_hub_page_id:
                logger.error(
                    "| ✗ Source hub page '%s' not found.",
                    self.source_parent_page_title,
                )
        except Exception as e:
            logger.error(
                "| ✗ Failed to resolve source hub page '%s': %s",
                self.source_parent_page_title,
                e,
            )

        return self._source_hub_page_id

    def _wait_for_database_ready(
        self,
        page_id: str,
        max_retries: int = 10,
        retry_delay: int = 2
    ) -> bool:
        """
        Wait for the database backend to be ready by checking page accessibility.

        Args:
            page_id: The ID of the page to check
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            True if the database is ready, False if timeout
        """
        logger.info("| ○ Starting heartbeat detection for page %s", page_id)

        for attempt in range(max_retries):
            try:
                # Try to retrieve the page from the evaluation workspace
                result = self.eval_notion_client.pages.retrieve(page_id=page_id)

                # Check if we got a valid response
                if result and isinstance(result, dict):
                    # Additional check: try to get page properties
                    if "properties" in result:
                        logger.info(
                            "| ✓ Database backend is ready (attempt %d/%d)",
                            attempt + 1,
                            max_retries
                        )
                        return True

            except Exception as e:
                logger.debug(
                    "| ✗ Database not ready yet (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    str(e)
                )

            # Wait before next retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        logger.error(
            "| ✗ Database backend failed to become ready after %d attempts",
            max_retries
        )
        return False

    def _create_initial_state(self, task: BaseTask) -> Optional[InitialStateInfo]:
        """Create initial state by duplicating Notion page."""
        if not isinstance(task, NotionTask):
            logger.error("Task must be NotionTask for Notion state manager")
            return None

        # Clean up any orphan pages in eval hub before creating new state
        self._cleanup_eval_hub_orphans()

        try:
            initial_state_title = self._category_to_initial_state_title(task.category_id)
            initial_state_info = self._find_initial_state_by_title(initial_state_title)

            if not initial_state_info:
                logger.error(
                    "| ✗ Initial state not found for category '%s' (title: '%s')",
                    task.category_id,
                    initial_state_title,
                )
                return None

            _, initial_state_url = initial_state_info

            duplicated_url, duplicated_id = self._duplicate_initial_state_for_task(
                initial_state_url, task.category_id, task.name
            )

            # Wait for database backend to be ready
            logger.info("| ○ Checking database backend accessibility for duplicated page...")
            if not self._wait_for_database_ready(duplicated_id):
                logger.error(
                    "| ✗ Database backend is not accessible after duplication for task %s",
                    task.name
                )
                # Clean up the duplicated page if database is not ready
                try:
                    self.eval_notion_client.pages.update(
                        page_id=duplicated_id, archived=True
                    )
                    logger.info("| ✓ Cleaned up inaccessible duplicated page: %s", duplicated_id)
                except Exception as cleanup_error:
                    logger.error("| ✗ Failed to clean up duplicated page: %s", cleanup_error)

                raise RuntimeError(
                    f"| ✗ Database backend failed to become ready for duplicated page {duplicated_id}"
                )

            time.sleep(5) # allow the page to fully load

            return InitialStateInfo(
                state_id=duplicated_id,
                state_url=duplicated_url,
                metadata={
                    "original_url": initial_state_url,
                    "category": task.category_id,
                    "task_name": task.name,
                },
            )

        except Exception as e:
            logger.error(f"| ✗ Failed to create initial state for {task.name}: {e}")
            return None

    def _store_initial_state_info(
        self, task: BaseTask, state_info: InitialStateInfo
    ) -> None:
        """Store initial state information in NotionTask object."""
        if isinstance(task, NotionTask):
            task.duplicated_initial_state_id = state_info.state_id
            task.duplicated_initial_state_url = state_info.state_url
            task.original_initial_state_url = state_info.metadata.get("original_url")

            # Track the duplicated page for cleanup
            self.track_resource("page", state_info.state_id, state_info.metadata)

    def _cleanup_task_initial_state(self, task: BaseTask) -> bool:
        """Clean up initial state for a specific Notion task."""
        if not isinstance(task, NotionTask):
            return True  # Nothing to clean up for non-Notion tasks

        initial_state_id = task.duplicated_initial_state_id
        if not initial_state_id:
            logger.warning(
                "| ✗ No duplicated initial state ID found for task %s, skipping cleanup.",
                task.name,
            )
            return False

        try:
            # Archive the duplicated page
            self.eval_notion_client.pages.update(
                page_id=initial_state_id, archived=True
            )
            logger.info("| ✓ Archived page initial state: %s", initial_state_id)

            # Remove from tracked resources to avoid duplicate cleanup
            self.tracked_resources = [
                r
                for r in self.tracked_resources
                if not (r["type"] == "page" and r["id"] == initial_state_id)
            ]

            return True
        except Exception as e:
            logger.error("| ✗ Failed to archive initial state %s: %s", initial_state_id, e)
            return False

    def _cleanup_single_resource(self, resource: Dict[str, Any]) -> bool:
        """Clean up a single Notion resource."""
        if resource["type"] == "page":
            try:
                self.eval_notion_client.pages.update(
                    page_id=resource["id"], archived=True
                )
                logger.info(f"| ✓ Archived Notion page: {resource['id']}")
                return True
            except Exception as e:
                logger.error(f"| ✗ Failed to archive Notion page {resource['id']}: {e}")
                return False

        logger.warning(f"| ? Unknown resource type for cleanup: {resource['type']}")
        return False

    # =========================================================================
    # Notion API Operations
    # =========================================================================

    def _rename_initial_state_via_api(
        self, initial_state_id: str, new_title: str
    ) -> None:
        """Renames a Notion page using the API."""
        try:
            self.eval_notion_client.pages.update(
                page_id=initial_state_id,
                properties={"title": {"title": [{"text": {"content": new_title}}]}},
            )
        except Exception as e:
            logger.error("| ✗ Failed to rename page via API: %s", e)

    # ------------------------------------------------------------------
    # Playwright helpers
    # ------------------------------------------------------------------

    # =========================================================================
    # Playwright Automation Methods
    # =========================================================================

    def _move_current_page_to_env(
        self, page: Page, *, wait_timeout: int = 60_000
    ) -> None:
        """Moves the currently open page into the designated evaluation parent page.

        This operation is done via Playwright UI automation because the Notion API
        does not yet expose a direct "move" endpoint for pages. It relies on the
        following sequence:

        1. Open the page action menu (same selector as duplication).
        2. Choose the "Move to" menu item.
        3. In the search field that appears (placeholder starts with
           "Move page to"), type the target parent page title.
        4. Click the matching search result to complete the move.
        """

        logger.info(
            "| ○ Moving duplicated page to evaluation parent '%s'...",
            self.eval_parent_page_title,
        )

        try:
            # Step 1: Open the page menu
            page.wait_for_selector(
                PAGE_MENU_BUTTON_SELECTOR, state="visible", timeout=30_000
            )
            page.click(PAGE_MENU_BUTTON_SELECTOR)

            # Step 2: Select "Move to"
            page.hover(MOVE_TO_MENU_ITEM_SELECTOR)
            page.click(MOVE_TO_MENU_ITEM_SELECTOR)

            # Step 3: Fill the destination title
            page.wait_for_selector(
                MOVE_TO_SEARCH_INPUT_SELECTOR, state="visible", timeout=15_000
            )

            # Ensure focus then type the destination title – using type() triggers
            # key events Notion relies on for search filtering.
            search_input = page.locator(MOVE_TO_SEARCH_INPUT_SELECTOR).first
            search_input.click()
            search_input.fill("")  # Clear any residual text (safety)
            search_input.type(self.eval_parent_page_title, delay=50)

            # Step 4: Wait for the search result matching the page title, then click it
            # Selector for the menu item row – ensure we click the outer container, not a nested <div>
            result_selector = (
                f'div[role="menuitem"]:has-text("{self.eval_parent_page_title}")'
            )
            page.wait_for_selector(
                result_selector, state="visible", timeout=wait_timeout
            )
            page.locator(result_selector).first.click(force=True)

            # Wait for the dialog to disappear – indicates move finished
            page.wait_for_selector(
                MOVE_TO_SEARCH_INPUT_SELECTOR, state="detached", timeout=wait_timeout
            )

            # Give Notion a brief moment to process the move
            time.sleep(3)
        except PlaywrightTimeoutError as e:
            logger.error(
                "| ✗ Playwright timed out while moving page to evaluation parent – move may have failed."
            )
            raise RuntimeError("Playwright timeout during move-to operation") from e
        except Exception as exc:
            logger.error("| ✗ Unexpected error during move-to operation: %s", exc)
            # Propagate the error to allow retry logic at higher level if necessary
            raise

    def _category_to_initial_state_title(self, category: str) -> str:
        """Converts a category name to a capitalized initial state title."""
        return " ".join(word.capitalize() for word in category.split("_"))

    def _extract_initial_state_id_from_url(self, url: str) -> str:
        """Extracts the initial state ID from a Notion URL."""
        slug = url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
        compact = "".join(c for c in slug if c.isalnum())
        if len(compact) < 32:
            raise ValueError(f"Could not parse initial state ID from URL: {url}")
        compact = compact[-32:]
        return f"{compact[:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:]}"

    # =========================================================================
    # URL and State Utilities
    # =========================================================================

    def _get_slug_base(self, url: str) -> str:
        """Returns the slug part without its trailing 32-char ID (hyphen separated)."""
        slug = url.split("?", 1)[0].split("#", 1)[0].rstrip("/").split("/")[-1]
        match = re.match(r"^(.*)-([0-9a-fA-F]{32})$", slug)
        if match:
            return match.group(1)
        return slug

    def _is_valid_duplicate_url(self, original_url: str, duplicated_url: str) -> bool:
        """Checks whether duplicated_url looks like a Notion duplicate (original slug + '-N')."""
        orig_base = self._get_slug_base(original_url)
        dup_base = self._get_slug_base(duplicated_url)
        if not dup_base.startswith(orig_base + "-"):
            return False
        suffix = dup_base[len(orig_base) + 1 :]
        return suffix.isdigit()

    def _find_initial_state_by_title(self, title: str) -> Optional[Tuple[str, str]]:
        """Find a child page under the source hub by exact title.

        Strategy:
        - Locate the source hub page ("MCPBench Source Hub") via search to get its ID.
        - List its first-level children via `blocks.children.list`.
        - Find a `child_page` whose title exactly matches `title`.
        - Return the page ID and URL (retrieved via `pages.retrieve`).
        """
        try:
            # 1) Resolve the source hub page once and reuse its ID
            source_hub_id = self._ensure_source_hub_page_id()

            if not source_hub_id:
                return None

            # 2) List first-level children of the hub page and find exact title match
            matched_child_id: Optional[str] = None
            next_cursor = None

            while True:
                kwargs = {"block_id": source_hub_id}
                if next_cursor:
                    kwargs["start_cursor"] = next_cursor

                children = self.source_notion_client.blocks.children.list(**kwargs)
                for child in children.get("results", []):
                    if child.get("type") != "child_page":
                        continue  # Only consider child pages
                    child_title = (child.get("child_page", {}) or {}).get("title", "").strip()
                    if child_title == title:
                        matched_child_id = child.get("id")
                        break

                if matched_child_id or not children.get("has_more"):
                    break

                next_cursor = children.get("next_cursor")

            if not matched_child_id:
                logger.debug("| ✗ No child page titled '%s' under '%s'", title, self.source_parent_page_title)
                return None

            # 3) Retrieve the page to get its canonical URL
            try:
                page_obj = self.source_notion_client.pages.retrieve(page_id=matched_child_id)
                page_url = page_obj.get("url")
            except Exception as e:
                logger.warning("| ✗ Failed to retrieve page URL for '%s' (%s): %s", title, matched_child_id, e)
                page_url = None

            if not page_url:
                # Fall back to returning just the ID if URL couldn't be retrieved
                logger.debug("| ○ Returning page ID without URL for '%s'", title)
                return matched_child_id, ""

            return matched_child_id, page_url
        except Exception as e:
            logger.error("| ✗ Error locating initial state '%s' via children listing: %s", title, e)
            return None

    # =========================================================================
    # Duplication and State Management
    # =========================================================================
    # NOTE: Initial state type detection logic has been removed because all initial states are pages.

    def _duplicate_current_initial_state(
        self,
        page: Page,
        new_title: Optional[str] = None,
        *,
        original_initial_state_id: str,
        original_initial_state_title: str,
        wait_timeout: int = 180_000,
    ) -> str:
        """Duplicates the currently open Notion initial state using Playwright."""
        try:
            logger.info("| ○ Opening page menu...")
            page.wait_for_selector(
                PAGE_MENU_BUTTON_SELECTOR, state="visible", timeout=30_000
            )
            page.click(PAGE_MENU_BUTTON_SELECTOR)

            logger.info("| ○ Clicking 'Duplicate'...")
            page.hover(DUPLICATE_MENU_ITEM_SELECTOR)
            page.click(DUPLICATE_MENU_ITEM_SELECTOR)

            original_url = page.url
            logger.info(
                "| ○ Waiting for duplicated initial state to load (up to %.1f s)...",
                wait_timeout / 1000,
            )
            page.wait_for_url(lambda url: url != original_url, timeout=wait_timeout)

            # wait for the page to fully load
            time.sleep(5)
            duplicated_url = page.url
            # Validate that the resulting URL is a genuine duplicate of the original template.
            if not self._is_valid_duplicate_url(original_url, duplicated_url):
                # Sometimes duplication succeeds but UI navigates to parent instead of the new page.
                # In that case, try to find the most recently created page named exactly "<title> (1)".
                logger.warning(
                    "| ✗ Duplicate URL pattern mismatch. Attempting recovery by searching for latest '%s (1)' page...",
                    original_initial_state_title,
                )

                target_title = f"{original_initial_state_title} (1)"
                try:
                    # Wait 5 seconds before the first search to allow Notion to index the new page
                    time.sleep(5)

                    attempts = 3
                    source_hub_id = self._ensure_source_hub_page_id()
                    if not source_hub_id:
                        logger.error(
                            "| ✗ Cannot resolve source hub ID while locating '%s' duplicate.",
                            target_title,
                        )
                    else:
                        for retry_idx in range(attempts):
                            candidates = []
                            next_cursor = None

                            while True:
                                kwargs: Dict[str, Any] = {"block_id": source_hub_id}
                                if next_cursor:
                                    kwargs["start_cursor"] = next_cursor

                                children = self.source_notion_client.blocks.children.list(**kwargs)
                                for child in children.get("results", []):
                                    if child.get("type") != "child_page":
                                        continue
                                    child_id = child.get("id")
                                    if child_id == original_initial_state_id:
                                        continue

                                    child_title = (
                                        (child.get("child_page", {}) or {})
                                        .get("title", "")
                                        .strip()
                                    )
                                    if child_title != target_title:
                                        continue

                                    created_time = child.get("created_time") or child.get(
                                        "last_edited_time"
                                    )
                                    candidates.append((created_time or "", child_id))

                                if not children.get("has_more"):
                                    break

                                next_cursor = children.get("next_cursor")

                            if candidates:
                                latest_child_id = max(candidates, key=lambda x: x[0])[1]
                                fallback_url = None
                                try:
                                    page_obj = self.source_notion_client.pages.retrieve(
                                        page_id=latest_child_id
                                    )
                                    fallback_url = page_obj.get("url")
                                except Exception as retrieve_error:
                                    logger.warning(
                                        "| ✗ Failed to resolve URL for duplicate '%s': %s",
                                        latest_child_id,
                                        retrieve_error,
                                    )

                                if fallback_url:
                                    logger.info(
                                        "| ○ Navigating directly to latest '%s' duplicate via children list...",
                                        target_title,
                                    )
                                    page.goto(fallback_url, wait_until="load", timeout=60_000)
                                    time.sleep(5)
                                    duplicated_url = page.url
                                    break

                            if retry_idx < attempts - 1:
                                logger.debug(
                                    "| ○ '%s' not visible yet via children listing. Waiting 5s before retry %d/%d...",
                                    target_title,
                                    retry_idx + 1,
                                    attempts - 1,
                                )
                                time.sleep(5)

                    # Re-validate after attempted recovery
                    if not self._is_valid_duplicate_url(original_url, duplicated_url):
                        logger.error(
                            "| ✗ Could not locate a valid '%s' duplicate after recovery attempt.\n|  Original: %s\n|  Observed: %s",
                            target_title,
                            original_url,
                            duplicated_url,
                        )
                        # Attempt to clean up stray duplicate before propagating error.
                        self._cleanup_orphan_duplicate(
                            original_initial_state_id, original_initial_state_title
                        )
                        raise RuntimeError(
                            "Duplicate URL pattern mismatch – duplication likely failed"
                        )
                except Exception as search_exc:
                    logger.error(
                        "| ✗ Failed during recovery search for '%s': %s",
                        target_title,
                        search_exc,
                    )
                    # Attempt to clean up stray duplicate before propagating error.
                    self._cleanup_orphan_duplicate(
                        original_initial_state_id, original_initial_state_title
                    )
                    raise RuntimeError(
                        "Duplicate URL pattern mismatch – duplication likely failed"
                    ) from search_exc

            duplicated_initial_state_id = self._extract_initial_state_id_from_url(
                duplicated_url
            )

            # Always move to evaluation parent
            self._move_current_page_to_env(page, wait_timeout=wait_timeout)

            # Rename if new title is provided
            if new_title:
                self._rename_initial_state_via_api(
                    duplicated_initial_state_id, new_title
                )

            # verify whether the page is moved to the evaluation parent page
            try:
                result = self.eval_notion_client.pages.retrieve(
                    page_id=duplicated_initial_state_id
                )
                if not result or not isinstance(result, dict):
                    logger.error(
                        "| ✗ Playwright move to error: Notion API did not return a valid page dict after move."
                    )
                    raise RuntimeError(
                        "Playwright move to error: Notion API did not return a valid page dict after move."
                    )
                logger.info(
                    "| ✓ Page moved to '%s' successfully.", self.eval_parent_page_title
                )
            except Exception as move_exc:
                logger.error(f"Playwright move to error: {move_exc}")
                raise RuntimeError(
                    "Playwright move to error: Notion client failed to retrieve page after move."
                ) from move_exc

            return duplicated_initial_state_id
        except PlaywrightTimeoutError as e:
            logger.error("Playwright timed out while duplicating initial state.")
            raise RuntimeError("Playwright timeout during duplication") from e

    # =========================================================================
    # Cleanup and Maintenance
    # =========================================================================

    def _cleanup_orphan_duplicate(
        self,
        original_initial_state_id: str,
        initial_state_title: str,
    ) -> bool:
        """Finds and archives a stray duplicate ("orphan") that matches pattern 'Title (n)'.

        Returns True if at least one orphan duplicate was archived.
        """
        try:
            source_hub_id = self._ensure_source_hub_page_id()
            if not source_hub_id:
                logger.error(
                    "| ✗ Cannot resolve source hub while cleaning up duplicates for '%s'",
                    initial_state_title,
                )
                return False

            # Only consider exactly one copy "Title (1)".
            title_regex = re.compile(rf"^{re.escape(initial_state_title)}\s*\(1\)$")

            archived_any = False
            next_cursor = None
            while True:
                kwargs: Dict[str, Any] = {"block_id": source_hub_id}
                if next_cursor:
                    kwargs["start_cursor"] = next_cursor

                children = self.source_notion_client.blocks.children.list(**kwargs)
                for child in children.get("results", []):
                    if child.get("type") != "child_page":
                        continue

                    dup_id = child.get("id")
                    if dup_id == original_initial_state_id:
                        continue

                    title_plain = (
                        (child.get("child_page", {}) or {}).get("title", "")
                    ).strip()
                    if not title_regex.match(title_plain):
                        continue  # not a numbered duplicate

                    try:
                        self.source_notion_client.pages.update(
                            page_id=dup_id, archived=True
                        )
                        logger.info("| ✓ Archived orphan duplicate (%s): %s", "page", dup_id)
                        archived_any = True
                    except Exception as exc:
                        logger.warning("| ✗ Failed to archive orphan page %s: %s", dup_id, exc)

                if not children.get("has_more"):
                    break

                next_cursor = children.get("next_cursor")

            return archived_any
        except Exception as exc:
            logger.warning(
                "Error while attempting to cleanup orphan duplicate: %s", exc
            )
            return False

    def _duplicate_initial_state_for_task(
        self,
        initial_state_url: str,
        category: str,
        task_name: str,
        *,
        max_retries: int = 2,
        initial_wait_ms: int = 180_000,
    ) -> Tuple[str, str]:
        """Duplicates an initial state for a task, with retries for reliability."""
        if not self.state_file.exists():
            raise FileNotFoundError(
                "Authentication state 'notion_state.json' not found. "
                "Run the Notion login helper first."
            )

        last_exc = None
        for attempt in range(max_retries + 1):
            wait_timeout = initial_wait_ms * (attempt + 1)
            try:
                with sync_playwright() as p:
                    browser_type = getattr(p, self.browser_name)
                    browser: Browser = browser_type.launch(headless=self.headless)
                    context = browser.new_context(storage_state=str(self.state_file))
                    page = context.new_page()

                    logger.info("| ○ Navigating to initial state for %s...", category)
                    # Start timing from the moment we begin navigating to the initial state page.
                    start_time = time.time()
                    page.goto(initial_state_url, wait_until="load", timeout=60_000)
                    context.storage_state(path=str(self.state_file))

                    initial_state_id = self._extract_initial_state_id_from_url(
                        initial_state_url
                    )
                    initial_state_title = self._category_to_initial_state_title(
                        category
                    )

                    duplicated_id = self._duplicate_current_initial_state(
                        page,
                        new_title=initial_state_title,  # Use original initial state name without (1) suffix
                        original_initial_state_id=initial_state_id,
                        original_initial_state_title=initial_state_title,
                        wait_timeout=wait_timeout,
                    )
                    duplicated_url = page.url
                    # Validate URL pattern again at this higher level (should already be validated inside).
                    context.storage_state(path=str(self.state_file))
                    # Log how long the whole duplication (navigate → duplicate) took.
                    elapsed = time.time() - start_time
                    logger.info(
                        "| ✓ Initial state duplicated successfully in %.2f seconds (task: %s).",
                        elapsed,
                        task_name,
                    )
                    return duplicated_url, duplicated_id
            except Exception as e:
                # No additional cleanup here—handled inside _duplicate_current_template.
                last_exc = e
                if attempt < max_retries:
                    logger.warning(
                        "| ✗ Duplication attempt %d failed: %s. Retrying...",
                        attempt + 1,
                        e,
                    )
                time.sleep(120 * attempt + 120)

        raise RuntimeError(
            f"Initial state duplication failed for task '{task_name}' after {max_retries + 1} attempts: {last_exc}"
        )

    def get_service_config_for_agent(self) -> dict:
        """
        Get service-specific configuration for agent execution.

        Returns:
            Dictionary containing configuration needed by the agent/MCP server
        """
        from src.config.config_schema import ConfigRegistry

        # Get the eval_api_key from config registry
        config = ConfigRegistry.get_config("notion").get_all()
        service_config = {}

        if "eval_api_key" in config:
            service_config["notion_key"] = config["eval_api_key"]

        return service_config
