"""Verification module for sales inventory analysis task."""
# pylint: disable=R0911,R0912
import asyncio
import sys
import re
import os
import json
from pathlib import Path


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

        # Find the last assistant message with type='message', status='completed'
        for message in reversed(messages):
            if (
                message.get("role") == "assistant"
                and message.get("status") == "completed"
                and message.get("type") == "message"
            ):
                content = message.get("content", [])
                for item in content:
                    # Check for both 'text' and 'output_text' types
                    if item.get("type") in ["text", "output_text"]:
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
        print("ERROR: No text provided to parse", file=sys.stderr)
        return None

    # Look for <answer>...</answer> pattern
    match = re.search(r"<answer>(.*?)</answer>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        print("ERROR: No <answer>...</answer> tags found in the response", file=sys.stderr)
        print("Response text preview (first 200 chars):", text[:200], file=sys.stderr)
        return None

    answer_content = match.group(1).strip()
    print(f"Found answer content with {len(answer_content)} characters", file=sys.stderr)

    # Parse each line
    result = {}
    lines = answer_content.split("\n")

    # Expected keys for this task
    expected_keys = [
        "SpriteProducts", "Quantity100Products", "WS12Info", "PendingOrders",
        "GraceOrderID", "HighestOrderInfo", "CheapProduct", "OvernightDufflePrice",
        "HollisterPosition", "CostelloCustomers", "SarahMillerInfo",
        "PaidInvoices", "Invoice002BillTo"
    ]

    if len(lines) != 13:
        print(f"ERROR: Expected 13 lines in answer, got {len(lines)}", file=sys.stderr)
        print(f"Lines found: {lines}", file=sys.stderr)
        return None

    for i, line in enumerate(lines, 1):
        if "|" not in line:
            print(f"ERROR: Line {i} does not contain pipe separator '|': '{line}'", file=sys.stderr)
            return None

        parts = line.split("|", 1)
        if len(parts) != 2:
            print(f"ERROR: Line {i} could not be split into key|value: '{line}'", file=sys.stderr)
            return None

        key, value = parts
        result[key.strip()] = value.strip()

    # Check if all expected keys are present
    missing_keys = set(expected_keys) - set(result.keys())
    if missing_keys:
        print(f"ERROR: Missing expected keys: {missing_keys}", file=sys.stderr)
        print(f"Keys found: {list(result.keys())}", file=sys.stderr)
        return None

    # Check for unexpected keys
    extra_keys = set(result.keys()) - set(expected_keys)
    if extra_keys:
        print(f"WARNING: Unexpected keys found: {extra_keys}", file=sys.stderr)

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

        # Special handling for different types of values
        if key == "WS12Info":
            # Check if product name and price match (format: name:price)
            if ":" in expected_value and ":" in model_value:
                expected_name, expected_price = expected_value.rsplit(":", 1)
                model_name, model_price = model_value.rsplit(":", 1)
                # Normalize price format
                expected_price_clean = expected_price.replace("$", "").replace(",", "")
                model_price_clean = model_price.replace("$", "").replace(",", "")
                if (
                    expected_name != model_name
                    or expected_price_clean != model_price_clean
                ):
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )

        elif key == "GraceOrderID":
            # Order ID should start with "000" and match exactly
            if not model_value.startswith("000"):
                mismatches.append(
                    f"{key}: expected to start with '000', got '{model_value}'"
                )
            elif model_value != expected_value:
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        elif key == "HighestOrderInfo":
            # Check format customer:amount
            if ":" in expected_value and ":" in model_value:
                expected_customer, expected_amount = expected_value.rsplit(":", 1)
                model_customer, model_amount = model_value.rsplit(":", 1)
                # Normalize amount format
                expected_amount_clean = expected_amount.replace("$", "").replace(
                    ",", ""
                )
                model_amount_clean = model_amount.replace("$", "").replace(",", "")
                if (
                    expected_customer != model_customer
                    or expected_amount_clean != model_amount_clean
                ):
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )

        elif key == "Position2Product":
            # Check if product name and quantity match
            if ":" in expected_value and ":" in model_value:
                expected_name, expected_qty = expected_value.rsplit(":", 1)
                model_name, model_qty = model_value.rsplit(":", 1)
                if expected_name != model_name or expected_qty != model_qty:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )

        elif key == "OvernightDufflePrice":
            # Normalize price format
            expected_clean = expected_value.replace("$", "").replace(",", "")
            model_clean = model_value.replace("$", "").replace(",", "")
            if expected_clean != model_clean:
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        elif key == "HollisterPosition":
            # Position format (1st, 2nd, 3rd, etc.)
            if model_value.lower() != expected_value.lower():
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        elif key == "SarahMillerInfo":
            # Format: group:date
            if ":" in expected_value and ":" in model_value:
                expected_group, expected_date = expected_value.split(":", 1)
                model_group, model_date = model_value.split(":", 1)
                # Allow some flexibility in date format
                if expected_group != model_group:
                    mismatches.append(
                        f"{key}: expected group '{expected_group}', got '{model_group}'"
                    )
                # For date, check if key parts match
                if not (expected_date in model_date or model_date in expected_date):
                    mismatches.append(
                        f"{key}: expected date '{expected_date}', got '{model_date}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )

        elif key == "Invoice002BillTo":
            # Name should match exactly
            if model_value != expected_value:
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        else:
            # Exact match for count fields and other numeric values
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
    Verifies that the sales and inventory analysis task has been completed correctly.
    First checks the model's answer against the expected label,
    then optionally verifies the actual state in the Magento Admin.
    """
    print("\n" + "="*60, file=sys.stderr)
    print("Starting verification of Task 5", file=sys.stderr)
    print("="*60, file=sys.stderr)

    # Get the label file path
    label_path = Path(__file__).parent / "label.txt"

    # Load expected answer
    print("\n--- Loading Expected Answer ---", file=sys.stderr)
    expected_answer = load_expected_answer(label_path)
    if not expected_answer:
        print("FATAL ERROR: Could not load expected answer from label.txt", file=sys.stderr)
        return False, "Could not load expected answer from label.txt"
    print(f"Successfully loaded {len(expected_answer)} expected values", file=sys.stderr)

    # Get model's response from MCP_MESSAGES
    print("\n--- Loading Model Response ---", file=sys.stderr)
    model_response = get_model_response()
    if not model_response:
        print("FATAL ERROR: No model response found in MCP_MESSAGES", file=sys.stderr)
        return False, "No model response found in MCP_MESSAGES"

    print(f"Found model response ({len(model_response)} characters)", file=sys.stderr)

    print("\n--- Parsing Answer Format ---", file=sys.stderr)
    model_answer = parse_answer_format(model_response)

    if not model_answer:
        print("\nFATAL ERROR: Could not parse answer format from model response", file=sys.stderr)
        print("Verification FAILED", file=sys.stderr)
        return False, "Could not parse answer format from model response"

    print("\n=== Model Answer Successfully Parsed ===", file=sys.stderr)
    for key, value in model_answer.items():
        print(f"  {key}: {value}", file=sys.stderr)

    # Compare answers
    print("\n--- Comparing Answers ---", file=sys.stderr)
    answer_match, error_msg = compare_answers(model_answer, expected_answer)

    if not answer_match:
        print("\n" + "="*60, file=sys.stderr)
        print("VERIFICATION FAILED: Model answer does not match expected answer", file=sys.stderr)
        print("="*60, file=sys.stderr)
        return False, error_msg

    print("\n" + "="*60, file=sys.stderr)
    print("✓ VERIFICATION PASSED: Model answer matches expected answer", file=sys.stderr)
    print("="*60, file=sys.stderr)
    return True, ""


def main():
    """
    Executes the verification process and exits with a status code.
    """
    success, _ = asyncio.run(verify())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
