"""
MCPMark evaluator functions package.

This package provides function definitions for various MCP services
used in the MCPMark evaluation framework.
"""
import logging

logger = logging.getLogger(__name__)

# Import evaluators with optional dependency handling
try:
    from .github_functions import *
except ImportError as e:
    logger.debug(f"GitHub evaluator functions not available: {e}")

try:
    from .notion_functions import *
except ImportError as e:
    logger.debug(f"Notion evaluator functions not available: {e}")

try:
    from .filesystem_functions import *
except ImportError as e:
    logger.debug(f"Filesystem evaluator functions not available: {e}")

try:
    from .playwright_functions import *
except ImportError as e:
    logger.debug(f"Playwright evaluator functions not available: {e}")

try:
    from .postgres_functions import *
except ImportError as e:
    logger.debug(f"Postgres evaluator functions not available: {e}")
