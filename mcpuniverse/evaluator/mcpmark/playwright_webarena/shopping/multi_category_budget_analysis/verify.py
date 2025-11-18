"""Verification module for multi category budget analysis task."""
# pylint: disable=R0912
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
                and message.get("type") == "message"
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

    if len(lines) != 11:
        print(f"Error: Expected 11 lines in answer, got {len(lines)}", file=sys.stderr)
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

        # Special handling for different types of values
        if key == "chocolate_products":
            # Parse and compare chocolate products with price:SKU format
            expected_products = expected_value.split(";")
            model_products = model_value.split(";")

            if len(expected_products) != len(model_products):
                mismatches.append(f"{key}: expected {len(expected_products)} products, got {len(model_products)}")
            else:
                for i, (exp, mod) in enumerate(zip(expected_products, model_products)):
                    exp_parts = exp.strip().split(":")
                    mod_parts = mod.strip().split(":")
                    if len(exp_parts) != 2 or len(mod_parts) != 2:
                        mismatches.append(f"{key}: product {i+1} format error - expected 'price:SKU'")
                    else:
                        # Check price format (should start with $)
                        if not mod_parts[0].startswith("$"):
                            mismatches.append(
                                f"{key}: product {i+1} price format error - "
                                f"expected '$XX.XX' format, got '{mod_parts[0]}'"
                            )
                        elif exp_parts[0] != mod_parts[0] or exp_parts[1] != mod_parts[1]:
                            mismatches.append(f"{key}: product {i+1} mismatch - expected '{exp}', got '{mod}'")

        elif key == "tabletop_product":
            # Parse and compare tabletop product with price:SKU format
            exp_parts = expected_value.strip().split(":")
            mod_parts = model_value.strip().split(":")
            if len(exp_parts) != 2 or len(mod_parts) != 2:
                mismatches.append(f"{key}: format error - expected 'price:SKU', got '{model_value}'")
            else:
                # Check price format (should start with $)
                if not mod_parts[0].startswith("$"):
                    mismatches.append(f"{key}: price format error - expected '$XX.XX' format, got '{mod_parts[0]}'")
                elif exp_parts[0] != mod_parts[0] or exp_parts[1] != mod_parts[1]:
                    mismatches.append(f"{key}: mismatch - expected '{expected_value}', got '{model_value}'")

        elif key == "tabletop_reviews":
            # Parse and compare tabletop reviews with NumberOfReviews:Rating format
            exp_parts = expected_value.strip().split(":")
            mod_parts = model_value.strip().split(":")
            if len(exp_parts) != 2 or len(mod_parts) != 2:
                mismatches.append(f"{key}: format error - expected 'NumberOfReviews:Rating', got '{model_value}'")
            else:
                # Check if both parts match
                if exp_parts[0] != mod_parts[0] or exp_parts[1] != mod_parts[1]:
                    mismatches.append(f"{key}: mismatch - expected '{expected_value}', got '{model_value}'")

        elif key in ["chocolate_sum", "price_difference", "cart_subtotal", "cheapest_computer_accessory"]:
            # For price fields, only support $XX.XX format
            # Check if model value has correct format
            if not model_value.startswith("$"):
                mismatches.append(
                    f"{key}: incorrect format - expected '$XX.XX' format, got '{model_value}'"
                )
            else:
                # Normalize and compare values
                expected_clean = expected_value.replace("$", "").replace(",", "")
                model_clean = model_value.replace("$", "").replace(",", "")
                if expected_clean != model_clean:
                    mismatches.append(
                        f"{key}: expected '{expected_value}', got '{model_value}'"
                    )

        elif key == "under_60_budget":
            # Compare YES/NO value (case-insensitive)
            if expected_value.upper() != model_value.upper():
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key in ["tabletop_search_count", "comparison_count", "cart_item_count"]:
            # Numeric fields - exact match
            if model_value != expected_value:
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
    Verifies that the multi-category budget analysis task has been completed correctly.
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
        print("Warning: Could not parse answer format from model response", file=sys.stderr)
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
