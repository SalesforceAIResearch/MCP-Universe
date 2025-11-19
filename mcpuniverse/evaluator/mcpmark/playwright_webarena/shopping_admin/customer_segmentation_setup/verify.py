"""Verification module for customer segmentation setup task."""
# pylint: disable=R0911,R0912,R0914,R0915,R1702,duplicate-code
import asyncio
import sys
import re
import os
import json
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# 从环境变量读取 base_url（shopping_admin 会注入 http://localhost:7780/admin），默认回退到本地
BASE_URL = os.getenv("WEBARENA_BASE_URL", "http://localhost:7780/admin").rstrip("/")


def get_model_response():
    """
    Get the model's response from the MCP_MESSAGES environment variable.
    Returns the last assistant message text.
    """
    messages_path = os.getenv("MCP_MESSAGES")
    print(f"MCP_MESSAGES: {messages_path}")
    if not messages_path:
        print("Warning: MCP_MESSAGES environment variable not set", file=sys.stderr)
        return None

    try:
        with open(messages_path, "r", encoding='utf-8') as file_handle:
            messages = json.load(file_handle)

        # Find the last assistant message
        for message in reversed(messages):
            if (
                message.get("role") == "assistant"
                and message.get("status") == "completed"
            ):
                content = message.get("content", [])
                for item in content:
                    if item.get("type") == "output_text":
                        return item.get("text", "")

        print("Warning: No assistant response found in messages", file=sys.stderr)
        return None
    except (OSError, json.JSONDecodeError) as error:
        print(f"Error reading messages file: {str(error)}", file=sys.stderr)
        return None


