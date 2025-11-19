"""Verification module for NY expansion analysis task."""
# pylint: disable=C0411,C0412,C0413,R0911,R0912,R1702,W1309,duplicate-code
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
        print("ERROR: MCP_MESSAGES environment variable not set", file=sys.stderr)
        return None

    # Check if file exists
    if not Path(messages_path).exists():
        print(f"ERROR: Messages file not found at path: {messages_path}", file=sys.stderr)
        return None

    try:
        with open(messages_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        # Check if file is empty
        if not content or content.strip() == '""':
            print("ERROR: Messages file is empty or contains only empty string", file=sys.stderr)
            return None

        messages = json.loads(content)

        # Check if messages is a list
        if not isinstance(messages, list):
            print(
                f"ERROR: Messages file should contain a list, got {type(messages).__name__}",
                file=sys.stderr
            )
            return None

        # Find the last assistant message
        for message in reversed(messages):
            if message.get('role') == 'assistant' and message.get('status') == 'completed':
                content = message.get('content', [])
                if not content:
                    print("WARNING: Assistant message has empty content", file=sys.stderr)
                    continue

                for item in content:
                    if item.get('type') == 'output_text':
                        text = item.get('text', '')
                        if not text:
                            print("WARNING: Output text is empty", file=sys.stderr)
                            continue
                        return text

        print("ERROR: No assistant response with output_text found in messages", file=sys.stderr)
        return None
    except json.JSONDecodeError as error:
        print(f"ERROR: Invalid JSON in messages file: {str(error)}", file=sys.stderr)
        return None
    except OSError as error:
        print(f"ERROR: Unexpected error reading messages file: {str(error)}", file=sys.stderr)
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
    match = re.search(r'<answer>(.*?)</answer>', text, re.IGNORECASE | re.DOTALL)
    if not match:
        print("ERROR: No <answer> tags found in the response", file=sys.stderr)
        print(f"  Response preview: {text[:200]}...", file=sys.stderr)
        return None

    answer_content = match.group(1).strip()

    if not answer_content:
        print("ERROR: Empty content between <answer> tags", file=sys.stderr)
        return None

    # Parse each line
    result = {}
    lines = answer_content.split('\n')

    # Expected keys that should be present
    expected_keys = [
        'Lifetime_Sales_Amount', 'Cheap_Bestseller_Name', 'Second_Bestseller_Price',
        'Second_Bestseller_Quantity', 'Product_In_Last_Orders', 'NY_Tax_Rate',
        'CA_Tax_Rate', 'Higher_Tax_State', 'Total_States_With_Tax',
        'Processing_Visible_Storefront', 'Processing_Default_Status',
        'Number_Of_Websites', 'Main_Store_Code', 'Default_Source_Pickup_Status',
        'Default_Source_State', 'Dashboard_Revenue', 'Tax_Shipping_Zero'
    ]

    parsed_keys = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        if '|' not in line:
            print(f"ERROR: Line missing pipe separator '|': {line}", file=sys.stderr)
            continue

        parts = line.split('|', 1)
        if len(parts) != 2:
            print(f"ERROR: Invalid line format: {line}", file=sys.stderr)
            continue

        key, value = parts
        key = key.strip()
        value = value.strip()

        if not key:
            print(f"ERROR: Empty key in line: {line}", file=sys.stderr)
            continue

        result[key] = value
        parsed_keys.append(key)

    # Check for missing expected keys
    missing_keys = set(expected_keys) - set(parsed_keys)
    if missing_keys:
        print(f"ERROR: Missing expected keys: {', '.join(sorted(missing_keys))}", file=sys.stderr)

    # Check for unexpected keys
    unexpected_keys = set(parsed_keys) - set(expected_keys)
    if unexpected_keys:
        print(
            f"WARNING: Unexpected keys found: {', '.join(sorted(unexpected_keys))}",
            file=sys.stderr
        )

    if not result:
        print("ERROR: No valid key-value pairs parsed from answer", file=sys.stderr)
        return None

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
        if key in ['Lifetime_Sales_Amount', 'Second_Bestseller_Price', 'Dashboard_Revenue']:
            # For price/amount fields, normalize format
            expected_clean = expected_value.replace('$', '').replace(',', '')
            model_clean = model_value.replace('$', '').replace(',', '')
            if expected_clean != model_clean:
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key in ['NY_Tax_Rate', 'CA_Tax_Rate']:
            # Tax rates - allow different decimal formats
            expected_clean = expected_value.replace('%', '').strip()
            model_clean = model_value.replace('%', '').strip()
            # Convert to float for comparison
            try:
                if float(expected_clean) != float(model_clean):
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")
            except ValueError:
                if expected_clean != model_clean:
                    mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key in [
            'Product_In_Last_Orders',
            'Processing_Visible_Storefront',
            'Processing_Default_Status',
            'Tax_Shipping_Zero'
        ]:
            # Yes/No fields - case insensitive
            if model_value.lower() != expected_value.lower():
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'Empty_Rows_Yes_Effect':
            # Allow flexible descriptions for this field
            # Just check if model provided some reasonable description
            if not model_value or len(model_value) < 5:
                mismatches.append(f"{key}: expected meaningful description, got '{model_value}'")

        elif key == 'Order_Status_Options':
            # Check if main options are mentioned
            expected_options = set(opt.strip() for opt in expected_value.split(','))
            model_options = set(opt.strip() for opt in model_value.split(','))
            if expected_options != model_options:
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        elif key == 'Chart_Disabled_Message':
            # Allow some flexibility in message text
            # Check for key words
            if 'disabled' not in model_value.lower() and 'enable' not in model_value.lower():
                mismatches.append(
                    f"{key}: expected message about chart being disabled, "
                    f"got '{model_value}'"
                )

        elif key == 'Default_Source_State':
            # Handle 'None' or empty state
            expected_normalized = expected_value.lower() if expected_value.lower() != 'none' else ''
            model_normalized = model_value.lower() if model_value.lower() != 'none' else ''
            if expected_normalized != model_normalized:
                mismatches.append(f"{key}: expected '{expected_value}', got '{model_value}'")

        else:
            # Exact match for other fields
            if model_value != expected_value:
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
    Verifies that the NY expansion analysis task has been completed correctly.
    First checks the model's answer against the expected label,
    then optionally verifies the actual state in the Magento Admin.
    """
    print("\n=== Starting Verification ===", file=sys.stderr)

    # Get the label file path
    label_path = Path(__file__).parent / "label.txt"

    # Load expected answer
    print("Loading expected answer from label.txt...", file=sys.stderr)
    expected_answer = load_expected_answer(label_path)
    if not expected_answer:
        print("FATAL ERROR: Could not load expected answer from label.txt", file=sys.stderr)
        return False, "Could not load expected answer from label.txt"

    print(f"Expected answer loaded with {len(expected_answer)} keys", file=sys.stderr)

    # Get model's response from MCP_MESSAGES
    print("\nReading model response from MCP_MESSAGES...", file=sys.stderr)
    model_response = get_model_response()

    if not model_response:
        print("FATAL ERROR: No valid model response found", file=sys.stderr)
        return False, "No valid model response found"

    print(f"Model response found (length: {len(model_response)} chars)", file=sys.stderr)
    print("\nParsing answer format from model response...", file=sys.stderr)

    model_answer = parse_answer_format(model_response)

    if not model_answer:
        print("FATAL ERROR: Could not parse answer format from model response", file=sys.stderr)
        return False, "Could not parse answer format from model response"

    print(f"\n=== Model Answer Parsed Successfully ===", file=sys.stderr)
    print(f"Parsed {len(model_answer)} key-value pairs", file=sys.stderr)

    for key, value in model_answer.items():
        print(f"  {key}: {value}", file=sys.stderr)

    # Compare answers
    print("\n=== Comparing Model Answer with Expected Answer ===", file=sys.stderr)
    answer_match, error_msg = compare_answers(model_answer, expected_answer)

    if not answer_match:
        print("\nFATAL ERROR: Model answer does not match expected answer", file=sys.stderr)
        print("Verification FAILED", file=sys.stderr)
        return False, error_msg

    print("\n✓ Model answer matches expected answer", file=sys.stderr)
    print("Verification PASSED", file=sys.stderr)
    return True, ""

def main():
    """
    Executes the verification process and exits with a status code.
    """
    success, _ = asyncio.run(verify())
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
