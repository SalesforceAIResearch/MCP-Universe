#!/usr/bin/env python3
"""
Verification script for Playwright web search task.

Simple verification that checks if the AI agent found the correct Introduction content.
The expected ground truth answer is configured at the top of the file.
"""

# pylint: disable=duplicate-code

import sys
import json
import os
from pathlib import Path
from typing import Dict, Any

# =============================================================================
# CONFIGURATION
# =============================================================================

# Expected ground truth content from content.txt
EXPECTED_CONTENT_FILE = "content.txt"

# =============================================================================
# MCP RESULT PARSING
# =============================================================================


def get_working_directory() -> Path:
    """Get the working directory where messages.json should be."""
    # Priority 1: Use MCP_MESSAGES path if available (most reliable)
    messages_path = os.getenv("MCP_MESSAGES")
    if messages_path and Path(messages_path).exists():
        return Path(messages_path).parent.resolve()

    # Priority 2: Use PLAYWRIGHT_WORK_DIR environment variable
    work_dir = os.getenv("PLAYWRIGHT_WORK_DIR")
    if work_dir:
        work_path = Path(work_dir).resolve()
        if (work_path / "messages.json").exists():
            return work_path

    # Priority 3: Check current directory (fallback)
    current_dir = Path.cwd()
    if (current_dir / "messages.json").exists():
        return current_dir

    # Priority 4: Default fallback
    return Path(".").resolve()


def load_expected_content() -> str:
    """Load the expected content from content.txt"""
    # content.txt is in the same directory as verify.py
    current_file = Path(__file__).resolve()
    content_file = current_file.parent / EXPECTED_CONTENT_FILE

    if not content_file.exists():
        print(f"| {EXPECTED_CONTENT_FILE} not found at: {content_file}")
        return ""

    print(f"| Found {EXPECTED_CONTENT_FILE} at: {content_file}")

    try:
        with open(content_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (IOError, UnicodeDecodeError) as e:
        print(f"| Warning: Could not read {content_file}: {e}")
        return ""


def parse_ai_results(work_dir: Path) -> Dict[str, Any]:
    """Parse the AI agent's results from messages.json"""
    messages_file = work_dir / "messages.json"
    if not messages_file.exists():
        return {"success": False, "error": "No messages.json found"}

    try:
        with open(messages_file, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return {"success": False, "error": f"Failed to read messages.json: {e}"}

    # Look for extracted content in the AI's responses
    ai_responses = []
    extracted_content = ""

    for message in messages:
        if message.get("role") == "assistant":
            content = str(message.get("content", ""))

            # Handle both string and list content formats
            if isinstance(message.get("content"), list):
                content = " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in message.get("content", [])
                )

            ai_responses.append(content)

            # Store the last response as extracted content
            extracted_content = content

    return {
        "success": True,
        "found_content": True,  # Assuming content was found if we have responses
        "ai_responses": ai_responses,
        "extracted_content": extracted_content,
        "total_responses": len(ai_responses),
    }


def compare_content(extracted: str, expected: str) -> Dict[str, Any]:
    """Compare extracted content with expected content"""
    if not expected:
        return {"success": False, "error": "No expected content to compare against"}

    if not extracted:
        return {"success": False, "error": "No extracted content found"}

    # Normalize content for comparison (remove extra whitespace, normalize line breaks)
    extracted_normalized = " ".join(extracted.split())
    expected_normalized = " ".join(expected.split())

    # Direct text comparison - content must be exactly the same
    is_exact_match = extracted_normalized == expected_normalized

    return {
        "success": True,
        "is_exact_match": is_exact_match,
        "extracted_length": len(extracted_normalized),
        "expected_length": len(expected_normalized),
        "extracted_preview": (extracted_normalized[:100] + "..."
                              if len(extracted_normalized) > 100
                              else extracted_normalized),
        "expected_preview": (expected_normalized[:100] + "..."
                             if len(expected_normalized) > 100
                             else expected_normalized)
    }


# =============================================================================
# MAIN VERIFICATION
# =============================================================================


def verify_task(work_dir: Path) -> tuple[bool, str]:
    """Verify the AI agent found the correct Introduction content"""
    print("| Verifying Playwright Web Search Task - DeepSeek R1 Introduction")
    print("| " + "=" * 70)

    # Load expected content
    print("| Loading expected content...")
    expected_content = load_expected_content()

    if not expected_content:
        print("| Error: Could not load expected content")
        return False, "Could not load expected content"

    print(f"| Expected content loaded ({len(expected_content)} characters)")

    # Parse MCP messages
    messages = parse_ai_results(work_dir)

    if not messages["success"]:
        print(f"| Error: Could not parse AI results: {messages.get('error')}")
        return False, f"Could not parse AI results: {messages.get('error')}"

    # Extract AI agent response
    extracted_content = messages.get("extracted_content", "")

    if not extracted_content:
        print("| Error: No AI agent response found")
        return False, "No AI agent response found"

    print(f"| Extracted content: {len(extracted_content)} characters")

    # Compare content
    print("| Comparing extracted content with expected content...")
    comparison = compare_content(extracted_content, expected_content)

    if not comparison["success"]:
        print(f"| Comparison failed: {comparison.get('error')}")
        return False, f"Comparison failed: {comparison.get('error')}"

    print("| Content comparison results:")
    print(f"|   - Extracted length: {comparison['extracted_length']} characters")
    print(f"|   - Expected length: {comparison['expected_length']} characters")
    print(f"|   - Extracted preview: {comparison['extracted_preview']}")
    print(f"|   - Expected preview: {comparison['expected_preview']}")

    if comparison['is_exact_match']:
        print("| Task completed successfully! Content matches exactly.")
        return True, ""
    print("| Task verification failed. Content does not match exactly.")
    return False, "Task verification failed. Content does not match exactly."


def main():
    """Main verification function"""
    print("| Starting verification...")

    # Get working directory
    work_dir = get_working_directory()
    print(f"| Working directory: {work_dir}")

    # Run verification
    success, _error_msg = verify_task(work_dir)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
