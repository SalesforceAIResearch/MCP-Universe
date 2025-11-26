#!/usr/bin/env python3
"""
Notion Login Helper for MCPMark
=================================

A simplified and improved utility for logging into Notion and saving session state.

Usage:
    python notion_login.py                    # Interactive mode with GUI browser
    python notion_login.py --headless         # Headless mode (email + code)
    python notion_login.py --browser chromium # Use Chromium instead of Firefox
    python notion_login.py --output /path/to/state.json  # Custom output path
"""

import argparse
import sys
from pathlib import Path
from typing import Optional
import traceback

try:
    from playwright.sync_api import (
        BrowserContext,
        Page,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:
    print("❌ Error: Playwright is not installed.")
    print("📦 Please install it with: pip install playwright")
    print("🌐 Then install browsers with: playwright install")
    sys.exit(1)


class NotionLoginHelper:
    """
    Simplified utility helper for logging into Notion using Playwright.
    """

    SUPPORTED_BROWSERS = {"chromium", "firefox"}
    # Default to MCP-Universe root directory
    DEFAULT_STATE_PATH = Path(__file__).parent.parent.parent / "notion_state.json"

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        headless: bool = False,
        state_path: Optional[str | Path] = None,
        browser: str = "firefox",
    ) -> None:
        """
        Initialize the Notion login helper.

        Args:
            url: The Notion URL to open (default: login page)
            headless: Run in headless mode (requires email + verification code)
            state_path: Where to save the session state (default: MCP-Universe/notion_state.json)
            browser: Browser to use ('chromium' or 'firefox')
        """
        if browser not in self.SUPPORTED_BROWSERS:
            raise ValueError(
                f"Unsupported browser '{browser}'. Choose: {', '.join(self.SUPPORTED_BROWSERS)}"
            )

        self.url = url or "https://www.notion.so/login"
        self.headless = headless
        self.browser_name = browser
        self.state_path = Path(state_path or self.DEFAULT_STATE_PATH).expanduser().resolve()

        self._browser_context: Optional[BrowserContext] = None
        self._playwright = None
        self._browser = None

    def login(self) -> BrowserContext:
        """
        Launch browser, perform login, and save session state.
        
        Returns:
            BrowserContext: The authenticated browser context
        """
        # Remove old state file if exists
        if self.state_path.exists():
            print(f"🗑️  Removing old state file: {self.state_path}")
            try:
                self.state_path.unlink()
            except OSError as e:
                print(f"⚠️  Warning: Could not remove old state file: {e}")

        # Ensure output directory exists
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Start Playwright
        print(f"🚀 Starting {self.browser_name} browser...")
        self._playwright = sync_playwright().start()
        browser_type = getattr(self._playwright, self.browser_name)
        self._browser = browser_type.launch(headless=self.headless)
        context = self._browser.new_context()
        page = context.new_page()

        print(f"🌐 Navigating to: {self.url}")
        page.goto(self.url, wait_until="load")

        # Handle login based on mode
        if self.headless:
            self._handle_headless_login(page)
        else:
            self._handle_interactive_login(page)

        # Wait for page to stabilize
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        # Save session state
        print(f"💾 Saving session state to: {self.state_path}")
        context.storage_state(path=str(self.state_path))
        print("✅ Login successful! Session state saved.")
        print(f"📁 File: {self.state_path}")

        self._browser_context = context
        return context

    def _handle_interactive_login(self, page: Page) -> None:
        """
        Guide user through interactive login with a visible browser window.
        """
        print("\n" + "="*60)
        print("🔑 NOTION LOGIN - INTERACTIVE MODE")
        print("="*60)
        print("📌 A browser window has opened.")
        print("📌 Please complete the Notion login in the browser.")
        print("📌 After you see your workspace, return here and press ENTER.")
        print("="*60 + "\n")

        initial_url = page.url
        input("Press ENTER after completing login in the browser... ")

        # Check if URL changed (indicates successful login)
        try:
            page.wait_for_url(lambda u: u != initial_url, timeout=5000)
            print("✅ Login detected!")
        except PlaywrightTimeoutError:
            print("⚠️  URL didn't change, but proceeding anyway...")

    def _handle_headless_login(self, page: Page) -> None:
        """
        Guide user through headless login (email + verification code).
        """
        print("\n" + "="*60)
        print("🔑 NOTION LOGIN - HEADLESS MODE")
        print("="*60)

        login_url = "https://www.notion.so/login"
        page.goto(login_url, wait_until="domcontentloaded")

        # Step 1: Enter email
        print("\n📧 Step 1: Enter your email")
        email = input("Enter your Notion email address: ").strip()
        self._submit_email(page, email)

        # Step 2: Enter verification code
        print("\n🔐 Step 2: Check your email for a verification code")
        code = input("Enter the verification code from your email: ").strip()
        self._submit_code(page, code)

        # Wait for redirect after login
        print("\n⏳ Waiting for login to complete...")
        try:
            page.wait_for_url(lambda url: url != login_url, timeout=60000)
            print("✅ Login successful!")
        except PlaywrightTimeoutError:
            print("⚠️  Login redirect timed out, but proceeding to save state...")

        # Navigate to target URL if specified
        if self.url and self.url != login_url:
            print(f"🌐 Navigating to: {self.url}")
            page.goto(self.url, wait_until="domcontentloaded")

    def _submit_email(self, page: Page, email: str) -> None:
        """Fill and submit email in headless flow."""
        try:
            email_input = page.locator('input[placeholder="Enter your email address..."]')
            email_input.wait_for(state="visible", timeout=10000)
            email_input.fill(email)
            email_input.press("Enter")
            print("✅ Email submitted")
        except PlaywrightTimeoutError as exc:
            print("❌ Error: Email input field not found")
            raise RuntimeError("Timed out waiting for email input field") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"⚠️  Trying alternative method: {exc}")
            try:
                page.get_by_role("button", name="Continue", exact=True).click()
            except Exception as click_exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError("Could not submit email") from click_exc

    def _submit_code(self, page: Page, code: str) -> None:
        """Fill and submit verification code in headless flow."""
        try:
            code_input = page.locator('input[placeholder="Enter code"]')
            code_input.wait_for(state="visible", timeout=120000)
            code_input.fill(code)
            code_input.press("Enter")
            print("✅ Code submitted")
        except PlaywrightTimeoutError as exc:
            print("❌ Error: Verification code input not found")
            raise RuntimeError("Timed out waiting for verification code input") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"⚠️  Trying alternative method: {exc}")
            try:
                page.get_by_role("button", name="Continue", exact=True).click()
            except Exception as click_exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError("Could not submit verification code") from click_exc
    def close(self) -> None:
        """Close browser and cleanup."""
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

    def __enter__(self) -> "NotionLoginHelper":
        """Context manager entry."""
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def main():
    """Main entry point for the CLI script."""
    parser = argparse.ArgumentParser(
        description="Authenticate to Notion and save session state for automation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended for first-time setup)
  python notion_login.py

  # Headless mode (requires email + verification code)
  python notion_login.py --headless

  # Use Chromium instead of Firefox
  python notion_login.py --browser chromium

  # Save to custom location
  python notion_login.py --output ~/notion_session.json

  # Combine options
  python notion_login.py --headless --browser chromium --output /tmp/notion.json
        """
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no GUI, requires email + verification code input)",
    )
    parser.add_argument(
        "--browser",
        default="firefox",
        choices=["chromium", "firefox"],
        help="Browser engine to use (default: firefox)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Path to save session state (default: MCP-Universe/notion_state.json)",
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Notion URL to navigate to after login (default: login page)",
    )
    args = parser.parse_args()
    print("\n" + "🔐 Notion Login Helper".center(60, "="))
    print()
    try:
        helper = NotionLoginHelper(
            headless=args.headless,
            browser=args.browser,
            state_path=args.output,
            url=args.url,
        )
        with helper:
            print("\n" + "="*60)
            print("🎉 Login process completed successfully!")
            print("="*60)
            print(f"\n📄 Session state saved to: {helper.state_path}")
            print("\n💡 You can now use this session state for automated Notion tasks.")
            print()
    except KeyboardInterrupt:
        print("\n\n⚠️  Login cancelled by user")
        sys.exit(1)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"\n\n❌ Error during login: {exc}")
        traceback.print_exc()
        sys.exit(1)
if __name__ == "__main__":
    main()
