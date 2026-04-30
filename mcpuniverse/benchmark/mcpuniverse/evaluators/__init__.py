"""MCP-Universe paper benchmark: register compare_func evaluators (side effects on import)."""
# pylint: disable=unused-import
import logging

logger = logging.getLogger(__name__)

# Import evaluators with optional dependency handling
try:
    from .blender import functions as _blender_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Blender evaluator not available: {e}")

try:
    from .github import functions as _github_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"GitHub evaluator not available: {e}")

try:
    from .google_maps import functions as _google_maps_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Google Maps evaluator not available: {e}")

try:
    from .google_search import functions as _google_search_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Google Search evaluator not available: {e}")

try:
    from .notion import functions as _notion_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Notion evaluator not available: {e}")

try:
    from .playwright import functions as _playwright_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Playwright evaluator not available: {e}")

try:
    from .weather import functions as _weather_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"Weather evaluator not available: {e}")

try:
    from .yfinance import functions as _yfinance_functions  # noqa: F401
except ImportError as e:
    logger.debug(f"YFinance evaluator not available: {e}")
