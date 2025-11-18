"""Verification module for AI data analyst task."""
# pylint: disable=R0911,R0912,R0915,R1702
import asyncio
import sys
import re
import os
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# 从环境变量读取 base_url，默认回退到本地
BASE_URL = os.getenv("WEBARENA_BASE_URL", "http://localhost:9999").rstrip("/")


def parse_key_value_format(text):
    """
    Parse the Key|Value format from the submission body using regex.
    Works with markdown format using pipe separators, with or without list markers.
    """
    data = {}

    # Define patterns for each field using pipe separator
    # Optional list markers (-, •, *) at the beginning
    patterns = {
        "Deeplearning_Post_Count": r"(?:[-•*]\s*)?Deeplearning_Post_Count\s*\|\s*(\d+)",
        "ChatGPT_Tool_Vote_Count": r"(?:[-•*]\s*)?ChatGPT_Tool_Vote_Count\s*\|\s*(\d+)",
        "Transformer_Third_Result": r"(?:[-•*]\s*)?Transformer_Third_Result\s*\|\s*(.+?)(?=\n|$)",
        "Page2_Top_Post_Title": r"(?:[-•*]\s*)?Page2_Top_Post_Title\s*\|\s*(.+?)(?=\n|$)",
        "Page2_Top_Post_Votes": r"(?:[-•*]\s*)?Page2_Top_Post_Votes\s*\|\s*(\d+)",
        "Page2_Last_Comment_Username": r"(?:[-•*]\s*)?Page2_Last_Comment_Username\s*\|\s*(.+?)(?=\n|$)",
        "Page2_Last_Comment_Text": r"(?:[-•*]\s*)?Page2_Last_Comment_Text\s*\|\s*(.+?)(?=\n|$)",
    }

    # Extract each field using regex
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            # For text fields, clean up newlines and extra spaces
            value = match.group(1).strip()
            if key not in [
                "Deeplearning_Post_Count",
                "ChatGPT_Tool_Vote_Count",
                "Page2_Top_Post_Votes",
            ]:
                # Replace newlines with spaces and normalize whitespace
                value = " ".join(value.split())
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