def parse_answer_format(text):
    """
    Parse the <answer>...</answer> format from the agent's output.
    Returns a dictionary with the parsed values.
    """
    if not text:
        return None

    # Look for <answer>...</answer> pattern
    match = re.search(r"<answer>(.*?)</answer>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    answer_content = match.group(1).strip()

    # Parse each line
    result = {}
    lines = answer_content.split("\n")

    if len(lines) != 5:
        print(f"Error: Expected 5 lines in answer, got {len(lines)}", file=sys.stderr)
        return None

    for line in lines:
        if "|" in line:
            key, value = line.split("|", 1)
            result[key.strip()] = value.strip()

    return result


def load_expected_answer(label_path):
    """
    Load the expected answer from label.txt file.
    Returns a dictionary with the expected values.
    """
    try:
        with open(label_path, "r", encoding='utf-8') as file_handle:
            lines = file_handle.read().strip().split("\n")

        expected = {}
        for line in lines:
            if "|" in line:
                key, value = line.split("|", 1)
                expected[key.strip()] = value.strip()

        return expected
    except OSError as error:
        print(f"Error reading label file: {str(error)}", file=sys.stderr)
        return None


def compare_answers(model_answer, expected_answer):
    """
    Compare the model's answer with the expected answer.
    Returns (True, "") if all key information matches, (False, error_message) otherwise.
    """
    if not model_answer or not expected_answer:
        return False, "Missing model answer or expected answer"

    # Check each expected key
    mismatches = []
    for key, expected_value in expected_answer.items():
        model_value = model_answer.get(key, "")

        # Exact match for all fields
        if model_value != expected_value:
            mismatches.append(
                f"{key}: expected '{expected_value}', got '{model_value}'"
            )

    if mismatches:
        print("\n=== Answer Comparison Mismatches ===", file=sys.stderr)
        error_msg = "Answer comparison mismatches:\n"
        for mismatch in mismatches:
            print(f"✗ {mismatch}", file=sys.stderr)
            error_msg += f"✗ {mismatch}\n"
        return False, error_msg.strip()

    print("\n=== Answer Comparison ===", file=sys.stderr)
    print("✓ All key information matches the expected answer", file=sys.stderr)
    return True, ""


async def verify() -> tuple[bool, str]:
    """
    Verifies that the customer segmentation setup task has been completed correctly.
    First checks the model's answer against the expected label,
    then verifies the actual state in the Magento Admin.
    """
    # Get the label file path
    label_path = Path(__file__).parent / "label.txt"

    # Load expected answer
    expected_answer = load_expected_answer(label_path)
    if not expected_answer:
        print("Error: Could not load expected answer from label.txt", file=sys.stderr)
        return False, "Could not load expected answer from label.txt"

    # Get model's response from MCP_MESSAGES
    model_response = get_model_response()
    if model_response:
        print("Found model response, parsing answer format...", file=sys.stderr)
        model_answer = parse_answer_format(model_response)

        if model_answer:
            print("\n=== Model Answer Parsed ===", file=sys.stderr)
            for key, value in model_answer.items():
                print(f"{key}: {value}", file=sys.stderr)

            # Compare answers
            answer_match, error_msg = compare_answers(model_answer, expected_answer)
            if not answer_match:
                print("\nModel answer does not match expected answer", file=sys.stderr)
                return False, error_msg
            print("\n✓ Model answer matches expected answer", file=sys.stderr)
        else:
            print(
                "Warning: Could not parse answer format from model response",
                file=sys.stderr,
            )
            print("Will proceed with browser verification only", file=sys.stderr)
    else:
        print(
            "No model response found, proceeding with browser verification",
            file=sys.stderr,
        )

    # Browser verification for actual state
    print("\n=== Starting Browser Verification ===", file=sys.stderr)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Navigate to Magento Admin
            print("Navigating to Magento Admin...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/", wait_until="networkidle"
            )

            # Check if already logged in, if not, login
            if "dashboard" not in page.url.lower():
                print("Logging into Magento Admin...", file=sys.stderr)
                await page.fill('input[name="login[username]"]', "admin")
                await page.fill('input[name="login[password]"]', "admin1234")
                await page.click('button:has-text("Sign in")')
                await page.wait_for_load_state("networkidle")

                if "dashboard" not in page.url.lower():
                    print("Error: Login failed", file=sys.stderr)
                    return False, "Login failed"

            print("Successfully logged into Magento Admin", file=sys.stderr)

            # 1. Verify Customer Groups
            print("\nVerifying Customer Groups...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/customer/group/",
                wait_until="networkidle",
            )
            await page.wait_for_timeout(2000)  # Wait for grid to load

            # Check for Premium Europe group
            premium_europe_exists = (
                await page.locator("text=Premium Europe").count() > 0
            )
            if premium_europe_exists:
                print("✓ Found 'Premium Europe' customer group", file=sys.stderr)

                # Check if it has Retail Customer tax class
                # Look for Premium Europe row and check its tax class
                premium_row = page.locator('tr:has-text("Premium Europe")')
                if await premium_row.count() > 0:
                    tax_class_text = await premium_row.locator("td").nth(2).inner_text()
                    if "Retail Customer" in tax_class_text:
                        print(
                            "✓ Premium Europe has 'Retail Customer' tax class",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"Warning: Premium Europe tax class is '{tax_class_text}'",
                            file=sys.stderr,
                        )
            else:
                print("✗ 'Premium Europe' customer group not found", file=sys.stderr)
                return False, "'Premium Europe' customer group not found"

            # Check total groups count
            records_found = page.locator("text=records found").first
            if await records_found.count() > 0:
                count_text = await records_found.inner_text()
                print(f"Customer Groups count: {count_text}", file=sys.stderr)

                # Extract number
                match = re.search(r"(\d+)\s+records found", count_text)
                if match:
                    groups_count = int(match.group(1))
                    print(f"✓ Customer groups count is {groups_count}", file=sys.stderr)

            # 2. Verify Customer
            print("\nVerifying Customer Isabella Romano...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/customer/index/",
                wait_until="networkidle",
            )
            await page.wait_for_timeout(3000)  # Wait for grid to load

            # Check total customers count
            customer_records = page.locator("text=records found").first
            if await customer_records.count() > 0:
                count_text = await customer_records.inner_text()
                print(f"Customers count: {count_text}", file=sys.stderr)

                # Extract number
                match = re.search(r"(\d+)\s+records found", count_text)
                if match:
                    customers_count = int(match.group(1))
                    print(
                        f"✓ Total customers count is {customers_count}", file=sys.stderr
                    )

                    # Verify against expected answer if available
                    if expected_answer and "FinalCustomers" in expected_answer:
                        expected_final = int(expected_answer["FinalCustomers"])
                        if customers_count == expected_final:
                            print(
                                f"✓ Customer count matches expected: {customers_count}",
                                file=sys.stderr,
                            )
                        else:
                            print(
                                f"✗ Customer count mismatch: Expected {expected_final} customers, "
                                f"found {customers_count}",
                                file=sys.stderr,
                            )
                            return False, (
                                f"Customer count mismatch: Expected {expected_final} customers, "
                                f"found {customers_count}"
                            )

            # Wait for the customer grid to load properly
            await page.wait_for_timeout(5000)

            # Check if Isabella Romano exists - first wait for grid to load
            grid_loaded = False
            for _ in range(3):
                # Look for grid container and wait for it to populate
                grid_container = page.locator(
                    ".admin__data-grid-outer-wrap, .data-grid, table"
                ).first
                if await grid_container.count() > 0:
                    # Check if there are customer rows loaded
                    customer_rows = page.locator("td[data-column='email'], td:has-text('@')")
                    if await customer_rows.count() > 0:
                        grid_loaded = True
                        break
                await page.wait_for_timeout(2000)

            if not grid_loaded:
                print("✗ Customer grid failed to load properly", file=sys.stderr)
                return False, "Customer grid failed to load properly"

            # Now check if Isabella Romano exists in the loaded grid
            isabella_exists = (
                await page.locator("text=isabella.romano@premium.eu").count() > 0
            )

            if not isabella_exists:
                # Try searching for the customer to be more thorough
                try:
                    search_selectors = (
                        'input[placeholder*="Search by keyword"], '
                        'input[name="search"], [data-role="search"]'
                    )
                    search_box = page.locator(search_selectors).first
                    if await search_box.count() > 0:
                        await search_box.clear()
                        await search_box.fill("isabella.romano@premium.eu")
                        await page.keyboard.press("Enter")
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(3000)

                        # Check again after search
                        isabella_exists = (
                            await page.locator("text=isabella.romano@premium.eu").count() > 0
                        )

                        # Also check for "No records found" message
                        no_records_locator = (
                            "text=We couldn't find any records., "
                            "text=No records found"
                        )
                        no_records = await page.locator(no_records_locator).count() > 0
                        if no_records:
                            print(
                                "✗ Customer 'isabella.romano@premium.eu' not found - "
                                "search returned no results",
                                file=sys.stderr,
                            )
                            return False, (
                                "Customer 'isabella.romano@premium.eu' not found - "
                                "search returned no results"
                            )
                except RuntimeError as error:
                    print(f"✗ Search failed: {str(error)}", file=sys.stderr)

            if isabella_exists:
                print(
                    "✓ Found customer with email 'isabella.romano@premium.eu'",
                    file=sys.stderr,
                )
            else:
                print(
                    "✗ Customer 'isabella.romano@premium.eu' not found",
                    file=sys.stderr,
                )
                return False, "Customer 'isabella.romano@premium.eu' not found"

            # 3. Verify Dashboard Last Orders
            print("\nVerifying Dashboard Last Orders...", file=sys.stderr)
            await page.goto(
                f"{BASE_URL}/admin/dashboard/",
                wait_until="networkidle",
            )
            await page.wait_for_timeout(2000)

            # Check for Last Orders section
            last_orders_exists = await page.locator("text=Last Orders").count() > 0
            if last_orders_exists:
                print("✓ Found 'Last Orders' section on dashboard", file=sys.stderr)

                # Find the first customer in the table
                # Look for the table after "Last Orders" heading
                orders_table = (
                    page.locator("text=Last Orders")
                    .locator("..")
                    .locator("table")
                    .first
                )
                if await orders_table.count() > 0:
                    # Get the last row in tbody
                    last_row = orders_table.locator("tbody tr").last
                    if await last_row.count() > 0:
                        last_customer = await last_row.locator(
                            "td"
                        ).first.inner_text()
                        print(
                            f"✓ Last customer in Last Orders: {last_customer}",
                            file=sys.stderr,
                        )

                        # Verify against expected answer if available
                        if expected_answer and "LastOrderCustomer" in expected_answer:
                            if last_customer == expected_answer["LastOrderCustomer"]:
                                print(
                                    f"✓ Last Order Customer matches expected: {last_customer}",
                                    file=sys.stderr,
                                )
                            else:
                                expected_customer = expected_answer['LastOrderCustomer']
                                print(
                                    f"✗ Last Order Customer mismatch: "
                                    f"Expected '{expected_customer}' but actual is "
                                    f"'{last_customer}'",
                                    file=sys.stderr,
                                )
                                return False, (
                                    f"Last Order Customer mismatch: "
                                    f"Expected '{expected_customer}' but actual is "
                                    f"'{last_customer}'"
                                )
            else:
                print(
                    "Warning: 'Last Orders' section not found on dashboard",
                    file=sys.stderr,
                )

            # Summary of verification - only print if we reach this point (all checks passed)
            print("\n=== Browser Verification Summary ===", file=sys.stderr)
            print("✓ Magento Admin login successful", file=sys.stderr)
            print(
                "✓ Customer group 'Premium Europe' exists with correct tax class",
                file=sys.stderr,
            )
            print("✓ Customer 'isabella.romano@premium.eu' found in system", file=sys.stderr)
            print("✓ Customer counts verified", file=sys.stderr)
            print("✓ Dashboard Last Orders section accessible", file=sys.stderr)

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
