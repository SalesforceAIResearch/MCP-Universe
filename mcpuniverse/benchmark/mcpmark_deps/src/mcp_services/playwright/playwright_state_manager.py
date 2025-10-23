"""
Playwright State Manager for MCPMark
======================================

This module manages browser contexts and test environments for Playwright-based
web automation tasks. Handles browser isolation, test page setup, and cleanup.
"""

import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from src.base.state_manager import BaseStateManager, InitialStateInfo
from src.base.task_manager import BaseTask
from src.logger import get_logger

logger = get_logger(__name__)


class PlaywrightStateManager(BaseStateManager):
    """
    Manages browser state and test environments for Playwright tasks.

    Provides browser context isolation, test page setup, and resource cleanup
    for web automation evaluation.
    """

    def __init__(
        self,
        browser: str = "chromium",
        headless: bool = True,
        state_path: Optional[Path] = None,
        network_origins: str = "*",
        user_profile: str = "isolated",
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ):
        """
        Initialize Playwright state manager.

        Args:
            browser: Browser engine to use ('chromium' or 'firefox')
            headless: Whether to run browser in headless mode
            state_path: Path to browser state file
            network_origins: Allowed network origins (comma-separated or *)
            user_profile: User profile type (isolated or persistent)
            viewport_width: Browser viewport width
            viewport_height: Browser viewport height
        """
        super().__init__(service_name="playwright")

        self.browser_name = browser
        # self.headless = headless
        self.headless = False
        self.state_path = state_path or Path.cwd() / "playwright_state.json"
        self.network_origins = network_origins
        self.user_profile = user_profile
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

        # Browser management
        self._playwright = None
        self._browser = None
        self._current_context: Optional[BrowserContext] = None

        # Task-specific tracking
        self._current_task_pages: List[Page] = []

        # Test environment URLs for different task categories
        self.test_environments = {
            "element_extraction": "https://mcp-eval-website.vercel.app/extraction",
            "form_interaction": "https://mcp-eval-website.vercel.app/forms/",
            "web_navigation": "https://mcp-eval-website.vercel.app/navigation",
            "authentication": "https://mcp-eval-website.vercel.app/auth/turnstile",
        }

        logger.info("Playwright state manager initialized")

    def _create_initial_state(self, task: BaseTask) -> Optional[InitialStateInfo]:
        """
        Create isolated browser context for task execution.

        Args:
            task: Task for which to create browser state

        Returns:
            InitialStateInfo with browser context details
        """
        try:
            logger.info(
                "| Skipping Playwright browser launch – no initial browser state "
                "needed for task: %s",
                task.name,
            )

            # Generate a lightweight identifier to allow resource tracking even
            # though no real browser context is created.
            context_id = f"noop_{task.category_id}_{task.task_id}_{int(time.time())}"

            # We still expose the canonical test URL (if any) because some
            # consumers add it to the task metadata.
            test_url = self.test_environments.get(task.category_id)

            # Record a dummy resource so cleanup logic remains symmetrical.
            self.track_resource(
                "browser_context",
                context_id,
                {
                    "task_name": task.name,
                    "task_category": task.category_id,
                    "test_url": test_url,
                },
            )

            return InitialStateInfo(
                state_id=context_id,
                state_url=test_url,
                metadata={
                    "browser": self.browser_name,
                    "headless": self.headless,
                    "test_url": test_url,
                    "task_category": task.category_id,
                },
            )

        except Exception as e:
            logger.error(f"Failed to create stub initial state for {task.name}: {e}")
            return None

    def _store_initial_state_info(
        self, task: BaseTask, state_info: InitialStateInfo
    ) -> None:
        """Store browser context information in task object."""
        if hasattr(task, "__dict__"):
            task.browser_context_id = state_info.state_id
            task.test_url = state_info.state_url
            task.browser_config = state_info.metadata

    def _cleanup_task_initial_state(self, task: BaseTask) -> bool:
        """Clean up browser context for specific task."""
        try:
            success = True

            # Close any open pages
            if self._current_task_pages:
                for page in self._current_task_pages:
                    try:
                        page.close()
                    except Exception as e:
                        logger.warning(f"Failed to close page: {e}")
                        success = False
                self._current_task_pages.clear()

            # Close browser context
            if self._current_context:
                try:
                    self._current_context.close()
                    logger.info("Closed browser context")
                except Exception as e:
                    logger.error(f"Failed to close browser context: {e}")
                    success = False
                finally:
                    self._current_context = None

            return success

        except Exception as e:
            logger.error(f"Error during browser cleanup for {task.name}: {e}")
            return False

    def _cleanup_single_resource(self, resource: Dict[str, Any]) -> bool:
        """Clean up a single browser resource."""
        try:
            if resource["type"] == "browser_context":
                # Context cleanup is handled in _cleanup_task_initial_state
                logger.debug(f"Browser context {resource['id']} marked for cleanup")
                return True

            logger.warning(f"Unknown resource type for cleanup: {resource['type']}")
            return False

        except Exception as e:
            logger.error(f"Failed to cleanup resource {resource}: {e}")
            return False

    def _get_context_options(self, task: BaseTask) -> Dict[str, Any]:
        """Get browser context options based on task requirements."""
        options = {
            "viewport": {"width": self.viewport_width, "height": self.viewport_height}
        }

        # Load browser state if available
        if self.state_path.exists():
            try:
                options["storage_state"] = str(self.state_path)
            except Exception as e:
                logger.warning(f"Failed to load browser state: {e}")

        # Task-specific context options
        if task.category_id == "form_interaction":
            # Enable form interactions
            options["permissions"] = ["geolocation"]
        elif task.category_id == "web_navigation":
            # Allow navigation between pages
            options["accept_downloads"] = False

        return options

    def _setup_test_environment(self, task: BaseTask) -> Optional[str]:
        """Set up test environment for task category."""
        try:
            test_url = self.test_environments.get(task.category_id)
            if not test_url:
                logger.warning(
                    f"No test environment defined for category: {task.category_id}"
                )
                return None

            # Create a page and navigate to test environment
            if self._current_context:
                page = self._current_context.new_page()

                # Navigate to test URL to ensure it's accessible
                page.goto(test_url, wait_until="networkidle", timeout=30000)
                logger.info(f"Test environment ready: {test_url}")

                # Track the page for cleanup
                self._current_task_pages.append(page)

                # Verify page loaded correctly
                title = page.title()
                if title:
                    logger.debug(f"Page loaded with title: {title}")

                return test_url

        except PlaywrightTimeoutError:
            logger.error(f"Timeout loading test environment: {test_url}")
        except Exception as e:
            logger.error(f"Failed to setup test environment: {e}")

        return None

    def get_current_context(self) -> Optional[BrowserContext]:
        """Get the current browser context."""
        return self._current_context

    def get_test_page(self) -> Optional[Page]:
        """Get a page for testing (creates new one if needed)."""
        if self._current_context:
            try:
                page = self._current_context.new_page()
                self._current_task_pages.append(page)
                return page
            except Exception as e:
                logger.error(f"Failed to create test page: {e}")
        return None

    def navigate_to_test_url(self, task: BaseTask) -> Optional[Page]:
        """Navigate to the test URL for a specific task."""
        test_url = self.test_environments.get(task.category_id)
        if not test_url:
            logger.error(f"No test URL defined for category: {task.category_id}")
            return None

        page = self.get_test_page()
        if page:
            try:
                page.goto(test_url, wait_until="networkidle", timeout=30000)
                logger.info(f"Navigated to test URL: {test_url}")
                return page
            except Exception as e:
                logger.error(f"Failed to navigate to {test_url}: {e}")

        return None

    def get_service_config_for_agent(self) -> dict:
        """
        Get service-specific configuration for agent execution.

        Returns:
            Dictionary containing browser configuration for MCP server
        """
        config = {
            "browser": self.browser_name,
            "headless": self.headless,
        }

        # Add browser state file if it exists
        if self.state_path.exists():
            config["browser_state"] = str(self.state_path)

        # Add test environment URLs
        config["test_environments"] = self.test_environments

        return config

    def close_all(self) -> None:
        """Close all browser resources."""
        try:
            # Close all pages
            for page in self._current_task_pages:
                try:
                    page.close()
                except Exception:
                    pass
            self._current_task_pages.clear()

            # Close context
            if self._current_context:
                self._current_context.close()
                self._current_context = None

            # Close browser
            if self._browser:
                self._browser.close()
                self._browser = None

            # Stop Playwright
            if self._playwright:
                self._playwright.stop()
                self._playwright = None

            logger.info("All browser resources closed")

        except Exception as e:
            logger.error(f"Error closing browser resources: {e}")

    def set_verification_environment(self, messages_path: str = None) -> None:
        """
        Set Playwright-specific environment variables for verification scripts.

        Args:
            messages_path: Optional path to messages.json file for verification
        """
        import os

        # Set common MCP_MESSAGES if provided
        if messages_path:
            os.environ["MCP_MESSAGES"] = str(messages_path)
            # Also set PLAYWRIGHT_WORK_DIR to the directory containing messages.json
            work_dir = str(Path(messages_path).parent)
            os.environ["PLAYWRIGHT_WORK_DIR"] = work_dir
            logger.info(f"| Set PLAYWRIGHT_WORK_DIR to: {work_dir}")
            logger.info(f"| Set MCP_MESSAGES to: {messages_path}")

    def __del__(self):
        """Ensure cleanup on deletion."""
        self.close_all()
