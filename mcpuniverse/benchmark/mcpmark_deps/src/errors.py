#!/usr/bin/env python3
"""
Simple Error Handling for MCPMark
==================================

Provides basic error standardization and retry logic.
"""

from typing import Optional


"""Retryable error detection via minimal substring matching (lower-case)."""

# Keep this list short and generic; aim to catch API/infrastructure issues only.
RETRYABLE_PATTERNS = {
    "ratelimit",              # e.g., RateLimitError, too many requests
    "connection",             # connection refused/reset/error
    "unavailable",            # service unavailable
    # "execution timed out",    # timeout
    "internal server error",  # 500s
    "network error",          # generic network issue
    "quota",                  # budget/quota exceeded
    # "llm provider not provided",  # litellm error
    # pipeline infra signals
    "double quotes", # actually json error
    "account balance",
    "expecting value",
    "mcp network error",
    "state duplication error",
}


def is_retryable_error(error: str) -> bool:
    """Return True if the error string contains any retryable pattern."""
    error_lower = str(error or "").lower()
    return any(pattern in error_lower for pattern in RETRYABLE_PATTERNS)


def standardize_error_message(error: str, mcp_service: Optional[str] = None) -> str:
    """Standardize error messages for consistent reporting."""
    error_str = str(error).strip()

    # Common standardizations
    if "timeout" in error_str.lower():
        base_msg = "Operation timed out"
    elif (
        "connection refused" in error_str.lower() or "econnrefused" in error_str.lower()
    ):
        base_msg = "Connection refused"
    elif "authentication" in error_str.lower() or "unauthorized" in error_str.lower():
        base_msg = "Authentication failed"
    elif "not found" in error_str.lower():
        base_msg = "Resource not found"
    elif "already exists" in error_str.lower():
        base_msg = "Resource already exists"
    elif "mcp" in error_str.lower() and "error" in error_str.lower():
        base_msg = "MCP service error"
    else:
        # Return original message if no standardization applies
        return error_str

    # Add MCP service prefix if provided
    if mcp_service:
        return f"{mcp_service.title()} {base_msg}"

    return base_msg
