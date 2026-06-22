"""Verification module for buyitforlife research task."""
# pylint: disable=R0911,R0912,R0914,R0915,R1702,duplicate-code
import asyncio
import sys
import re
import os
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

BASE_URL = os.getenv("WEBARENA_BASE_URL", "http://localhost:9999").rstrip("/")


def parse_markdown_list_format(text):
    """
    Parse the markdown list format (- Key|Value) from the submission body.
    Also handles plain Key|Value format without the dash.
    """
    data = {}

    # Pattern to match lines like: - Key|Value or just Key|Value
    pattern = r'^(?:-\s*)?([^|]+)\|(.+)$'

    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if '|' in line:
            match = re.match(pattern, line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                data[key] = value

    return data


def normalize_text(text):
    """
    Normalize text for comparison by handling different quote styles and whitespace.
    """
    if not isinstance(text, str):
        return str(text)

    # Replace various quote styles with standard quotes
    text = text.replace(""", "'").replace(""", "'")
    text = text.replace('"', '"').replace('"', '"')

    # Normalize whitespace
    text = " ".join(text.split())

    return text.strip()


async def check_account_login(page):
    """
    Check if the account can be successfully logged in.
    Returns True if login successful, False otherwise.
    """
    try:
        # Navigate to main page
        await page.goto(f"{BASE_URL}/", wait_until="networkidle")

        # Check if already logged in
        user_button = page.locator('button[class*="UserButton"]')
        if await user_button.count():
            username = await user_button.inner_text()
            if username.lower() == "buyitforlife_researcher":
                print(f"Already logged in as {username}", file=sys.stderr)
                return True
            # Log out first
            await user_button.click()
            await page.click('a:has-text("Log out")')
            await page.wait_for_load_state("networkidle")

        # Try to login
        await page.click('a:has-text("Log in")')
        await page.wait_for_load_state("networkidle")

        await page.fill('input[name="_username"]', "buyitforlife_researcher")
        await page.fill('input[name="_password"]', "BIFL2024Research!")

        await page.click('button:has-text("Log in")')
        await page.wait_for_load_state("networkidle")

        # Check if login successful
        user_button = page.locator('button:has-text("buyitforlife_researcher")')
        if await user_button.count():
            print("Successfully logged in as buyitforlife_researcher", file=sys.stderr)
            return True
        print("Login failed for buyitforlife_researcher", file=sys.stderr)
        return False

    except RuntimeError as error:
        print(f"Error during login check: {str(error)}", file=sys.stderr)
        return False


async def check_submission_exists(page):
    """
    Check if the submission exists in the BuyItForLife forum with correct content.
    Returns (exists, content_data) tuple.
    """
    try:
        # Navigate to BuyItForLife forum
        await page.goto(f"{BASE_URL}/f/BuyItForLife", wait_until="networkidle")

        # Look for the post with correct title
        print("Looking for post 'Research Report for BuyItForLife'...", file=sys.stderr)
        post_locator = page.locator('a:has-text("Research Report for BuyItForLife")')

        if not await post_locator.count():
            print(
                "Error: Could not find post with title 'Research Report for BuyItForLife'",
                file=sys.stderr
            )
            return False, None

        # Click on the post to view its content
        await post_locator.first.click()
        await page.wait_for_load_state("networkidle")

        # Get the post content
        post_content = None
        selectors = [
            '.PostFullItem-body',
            '.Post-body',
            '.PostItem-body',
            '.item-RichText',
            '[class*="RichText"]',
            'div:has-text("Post1_Title")',
        ]

        for selector in selectors:
            post_content_element = page.locator(selector)
            if await post_content_element.count():
                # Get the text content, handling multiple elements if needed
                if await post_content_element.count() > 1:
                    for i in range(await post_content_element.count()):
                        text = await post_content_element.nth(i).inner_text()
                        if "Post1_Title" in text:
                            post_content = text
                            print(
                                f"Found post content using selector: {selector} (element {i})",
                                file=sys.stderr
                            )
                            break
                else:
                    post_content = await post_content_element.first.inner_text()
                    print(f"Found post content using selector: {selector}", file=sys.stderr)

                if post_content and "Post1_Title" in post_content:
                    break

        if not post_content:
            print("Error: Could not find post content element", file=sys.stderr)
            return False, None

        print("Post content found:", file=sys.stderr)
        print(
            post_content[:200] + "..." if len(post_content) > 200 else post_content,
            file=sys.stderr
        )

        # Parse the markdown list format
        extracted_data = parse_markdown_list_format(post_content)
        print(f"Extracted data: {extracted_data}", file=sys.stderr)

        return True, extracted_data

    except RuntimeError as error:
        print(f"Error checking submission: {str(error)}", file=sys.stderr)
        return False, None


async def verify() -> tuple[bool, str]:
    """
    Verifies that the BuyItForLife research task has been completed correctly.
    Checks:
    1. Account creation (can login with credentials)
    2. Submission exists with correct title
    3. Submission content matches expected format and values
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Step 1: Check account creation
            print("=== Step 1: Checking account creation ===", file=sys.stderr)
            account_ok = await check_account_login(page)
            if not account_ok:
                print(
                    "Error: Account 'buyitforlife_researcher' cannot be logged in",
                    file=sys.stderr
                )
                return False, "Account 'buyitforlife_researcher' cannot be logged in"

            # Step 2: Check submission exists and get content
            print("\n=== Step 2: Checking submission ===", file=sys.stderr)
            submission_exists, extracted_data = await check_submission_exists(page)

            if not submission_exists:
                print("Error: Submission not found in BuyItForLife forum", file=sys.stderr)
                return False, "Submission not found in BuyItForLife forum"

            if not extracted_data:
                print("Error: Could not extract data from submission", file=sys.stderr)
                return False, "Could not extract data from submission"

            # Step 3: Load expected data from label.txt
            print("\n=== Step 3: Validating submission content ===", file=sys.stderr)
            label_path = Path(__file__).parent / "label.txt"
            if not label_path.exists():
                print("Error: label.txt not found", file=sys.stderr)
                return False, "label.txt not found"

            with open(label_path, "r", encoding='utf-8') as file_handle:
                expected_text = file_handle.read().strip()
            expected_data = parse_markdown_list_format(expected_text)
            print(f"Expected data from label.txt: {expected_data}", file=sys.stderr)

            # Verify all required keys are present
            required_keys = [
                "Post1_Title",
                "Post1_Upvotes",
                "Post1_Comments",
                "Post2_Title",
                "Post2_Upvotes",
                "Post2_Comments",
                "Post3_Title",
                "Post3_Upvotes",
                "Post3_Comments",
                "TopComment_Text",
                "TopComment_Username",
                "Post1_Author",
                "Post2_Author",
                "Post3_Author",
            ]

            missing_keys = []
            for key in required_keys:
                if key not in extracted_data:
                    missing_keys.append(key)

            if missing_keys:
                print(f"Error: Missing required keys: {', '.join(missing_keys)}", file=sys.stderr)
                return False, f"Missing required keys: {', '.join(missing_keys)}"

            # Compare each field with expected values
            errors = []
            for key in required_keys:
                if key in expected_data and key in extracted_data:
                    expected_val = normalize_text(expected_data[key])
                    actual_val = normalize_text(extracted_data[key])

                    # For numeric fields, compare as integers
                    if "Upvotes" in key or "Comments" in key:
                        try:
                            expected_int = int(expected_val)
                            actual_int = int(actual_val)
                            if expected_int != actual_int:
                                errors.append(
                                    f"{key} mismatch: got {actual_int}, expected {expected_int}"
                                )
                        except ValueError:
                            errors.append(f"{key} should be numeric: got '{actual_val}'")
                    else:
                        # For text fields, special handling for usernames with underscores
                        if "Author" in key or key == "TopComment_Username":
                            expected_core = expected_val.strip('_')
                            actual_core = actual_val.strip('_')
                            if expected_core != actual_core:
                                errors.append(
                                    f"{key} mismatch: got '{actual_val}', expected '{expected_val}'"
                                )
                        else:
                            if expected_val != actual_val:
                                errors.append(
                                    f"{key} mismatch: got '{actual_val}', expected '{expected_val}'"
                                )

            # Verify upvotes are in descending order
            try:
                post1_votes = int(extracted_data["Post1_Upvotes"])
                post2_votes = int(extracted_data["Post2_Upvotes"])
                post3_votes = int(extracted_data["Post3_Upvotes"])

                if not post1_votes >= post2_votes >= post3_votes:
                    errors.append(
                        f"Posts should be ordered by upvotes: "
                        f"{post1_votes} >= {post2_votes} >= {post3_votes}"
                    )
            except (ValueError, KeyError):
                pass  # Already reported above

            if errors:
                print("Error: Validation failed with the following issues:", file=sys.stderr)
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                return False, f"Validation failed with {len(errors)} issues"

            # All checks passed
            print("\n=== SUCCESS ===", file=sys.stderr)
            print("✓ Account 'buyitforlife_researcher' created and can login", file=sys.stderr)
            print(
                "✓ Submission 'Research Report for BuyItForLife' found in correct forum",
                file=sys.stderr
            )
            print("✓ All 14 required fields present and correct", file=sys.stderr)
            print("✓ Data matches expected values from label.txt", file=sys.stderr)
            print("✓ Posts ordered by upvotes (descending)", file=sys.stderr)
            return True, ""

        except PlaywrightTimeoutError as timeout_error:
            print(f"Error: Timeout occurred - {str(timeout_error)}", file=sys.stderr)
            return False, f"Timeout occurred - {str(timeout_error)}"
        except RuntimeError as error:
            print(f"Error: Unexpected error - {str(error)}", file=sys.stderr)
            return False, f"Unexpected error - {str(error)}"
        finally:
            await browser.close()


def main():
    """
    Executes the verification process and exits with a status code.
    """
    success, _ = asyncio.run(verify())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
