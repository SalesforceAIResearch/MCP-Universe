"""Verification module for products sales analysis task."""
# pylint: disable=R0911,R0912,duplicate-code
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
        print("Error: No text provided to parse", file=sys.stderr)
        return None

    # Look for <answer>...</answer> pattern
    match = re.search(r"<answer>(.*?)</answer>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        print("Error: No <answer>...</answer> tags found in response", file=sys.stderr)
        return None

    answer_content = match.group(1).strip()
    if not answer_content:
        print("Error: Empty answer content", file=sys.stderr)
        return None

    # Parse each line
    result = {}
    lines = [line.strip() for line in answer_content.split("\n") if line.strip()]

    if len(lines) != 10:
        print(f"Error: Expected 10 lines in answer, got {len(lines)}", file=sys.stderr)
        print(f"Lines found: {lines}", file=sys.stderr)
        return None

    # Expected keys for validation
    expected_keys = [
        "YogaProducts", "WH11Price", "ZeroQuantityProducts", "LowestProduct",
        "QuestLumaflexQuantity", "DashboardRevenue", "SarahMillerEmail",
        "TotalCustomers", "PendingOrders", "GraceNguyenOrderID"
    ]

    for line in lines:
        if "|" not in line:
            print(f"Error: Line missing '|' separator: {line}", file=sys.stderr)
            return None

        parts = line.split("|", 1)
        if len(parts) != 2:
            print(f"Error: Invalid line format: {line}", file=sys.stderr)
            return None

        key, value = parts[0].strip(), parts[1].strip()

        if not key or not value:
            print(f"Error: Empty key or value in line: {line}", file=sys.stderr)
            return None

        result[key] = value

    # Validate all expected keys are present
    missing_keys = set(expected_keys) - set(result.keys())
    if missing_keys:
        print(f"Error: Missing required keys: {missing_keys}", file=sys.stderr)
        return None

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
        if key == "LowestProduct":
            # Check if product name and quantity match (format: "Product Name:quantity")
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

        elif key in ["WH11Price", "DashboardRevenue"]:
            # For price/amount fields, normalize format
            expected_clean = expected_value.replace("$", "").replace(",", "")
            model_clean = model_value.replace("$", "").replace(",", "")
            if expected_clean != model_clean:
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        elif key == "SarahMillerEmail":
            # Email should match exactly
            if model_value.lower() != expected_value.lower():
                mismatches.append(
                    f"{key}: expected '{expected_value}', got '{model_value}'"
                )

        else:
            # Exact match for other fields
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
    Verifies that the products and sales analysis task has been completed correctly.
    First checks the model's answer against the expected label,
    then optionally verifies the actual state in the Magento Admin.
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
            return True, ""
        print(
            "Warning: Could not parse answer format from model response",
            file=sys.stderr,
        )
        return False, "Could not parse answer format from model response"
    print("No model response found", file=sys.stderr)
    return False, "No model response found"


def main():
    """
    Executes the verification process and exits with a status code.
    """
    success, _ = asyncio.run(verify())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
