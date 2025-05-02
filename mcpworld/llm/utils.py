"""
Utility functions for processing LLM outputs.

This module provides helper functions to extract and parse structured data
from LLM responses, particularly focusing on JSON-formatted outputs.
"""
# pylint: disable=broad-exception-caught
import re
import json
from typing import List


def extract_json_output(response: str) -> List[dict]:
    """
    Extracts and parses JSON-formatted outputs from an LLM response.

    This function searches for JSON-like structures within the given response,
    attempts to parse them, and returns a list of successfully parsed JSON objects.

    Args:
        response (str): The raw text response from an LLM.

    Returns:
        List[dict]: A list of parsed JSON objects extracted from the response.
            Returns an empty list if no valid JSON structures are found.

    Note:
        The function first looks for JSON structures enclosed in ```json``` blocks.
        If none are found, it searches for any content within ``` blocks.
        Invalid JSON structures are silently ignored.
    """
    results = []
    pattern = r"```json(.*?)```"
    matches = re.finditer(pattern, response, re.DOTALL | re.IGNORECASE)
    for match in matches:
        results.append(match.groups()[0])

    if len(results) == 0:
        pattern = r"```(.*?)```"
        matches = re.finditer(pattern, response, re.DOTALL | re.IGNORECASE)
        for match in matches:
            results.append(match.groups()[0])

    outputs = []
    for r in results:
        try:
            d = json.loads(r)
            outputs.append(d)
        except Exception:
            pass
    return outputs
