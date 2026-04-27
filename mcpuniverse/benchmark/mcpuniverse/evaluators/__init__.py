"""MCP-Universe paper benchmark: register compare_func evaluators (side effects on import)."""
# pylint: disable=unused-import
from .blender import functions as _blender_functions  # noqa: F401
from .github import functions as _github_functions  # noqa: F401
from .google_maps import functions as _google_maps_functions  # noqa: F401
from .google_search import functions as _google_search_functions  # noqa: F401
from .notion import functions as _notion_functions  # noqa: F401
from .playwright import functions as _playwright_functions  # noqa: F401
from .weather import functions as _weather_functions  # noqa: F401
from .yfinance import functions as _yfinance_functions  # noqa: F401
