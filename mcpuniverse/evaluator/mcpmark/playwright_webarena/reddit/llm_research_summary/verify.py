"""Verification module for LLM research summary task."""
# pylint: disable=R0911,R0912,R0915,R1702
import asyncio
import sys
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
    Parse the Key|Value format from the submission body.
    Handles both pipe (|) and colon (:) separators for compatibility.
    """
    data = {}

    # Try to parse with pipe separator first (expected format)
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Remove markdown list prefix if present
        if line.startswith('- '):
            line = line[2:]
        elif line.startswith('* '):
            line = line[2:]

        # Try pipe separator first
        if '|' in line:
            parts = line.split('|', 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                data[key] = value
        # Fallback to colon separator for label.txt compatibility
        elif ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
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
    Verifies that the LLM analysis task has been completed correctly.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Navigate to the main page
            print("Navigating to forum...", file=sys.stderr)
            await page.goto(f"{BASE_URL}/", wait_until="networkidle")

            # Check if logged in as llm_analyst_2024
            user_button = page.locator('button:has-text("llm_analyst_2024")')
            if not await user_button.count():
                # Try to login
                print("Not logged in, attempting to login...", file=sys.stderr)

                await page.click('a:has-text("Log in")')
                await page.wait_for_load_state("networkidle")

                await page.fill('input[name="_username"]', "llm_analyst_2024")
                await page.fill('input[name="_password"]', "LLMExpert2024!")

                await page.click('button:has-text("Log in")')
                await page.wait_for_load_state("networkidle")

                user_button = page.locator('button:has-text("llm_analyst_2024")')
                if not await user_button.count():
                    print("Error: Login failed for llm_analyst_2024", file=sys.stderr)
                    return False, "Login failed for llm_analyst_2024"

                print("Successfully logged in as llm_analyst_2024", file=sys.stderr)
            else:
                print("Already logged in as llm_analyst_2024", file=sys.stderr)

            # Navigate to MachineLearning forum
            print("Navigating to MachineLearning forum...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/f/MachineLearning", wait_until="networkidle"
            )

            # Look for the submission with our specific title
            print(
                "Looking for submission 'LLM Research Summary: GPT Discussions Analysis [2024]'...",
                file=sys.stderr,
            )
            post_link = page.locator(
                'a:has-text("LLM Research Summary: GPT Discussions Analysis [2024]")'
            )

            if not await post_link.count():
                print(
                    "Error: Could not find submission with required title",
                    file=sys.stderr,
                )
                return False, "Could not find submission with required title"

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
                'div:has(> p:has-text("Total_LLM_Posts"))',
                'div:has-text("Total_LLM_Posts"):has-text("Deeplearning_Comments")',
            ]

            for selector in selectors:
                content_element = page.locator(selector)
                if await content_element.count():
                    post_content = await content_element.first.inner_text()
                    if "Total_LLM_Posts" in post_content:
                        print(
                            f"Found submission content using selector: {selector}",
                            file=sys.stderr,
                        )
                        break

            if not post_content or "Total_LLM_Posts" not in post_content:
                print(
                    "Error: Could not find submission body with required format",
                    file=sys.stderr,
                )
                return False, "Could not find submission body with required format"

            print("Submission content found, parsing data...", file=sys.stderr)
            print(f"Raw content: {post_content[:200]}...", file=sys.stderr)

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
                "Total_LLM_Posts",
                "Top1_Title",
                "Top1_Upvotes",
                "Top1_Date",
                "Top2_Title",
                "Top2_Upvotes",
                "Top2_Date",
                "Top3_Title",
                "Top3_Upvotes",
                "Top3_Date",
                "Deeplearning_MostDiscussed",
                "Deeplearning_Comments",
            ]

            missing_keys = []
            for key in required_keys:
                if key not in extracted_data:
                    missing_keys.append(key)

            if missing_keys:
                print(
                    f"Error: Missing required keys: {', '.join(missing_keys)}",
                    file=sys.stderr,
                )
                return False, f"Missing required keys: {', '.join(missing_keys)}"

            # Validate data format and content
            errors = []

            # Check Total_LLM_Posts is a number and matches expected
            try:
                total_posts = int(extracted_data["Total_LLM_Posts"])
                if "expected_data" in locals() and "Total_LLM_Posts" in expected_data:
                    expected_total = int(expected_data["Total_LLM_Posts"])
                    if total_posts != expected_total:
                        errors.append(
                            f"Total_LLM_Posts mismatch: got {total_posts}, expected {expected_total}"
                        )
                elif total_posts < 5:  # Based on exploration, should be at least 5
                    errors.append(f"Total_LLM_Posts seems too low: {total_posts}")
            except ValueError:
                errors.append(
                    f"Total_LLM_Posts must be a number, got: {extracted_data['Total_LLM_Posts']}"
                )

            # If we have expected data, compare against it
            if "expected_data" in locals():
                # Compare each field
                for key in required_keys:
                    if key in expected_data and key in extracted_data:
                        expected_val = normalize_text(expected_data[key])
                        actual_val = normalize_text(extracted_data[key])

                        # For numeric fields, compare as integers
                        if (
                            "Upvotes" in key
                            or "Comments" in key
                            or key == "Total_LLM_Posts"
                        ):
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

            # Verify upvotes are in descending order for top 3
            try:
                top1_votes = int(extracted_data["Top1_Upvotes"])
                top2_votes = int(extracted_data["Top2_Upvotes"])
                top3_votes = int(extracted_data["Top3_Upvotes"])

                if not top1_votes >= top2_votes >= top3_votes:
                    errors.append(
                        f"Top posts should be ordered by upvotes: {top1_votes} >= {top2_votes} >= {top3_votes}"
                    )
            except (ValueError, KeyError):
                pass  # Already reported above

            if errors:
                print(
                    "Error: Validation failed with the following issues:",
                    file=sys.stderr,
                )
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                return False, f"Validation failed with {len(errors)} issues"

            # All checks passed
            print("Success: LLM analysis task completed successfully.")
            print("- Account llm_analyst_2024 verified")
            print(
                "- Submission 'LLM Research Summary: GPT Discussions Analysis [2024]' found"
            )
            print(
                f"- Total LLM-related posts analyzed: {extracted_data['Total_LLM_Posts']}"
            )
            print("- Top 3 posts by upvotes identified and documented")
            print(
                f"- Deeplearning forum page 2 most discussed post: {extracted_data['Deeplearning_MostDiscussed']}"
            )
            print("- All data in correct Key: Value format with 12 lines")
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
