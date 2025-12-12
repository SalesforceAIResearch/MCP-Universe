"""
MCP-Plus: Intelligent output filtering for MCP servers.

This module provides tools to wrap existing MCP servers with LLM-powered
post-processing that intelligently filters long tool outputs to extract
only the relevant information.

Usage:
    pip install mcpuniverse
    export OPENAI_API_KEY=sk-...
    mcp-build-plus --mcp-config ~/.cursor/mcp.json
"""

__version__ = "0.1.0"
