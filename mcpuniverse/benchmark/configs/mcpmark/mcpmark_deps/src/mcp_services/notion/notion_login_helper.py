"""
Notion Login Helper for MCPMark
=================================

This module provides a utility class and CLI script for logging into Notion
using Playwright. It saves the authenticated session state to a file,
which can be used for subsequent automated tasks.
"""
# pylint: disable=import-error
import argparse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src.logger import get_logger

# Initialize logger
logger = get_logger(__name__)


class BaseLoginHelper(ABC):  # pylint: disable=too-few-public-methods
    """Abstract base class for login helpers."""

    def __init__(self):
        """Initialize the base login helper."""

    @abstractmethod
    def login(self, **kwargs):
        """
        Perform login operation.

        Args:
            **kwargs: Login parameters specific to the service
        """



class NotionLoginHelper(BaseLoginHelper):
    """
    Utility helper for logging into Notion using Playwright.
    """

    SUPPORTED_BROWSERS = {"chromium", "firefox"}

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        headless: bool = True,
        state_path: Optional[str | Path] = None,
        browser: str = "firefox",
    ) -> None:
        """
        Initializes the Notion login helper.

        Args:
            url: The Notion URL to open after launching the browser.
            headless: Whether to run Playwright in headless mode.
            state_path: The path to save the authenticated session state.
            browser: The browser engine to use ('chromium' or 'firefox').
        """
        super().__init__()
        if browser not in self.SUPPORTED_BROWSERS:
            browsers_str = ', '.join(self.SUPPORTED_BROWSERS)
            raise ValueError(
                f"Unsupported browser '{browser}'. "
                f"Supported browsers are: {browsers_str}"
            )

        self.url = url or "https://www.notion.so/login"
        self.headless = headless
        self.browser_name = browser
        self.state_path = (
            Path(state_path or Path.cwd() / "notion_state.json").expanduser().resolve()
        )
        self._browser_context: Optional[BrowserContext] = None
        self._playwright = None
        self._browser = None

    def login(self, **kwargs) -> BrowserContext:  # pylint: disable=unused-argument
        """
        Launches a browser, performs login, and saves the session state.
        """
        if self.state_path.exists():
            try:
                self.state_path.unlink()
            except OSError as e:
                logger.warning("Unable to remove existing state file: %s", e)

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        browser_type = getattr(self._playwright, self.browser_name)
        self._browser = browser_type.launch(headless=self.headless)
        context = self._browser.new_context()
        page = context.new_page()

        logger.info("Navigating to Notion URL: %s", self.url)
        page.goto(self.url, wait_until="load")

        if self.headless:
            self._handle_headless_login(context)
        else:
            logger.info(
                "A browser window has been opened. Please complete the Notion login."
            )
            logger.info(
                "After you see your workspace, return to this terminal and press <ENTER>."
            )
            initial_url = page.url
            input()
            try:
                page.wait_for_url(lambda u: u != initial_url, timeout=10_000)
            except PlaywrightTimeoutError:
                pass  # It's okay if the URL doesn't change

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except PlaywrightTimeoutError:
            pass

        context.storage_state(path=str(self.state_path))
        logger.info("✅ Login successful! Session state saved to %s", self.state_path)

        self._browser_context = context
        return context

    def close(self) -> None:
        """Closes the underlying browser and Playwright instance."""
        if self._browser_context:
            try:
                self._browser_context.close()
            finally:
                self._browser_context = None
        if self._browser:
            try:
                self._browser.close()
            finally:
                self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def _handle_headless_login(self, context: BrowserContext) -> None:
        """
        Guides the user through the login process in headless mode.
        """
        page: Page = context.pages[0]
        login_url = "https://www.notion.so/login"
        page.goto(login_url, wait_until="domcontentloaded")

        email = input("Enter your Notion email address: ").strip()
        try:
            email_input = page.locator(
                'input[placeholder="Enter your email address..."]'
            )
            email_input.wait_for(state="visible", timeout=120_000)
            email_input.fill(email)
            email_input.press("Enter")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Timed out waiting for the email input field."
            ) from exc
        except Exception:  # pylint: disable=broad-exception-caught
            page.get_by_role("button", name="Continue", exact=True).click()

        try:
            code_input = page.locator('input[placeholder="Enter code"]')
            code_input.wait_for(state="visible", timeout=120_000)
            code = input("Enter the verification code from your email: ").strip()
            code_input.fill(code)
            code_input.press("Enter")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Timed out waiting for the verification code input."
            ) from exc
        except Exception:  # pylint: disable=broad-exception-caught
            page.get_by_role("button", name="Continue", exact=True).click()

        try:
            page.wait_for_url(lambda url: url != login_url, timeout=180_000)
        except PlaywrightTimeoutError:
            logger.warning("Login redirect timed out, but proceeding to save state.")

        if self.url and self.url != login_url:
            page.goto(self.url, wait_until="domcontentloaded")

    def __enter__(self) -> "NotionLoginHelper":
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    """Main entry point for the Notion login CLI script."""
    parser = argparse.ArgumentParser(
        description="Authenticate to Notion and generate a session state file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the login flow in headless mode (prompts for credentials).",
    )
    parser.add_argument(
        "--browser",
        default="firefox",
        choices=["chromium", "firefox"],
        help="The browser engine to use for Playwright.",
    )
    args = parser.parse_args()

    helper = NotionLoginHelper(headless=args.headless, browser=args.browser)
    with helper:
        logger.info("Login process completed.")


if __name__ == "__main__":
    main()
