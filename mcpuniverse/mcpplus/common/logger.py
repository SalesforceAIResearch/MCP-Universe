"""
Simplified logging for MCP+ with clean Cursor-friendly output.

This module provides a minimal logger that:
- Uses a clean format: "[MCP+] message" (no timestamps/process IDs)
- Defaults to WARNING level (quiet by default)
- Can be set to DEBUG via MCPPLUS_LOG_LEVEL environment variable
"""
# pylint: disable=invalid-name,global-statement,cyclic-import
import logging
import os

# Default to WARNING for quiet operation; set MCPPLUS_LOG_LEVEL=DEBUG for verbose
LOGLEVEL = os.environ.get("MCPPLUS_LOG_LEVEL", "WARNING").upper()
LOGGER_NAME = "MCPPlus"

# Clean format for Cursor UX - just prefix and message
LOGGER_FORMAT = "[MCP+] %(message)s"

# More detailed format for DEBUG level
DEBUG_FORMAT = "[MCP+:%(name)s] %(message)s"

# Track if we've already configured the root MCPPlus logger
_configured = False


def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    Get a logger with clean MCP+ formatting.

    Args:
        name: Logger name (will be prefixed with MCPPlus.)
        level: Optional override for log level. If not provided, uses MCPPLUS_LOG_LEVEL env var.

    Returns:
        Configured logger instance.
    """
    global _configured

    # Use the provided level or fall back to environment/default
    effective_level = level or LOGLEVEL

    # Get or create logger
    full_name = f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME
    logger = logging.getLogger(full_name)

    # Configure root MCPPlus logger once
    if not _configured:
        root_logger = logging.getLogger(LOGGER_NAME)
        root_logger.setLevel(effective_level)

        # Only add handler if none exist
        if not root_logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(effective_level)

            # Use cleaner format for INFO+, more detail for DEBUG
            if effective_level == "DEBUG":
                formatter = logging.Formatter(DEBUG_FORMAT)
            else:
                formatter = logging.Formatter(LOGGER_FORMAT)

            handler.setFormatter(formatter)
            root_logger.addHandler(handler)

        # Don't propagate to root logger
        root_logger.propagate = False
        _configured = True

    return logger


def set_log_level(level: str) -> None:
    """
    Dynamically change the log level for all MCP+ loggers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR)
    """
    level = level.upper()
    root_logger = logging.getLogger(LOGGER_NAME)
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
