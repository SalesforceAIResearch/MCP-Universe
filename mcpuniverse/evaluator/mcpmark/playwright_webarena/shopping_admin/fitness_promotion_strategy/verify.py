"""Verification module for fitness promotion strategy task."""
# pylint: disable=R0912,R0914,R0915,R1702,R1724,duplicate-code
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
        with open(messages_path, 'r', encoding='utf-8') as file_handle:
            messages = json.load(file_handle)

        # Find the last assistant message
        for message in reversed(messages):
            if message.get('role') == 'assistant' and message.get('status') == 'completed':
                content = message.get('content', [])
                for item in content:
                    if item.get('type') == 'output_text':
                        return item.get('text', '')

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
    match = re.search(r'<answer>(.*?)</answer>', text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    answer_content = match.group(1).strip()

    # Parse each line
    result = {}
    lines = answer_content.split('\n')

    # Skip the check for exact number of lines - just parse what we have
    # if len(lines) != 13:
    #     print(f"Error: Expected 13 lines in answer, got {len(lines)}", file=sys.stderr)
    #     return None

    for line in lines:
        if '|' in line:
            key, value = line.split('|', 1)
            result[key.strip()] = value.strip()

    return result

def load_expected_answer(label_path):
    """
    Load the expected answer from label.txt file.
    Returns a dictionary with the expected values.
    """
    try:
        with open(label_path, 'r', encoding='utf-8') as file_handle:
            lines = file_handle.read().strip().split('\n')

        expected = {}
        for line in lines:
            if '|' in line:
                key, value = line.split('|', 1)
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
        model_value = model_answer.get(key, '')

        # Special handling for different types of values
        if key in ['Bestseller1', 'Bestseller2', 'Bestseller3']:
            # Check if all parts match (name:price:quantity:sku:inventory:status)
            if ':' in expected_value and ':' in model_value:
                expected_parts = expected_value.split(':')
                model_parts = model_value.split(':')
                if len(expected_parts) == 6 and len(model_parts) == 6:
                    # Compare each part
                    for i, (exp, mod) in enumerate(zip(expected_parts, model_parts)):
                        if i == 1:  # Price field
                            exp_clean = exp.replace('$', '').replace(',', '')
                            mod_clean = mod.replace('$', '').replace(',', '')
                            if exp_clean != mod_clean:
                                mismatches.append(f"{key} price: expected '{exp}', got '{mod}'")
                        elif i == 4:  # Inventory field (may have decimal places)
                            exp_float = float(exp.replace(',', ''))
                            mod_float = float(mod.replace(',', ''))
                            if abs(exp_float - mod_float) > 0.0001:
                                mismatches.append(f"{key} inventory: expected '{exp}', got '{mod}'")
                        else:
                            if exp.lower() != mod.lower():
                                mismatches.append(f"{key} part {i}: expected '{exp}', got '{mod}'")
                else:
                    mismatches.append(
                        f"{key}: format mismatch - expected '{expected_value}', "
                        f"got '{model_value}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'LowestInventoryProduct':
            # Check product name and inventory
            if ':' in expected_value and ':' in model_value:
                expected_name, expected_inv = expected_value.rsplit(':', 1)
                model_name, model_inv = model_value.rsplit(':', 1)
                if expected_name.lower() != model_name.lower():
                    mismatches.append(f"{key} name: expected '{expected_name}', got '{model_name}'")
                exp_float = float(expected_inv.replace(',', ''))
                mod_float = float(model_inv.replace(',', ''))
                if abs(exp_float - mod_float) > 0.0001:
                    mismatches.append(
                        f"{key} inventory: expected '{expected_inv}', got '{model_inv}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key in ['TotalRevenue', 'MinimumPurchaseRule']:
            # For price/amount fields, normalize format
            expected_clean = expected_value.replace('$', '').replace(',', '')
            model_clean = model_value.replace('$', '').replace(',', '')
            if expected_clean != model_clean:
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'BestsellerInSearch':
            # Check search term and count
            if expected_value.lower() != model_value.lower():
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'PercentageDiscountRule':
            # Check rule name and percentage
            if ':' in expected_value and ':' in model_value:
                expected_name, expected_pct = expected_value.rsplit(':', 1)
                model_name, model_pct = model_value.rsplit(':', 1)
                if expected_name != model_name:
                    mismatches.append(f"{key} name: expected '{expected_name}', got '{model_name}'")
                # Normalize percentage (20% vs 20 vs 0.20)
                exp_pct_clean = expected_pct.replace('%', '').strip()
                mod_pct_clean = model_pct.replace('%', '').strip()
                if exp_pct_clean != mod_pct_clean:
                    mismatches.append(
                        f"{key} percentage: expected '{expected_pct}', got '{model_pct}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'TopCustomer':
            # Check name:email:group
            if ':' in expected_value and ':' in model_value:
                expected_parts = expected_value.split(':')
                model_parts = model_value.split(':')
                if len(expected_parts) == 3 and len(model_parts) == 3:
                    exp_name, exp_email, exp_group = expected_parts
                    mod_name, mod_email, mod_group = model_parts
                    if exp_name != mod_name:
                        mismatches.append(f"{key} name: expected '{exp_name}', got '{mod_name}'")
                    if exp_email.lower() != mod_email.lower():
                        mismatches.append(f"{key} email: expected '{exp_email}', got '{mod_email}'")
                    if exp_group.lower() != mod_group.lower():
                        mismatches.append(f"{key} group: expected '{exp_group}', got '{mod_group}'")
                else:
                    mismatches.append(
                        f"{key}: format mismatch - expected '{expected_value}', "
                        f"got '{model_value}'"
                    )
            else:
                if expected_value != model_value:
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'MostRecentOrderDate':
            # Date format may vary, do flexible comparison
            if expected_value.lower() == 'none' and model_value.lower() == 'none':
                continue
            elif expected_value != model_value:
                # Could add more flexible date parsing here if needed
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        else:
            # Exact match for other fields (counts, etc.)
            if str(model_value) != str(expected_value):
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

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
    Verifies that the bestseller analysis and promotion task has been completed correctly.
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
