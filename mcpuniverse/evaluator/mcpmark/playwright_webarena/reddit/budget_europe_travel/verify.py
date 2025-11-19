"""Verification module for budget Europe travel task."""
# pylint: disable=R0911,R0912,R0914,R0915,R1702,W0702,line-too-long,duplicate-code
import asyncio
import re
import sys
import os
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = os.getenv("WEBARENA_BASE_URL", "http://localhost:9999").rstrip("/")

def normalize_text(text):
    """
    Normalize text for comparison by handling different quote styles and whitespace.
    """
    if not isinstance(text, str):
        return str(text)

    # Replace various quote styles with standard quotes
    text = text.replace('\'', "'").replace('\'', "'")
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace('&amp;', '&')

    # Normalize whitespace
    text = ' '.join(text.split())

    return text.strip()

async def verify() -> tuple[bool, str]:
    """
    Verifies that the budget Europe travel resource task has been completed correctly.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()


        try:

            # 1. Check if account can login with correct credentials
            print("="*60)
            print("Step 1: Verifying account login with credentials...", file=sys.stderr)
            print("="*60)
            await page.goto(f"{BASE_URL}/", wait_until='networkidle')

            # First logout if already logged in
            user_button = page.locator('button:has-text("EuroTravelPlanner")')
            if await user_button.count():
                print("Already logged in, logging out first...", file=sys.stderr)
                await user_button.click()
                logout_link = page.locator('a:has-text("Log out")')
                if await logout_link.count():
                    await logout_link.click()
                    await page.wait_for_load_state('networkidle')

            # Now try to login with the specified credentials
            print(
                "Attempting to login with username 'EuroTravelPlanner' "
                "and password 'SecureTravel2024!'...",
                file=sys.stderr
            )

            # Navigate to login page
            login_link = page.locator('a:has-text("Log in")')
            if await login_link.count():
                await login_link.click()
                await page.wait_for_load_state('networkidle')
            else:
                print("❌ ERROR: Cannot find login link", file=sys.stderr)
                return False, "Cannot find login link"

            # Fill login form with exact credentials
            await page.fill('input[name="_username"]', 'EuroTravelPlanner')
            await page.fill('input[name="_password"]', 'SecureTravel2024!')

            # Submit login
            login_button = page.locator('button[type="submit"]:has-text("Log in")')
            if not await login_button.count():
                login_button = page.locator('button:has-text("Log in")')

            await login_button.click()
            await page.wait_for_load_state('networkidle')

            # Verify login success
            user_button = page.locator('button:has-text("EuroTravelPlanner")')
            if not await user_button.count():
                print(
                    "❌ ERROR: Login failed with username 'EuroTravelPlanner' "
                    "and password 'SecureTravel2024!'",
                    file=sys.stderr
                )
                return False, (
                    "Login failed with username 'EuroTravelPlanner' "
                    "and password 'SecureTravel2024!'"
                )
            print("✓ Account login successful with correct credentials", file=sys.stderr)


            # 2. Check if forum exists and has correct properties
            print("\n" + "="*60)
            print("Step 2: Checking forum existence and properties...", file=sys.stderr)
            print("="*60)

            # Check if forum exists at /f/BudgetEuropeTravel
            await page.goto(f"{BASE_URL}/f/BudgetEuropeTravel", wait_until='networkidle')

            # Check if we get 404 or the forum exists
            page_content = await page.content()
            page_title = await page.title()


            if "404" in page_title or "not found" in page_title.lower() or "Page not found" in page_content:
                print("❌ ERROR: Forum /f/BudgetEuropeTravel does not exist (404)", file=sys.stderr)
                return False, "Forum /f/BudgetEuropeTravel does not exist (404)"
            print("✓ Forum /f/BudgetEuropeTravel exists", file=sys.stderr)

            # Navigate to edit page to check properties
            await page.goto(f"{BASE_URL}/f/BudgetEuropeTravel/edit", wait_until='networkidle')

            # Check if we can access edit page
            edit_page_content = await page.content()
            edit_page_title = await page.title()

            if ("404" in edit_page_title or "not found" in edit_page_title.lower() or
                    "Page not found" in edit_page_content):
                print(
                    "❌ ERROR: Cannot access forum edit page at /f/BudgetEuropeTravel/edit",
                    file=sys.stderr
                )
                return False, "Cannot access forum edit page at /f/BudgetEuropeTravel/edit"
            print("✓ Forum edit page accessible", file=sys.stderr)

            # Check forum title
            title_input = page.locator('input[name*="title"], input#forum_title')
            if await title_input.count():
                title_value = await title_input.input_value()
                if title_value != "Budget Travel Europe":
                    print(
                        f"❌ ERROR: Forum title is '{title_value}', "
                        f"expected 'Budget Travel Europe'",
                        file=sys.stderr
                    )
                    return False, (
                        f"Forum title is '{title_value}', "
                        f"expected 'Budget Travel Europe'"
                    )
                print("✓ Forum title correct: 'Budget Travel Europe'", file=sys.stderr)
            else:
                print("❌ ERROR: Cannot find forum title field", file=sys.stderr)
                return False, "Cannot find forum title field"

            # Check forum description
            desc_input = page.locator('textarea[name*="description"], input[name*="description"]')
            if await desc_input.count():
                desc_value = await desc_input.input_value()
                expected_desc = "Community for sharing money-saving tips for European travel"
                if desc_value != expected_desc:
                    print(
                        f"❌ ERROR: Forum description is '{desc_value}', "
                        f"expected '{expected_desc}'",
                        file=sys.stderr
                    )
                    return False, (
                        f"Forum description is '{desc_value}', "
                        f"expected '{expected_desc}'"
                    )
                print("✓ Forum description correct", file=sys.stderr)
            else:
                print("❌ ERROR: Cannot find forum description field", file=sys.stderr)
                return False, "Cannot find forum description field"

            # Check sidebar content
            sidebar_input = page.locator('textarea[name*="sidebar"]')
            if await sidebar_input.count():
                sidebar_value = await sidebar_input.input_value()
                expected_sidebar = "Share your best European travel deals and budget tips here!"
                if sidebar_value != expected_sidebar:
                    print(
                        f"❌ ERROR: Forum sidebar is '{sidebar_value}', "
                        f"expected '{expected_sidebar}'",
                        file=sys.stderr
                    )
                    return False, (
                        f"Forum sidebar is '{sidebar_value}', "
                        f"expected '{expected_sidebar}'"
                    )
                print("✓ Forum sidebar correct", file=sys.stderr)
            else:
                print("❌ ERROR: Cannot find forum sidebar field", file=sys.stderr)
                return False, "Cannot find forum sidebar field"


            # 3. Check wiki page existence and content
            print("\n" + "="*60)
            print("Step 3: Checking wiki page existence and content...", file=sys.stderr)
            print("="*60)

            # Try the wiki URL with /wiki/ path
            await page.goto(f"{BASE_URL}/wiki/europe-travel-budget-guide", wait_until='networkidle')

            wiki_page_content = await page.content()
            wiki_page_title = await page.title()

            if ("404" in wiki_page_title or "not found" in wiki_page_title.lower() or
                    "Page not found" in wiki_page_content):
                print(
                    "❌ ERROR: Wiki page does not exist at /wiki/europe-travel-budget-guide",
                    file=sys.stderr
                )
                return False, "Wiki page does not exist at /wiki/europe-travel-budget-guide"
            print("✓ Wiki page exists at /wiki/europe-travel-budget-guide", file=sys.stderr)

            # Check wiki title
            wiki_title_found = False
            expected_wiki_title = "Complete Budget Travel Guide for Europe 2024"

            # Try multiple selectors for wiki title
            wiki_title_selectors = [
                f'h1:has-text("{expected_wiki_title}")',
                f'h1:text-is("{expected_wiki_title}")',
                'h1'
            ]

            for selector in wiki_title_selectors:
                wiki_title_elem = page.locator(selector)
                if await wiki_title_elem.count():
                    title_text = await wiki_title_elem.first.text_content()
                    if expected_wiki_title in title_text:
                        wiki_title_found = True
                        break

            if not wiki_title_found:
                print(f"❌ ERROR: Wiki title '{expected_wiki_title}' not found", file=sys.stderr)
                return False, f"Wiki title '{expected_wiki_title}' not found"
            print(f"✓ Wiki title correct: '{expected_wiki_title}'", file=sys.stderr)

            # Check for required content in wiki
            required_wiki_content = "Eurail passes and budget airlines"
            if required_wiki_content not in wiki_page_content:
                print(f"❌ ERROR: Wiki content must contain '{required_wiki_content}'", file=sys.stderr)
                return False, f"Wiki content must contain '{required_wiki_content}'"
            print(f"✓ Wiki content contains required text: '{required_wiki_content}'", file=sys.stderr)

            # 4. Check for post in the forum
            print("\n" + "="*60)
            print("Step 4: Checking for post in forum...", file=sys.stderr)
            print("="*60)

            await page.goto(f"{BASE_URL}/f/BudgetEuropeTravel", wait_until='networkidle')

            expected_post_title = "My 14-day Europe trip for under 1000 - Complete itinerary"
            post_link = page.locator(f'a:has-text("{expected_post_title}")')

            if not await post_link.count():
                print(f"❌ ERROR: Post with title '{expected_post_title}' not found in forum", file=sys.stderr)
                return False, f"Post with title '{expected_post_title}' not found in forum"
            print(f"✓ Post found with title: '{expected_post_title}'", file=sys.stderr)

            # Click on the post to check its content
            await post_link.first.click()
            await page.wait_for_load_state('networkidle')

            # Check if post contains required text
            post_page_content = await page.content()
            required_post_content = "budget guide wiki"

            if required_post_content not in post_page_content:
                print(f"❌ ERROR: Post body must contain '{required_post_content}'", file=sys.stderr)
                return False, f"Post body must contain '{required_post_content}'"
            print(f"✓ Post content contains required text: '{required_post_content}'", file=sys.stderr)

            # 5. Check upvote on search result
            print("\n" + "="*60)
            print("Step 5: Checking upvote on search result...", file=sys.stderr)
            print("="*60)

            # Navigate to search results for "travel insurance Europe"
            await page.goto(f"{BASE_URL}/search?q=travel+insurance+Europe", wait_until='networkidle')


            # Check if we're on search results page
            if "/search" not in page.url:
                print("❌ ERROR: Not on search results page", file=sys.stderr)
                return False, "Not on search results page"
            print("✓ On search results page for 'travel insurance Europe'", file=sys.stderr)

            # Check for upvoted posts
            upvote_found = False

            # Method 1: Check for "Retract upvote" button (indicates user has upvoted)
            retract_buttons = page.locator('button:has-text("Retract upvote")')
            if await retract_buttons.count() > 0:
                print("✓ Found upvoted post (Retract upvote button present)", file=sys.stderr)
                upvote_found = True

            # Method 2: Check for posts with upvote count >= 1
            if not upvote_found:
                # Look for vote counts
                vote_elements = page.locator('div.vote, span.vote-count, [class*="vote"]')

                for i in range(await vote_elements.count()):
                    vote_elem = vote_elements.nth(i)
                    vote_text = await vote_elem.text_content()
                    try:
                        # Extract number from vote text
                        numbers = re.findall(r'\d+', vote_text)
                        if numbers:
                            vote_count = int(numbers[0])
                            if vote_count >= 1:
                                print(f"✓ Found post with {vote_count} upvote(s)", file=sys.stderr)
                                upvote_found = True
                                break
                    except:
                        continue

                if not upvote_found:
                    print("❌ ERROR: No upvoted posts found in search results", file=sys.stderr)
                    return False, "No upvoted posts found in search results"

            # 6. Check user settings
            print("\n" + "="*60)
            print("Step 6: Checking user settings...", file=sys.stderr)
            print("="*60)


            await page.goto(f"{BASE_URL}/user/EuroTravelPlanner/preferences", wait_until='networkidle')

            # Check timezone setting
            timezone_select = page.locator('select[name*="timezone"], select#timezone')

            if await timezone_select.count():
                selected_value = await timezone_select.input_value()

                if selected_value == "Europe/Amsterdam":
                    print("✓ Timezone correctly set to 'Europe/Amsterdam'", file=sys.stderr)
                else:
                    # Check selected option text
                    selected_option = timezone_select.locator('option[selected]')
                    if await selected_option.count():
                        option_text = await selected_option.text_content()
                        if "Amsterdam" in option_text:
                            print("✓ Timezone correctly set to Europe/Amsterdam", file=sys.stderr)
                        else:
                            print(
                                f"❌ ERROR: Timezone is set to '{option_text}', "
                                f"expected 'Europe/Amsterdam'",
                                file=sys.stderr
                            )
                            return False, f"Timezone is set to '{option_text}', expected 'Europe/Amsterdam'"
                    else:
                        print(f"❌ ERROR: Timezone is '{selected_value}', expected 'Europe/Amsterdam'", file=sys.stderr)
                        return False, f"Timezone is '{selected_value}', expected 'Europe/Amsterdam'"
            else:
                print("❌ ERROR: Cannot find timezone selector", file=sys.stderr)
                return False, "Cannot find timezone selector"

            # Check "Notify on reply" setting
            notify_correct = False

            # Try multiple selectors for the checkbox
            notify_selectors = [
                'input[type="checkbox"]:near(:text("Notify on reply"))',
                'label:has-text("Notify on reply") input[type="checkbox"]',
                'input[type="checkbox"][name*="notify"]',
                'input[type="checkbox"][id*="notify"]'
            ]

            for selector in notify_selectors:
                notify_checkbox = page.locator(selector)
                if await notify_checkbox.count():
                    is_checked = await notify_checkbox.first.is_checked()
                    if is_checked:
                        print("✓ 'Notify on reply' is enabled (checked)", file=sys.stderr)
                        notify_correct = True
                    else:
                        print("❌ ERROR: 'Notify on reply' is not enabled (unchecked)", file=sys.stderr)
                        return False, "'Notify on reply' is not enabled (unchecked)"
                    break

            if not notify_correct:
                print("❌ ERROR: Cannot verify 'Notify on reply' setting", file=sys.stderr)
                return False, "Cannot verify 'Notify on reply' setting"

            # Final summary
            print("\n" + "="*60)
            print("✅ SUCCESS: All verification checks passed!", file=sys.stderr)
            print("="*60)
            return True, ""

        except PlaywrightTimeoutError as timeout_error:
            print(f"❌ ERROR: Timeout occurred - {str(timeout_error)}", file=sys.stderr)
            return False, f"Timeout occurred - {str(timeout_error)}"
        except RuntimeError as error:
            print(f"❌ ERROR: Unexpected error - {str(error)}", file=sys.stderr)
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