async def verify() -> tuple[bool, str]:
    """
    Verifies that the ML extraction task has been completed correctly by checking the forum post.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Navigate to the main page
            print("Navigating to forum...", file=sys.stderr)
            await page.goto(f"{BASE_URL}/", wait_until="networkidle")

            # Step 1: Check if account was created correctly by trying to login
            print("Step 1: Verifying account creation...", file=sys.stderr)
            user_button = page.locator('button:has-text("AIDataAnalyst2025")')
            if not await user_button.count():
                # Try to login
                print("Attempting to login with AIDataAnalyst2025...", file=sys.stderr)

                # Click login link
                await page.click('a:has-text("Log in")')
                await page.wait_for_load_state("networkidle")

                # Fill login form
                await page.fill('input[name="_username"]', "AIDataAnalyst2025")
                await page.fill('input[name="_password"]', "SecurePass123!")

                # Submit login form
                await page.click('button:has-text("Log in")')
                await page.wait_for_load_state("networkidle")

                # Check if login successful
                user_button = page.locator('button:has-text("AIDataAnalyst2025")')
                if not await user_button.count():
                    print(
                        "FAILED: Account AIDataAnalyst2025 with password SecurePass123! "
                        "cannot be logged in",
                        file=sys.stderr
                    )
                    print("This means the account was not created correctly", file=sys.stderr)
                    return False, (
                        "Account AIDataAnalyst2025 with password SecurePass123! "
                        "cannot be logged in"
                    )

                print("PASSED: Successfully logged in as AIDataAnalyst2025", file=sys.stderr)
            else:
                print("PASSED: Already logged in as AIDataAnalyst2025", file=sys.stderr)

            # Step 2: Check if submission was created correctly in MachineLearning forum
            print("\nStep 2: Verifying submission creation...", file=sys.stderr)
            print("Navigating to MachineLearning forum...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/f/MachineLearning", wait_until="networkidle"
            )

            # Look for the post with title "MachineLearning_Extraction"
            print(
                "Looking for submission with title 'MachineLearning_Extraction'...",
                file=sys.stderr,
            )
            post_link = page.locator('a:has-text("MachineLearning_Extraction")')

            if not await post_link.count():
                print(
                    "FAILED: Could not find submission with title 'MachineLearning_Extraction' "
                    "in MachineLearning forum",
                    file=sys.stderr,
                )
                return False, (
                    "Could not find submission with title 'MachineLearning_Extraction' "
                    "in MachineLearning forum"
                )

            print("PASSED: Found submission 'MachineLearning_Extraction' in MachineLearning forum", file=sys.stderr)

            # Step 3: Check submission content matches expected values
            print("\nStep 3: Verifying submission content...", file=sys.stderr)

            # Click on the submission to view its content
            await post_link.first.click()
            await page.wait_for_load_state("networkidle")

            # Extract the submission body content
            # Try multiple possible selectors for the post body
            post_content = None
            selectors = [
                ".submission__body",
                ".post-body",
                ".RichText",
                '[class*="RichText"]',
                'div:has(> p:has-text("Deeplearning_Post_Count"))',
                'div:has-text("Deeplearning_Post_Count"):has-text("Page2_Last_Comment_Text")',
            ]

            for selector in selectors:
                content_element = page.locator(selector)
                if await content_element.count():
                    post_content = await content_element.first.inner_text()
                    if "Deeplearning_Post_Count" in post_content:
                        print(
                            f"Found submission content using selector: {selector}",
                            file=sys.stderr,
                        )
                        break

            if not post_content or "Deeplearning_Post_Count" not in post_content:
                print(
                    "FAILED: Could not find submission body with required format",
                    file=sys.stderr,
                )
                print(
                    "Expected body to contain 'Deeplearning_Post_Count' in pipe-separated format",
                    file=sys.stderr,
                )
                return False, "Could not find submission body with required format"

            print("Found submission body content", file=sys.stderr)
            print(f"Raw content preview: {post_content[:200]}...", file=sys.stderr)

            # Parse the Key: Value format
            extracted_data = parse_key_value_format(post_content)
            print(f"Extracted data: {extracted_data}", file=sys.stderr)

            # Load expected values from label.txt
            expected_data = {}
            label_path = Path(__file__).parent / "label.txt"
            if label_path.exists():
                with open(label_path, "r", encoding='utf-8') as file_handle:
                    expected_text = file_handle.read().strip()
                expected_data = parse_key_value_format(expected_text)
                print("Loaded expected values from label.txt", file=sys.stderr)

            # Verify all required keys are present
            required_keys = [
                "Deeplearning_Post_Count",
                "ChatGPT_Tool_Vote_Count",
                "Transformer_Third_Result",
                "Page2_Top_Post_Title",
                "Page2_Top_Post_Votes",
                "Page2_Last_Comment_Username",
                "Page2_Last_Comment_Text",
            ]

            missing_keys = []
            for key in required_keys:
                if key not in extracted_data:
                    missing_keys.append(key)

            if missing_keys:
                print(
                    f"FAILED: Missing required keys in submission: {', '.join(missing_keys)}",
                    file=sys.stderr,
                )
                print(
                    "Expected all 7 fields to be present in pipe-separated format",
                    file=sys.stderr,
                )
                return False, f"Missing required keys in submission: {', '.join(missing_keys)}"

            # Validate data format and content
            errors = []

            # Check numeric fields
            try:
                post_count = int(extracted_data["Deeplearning_Post_Count"])
                if (
                    "expected_data" in locals()
                    and "Deeplearning_Post_Count" in expected_data
                ):
                    expected_count = int(expected_data["Deeplearning_Post_Count"])
                    if post_count != expected_count:
                        errors.append(
                            f"Deeplearning_Post_Count mismatch: got {post_count}, expected {expected_count}"
                        )
            except ValueError:
                errors.append(
                    f"Deeplearning_Post_Count must be a number, got: {extracted_data['Deeplearning_Post_Count']}"
                )

            # If we have expected data, compare against it
            if "expected_data" in locals():
                # Compare each field
                for key in required_keys:
                    if key in expected_data and key in extracted_data:
                        expected_val = normalize_text(expected_data[key])
                        actual_val = normalize_text(extracted_data[key])

                        # For numeric fields, compare as integers
                        if key in [
                            "Deeplearning_Post_Count",
                            "ChatGPT_Tool_Vote_Count",
                            "Page2_Top_Post_Votes",
                        ]:
                            try:
                                expected_int = int(expected_val)
                                actual_int = int(actual_val)
                                if expected_int != actual_int:
                                    errors.append(
                                        f"{key} mismatch: got {actual_int}, expected {expected_int}"
                                    )
                            except ValueError:
                                errors.append(
                                    f"{key} should be numeric: got '{actual_val}'"
                                )
                        else:
                            # For text fields, compare normalized text
                            if expected_val != actual_val:
                                errors.append(
                                    f"{key} mismatch: got '{actual_val}', expected '{expected_val}'"
                                )

            else:
                # If no expected data, just do basic validation
                for key in required_keys:
                    if key not in extracted_data:
                        errors.append(f"Missing required key: {key}")
                    elif (
                        not extracted_data[key] or extracted_data[key] == "[FILL_VALUE]"
                    ):
                        errors.append(f"{key} was not filled in")

            if errors:
                print(
                    "FAILED: Content validation failed with the following issues:",
                    file=sys.stderr,
                )
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                print("\nExpected values from label.txt:", file=sys.stderr)
                if "expected_data" in locals():
                    for key in required_keys:
                        if key in expected_data:
                            print(f"  {key}: {expected_data[key]}", file=sys.stderr)
                return False, f"Content validation failed with {len(errors)} issues"

            # All checks passed
            print("\n=== VERIFICATION SUCCESSFUL ===")
            print("✓ Step 1: Account AIDataAnalyst2025 can login with password SecurePass123!")
            print("✓ Step 2: Submission 'MachineLearning_Extraction' found in MachineLearning forum")
            print("✓ Step 3: All submission content matches expected values:")
            print(f"  - Deeplearning_Post_Count: {extracted_data['Deeplearning_Post_Count']}")
            print(f"  - ChatGPT_Tool_Vote_Count: {extracted_data['ChatGPT_Tool_Vote_Count']}")
            print(f"  - Transformer_Third_Result: {extracted_data['Transformer_Third_Result']}")
            print(f"  - Page2_Top_Post_Title: {extracted_data['Page2_Top_Post_Title']}")
            print(f"  - Page2_Top_Post_Votes: {extracted_data['Page2_Top_Post_Votes']}")
            print(f"  - Page2_Last_Comment_Username: {extracted_data['Page2_Last_Comment_Username']}")
            print(f"  - Page2_Last_Comment_Text: {extracted_data['Page2_Last_Comment_Text']}")
            print("✓ All data in correct pipe-separated markdown format")
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
