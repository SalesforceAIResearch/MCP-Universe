"""
MCP Hybrid Mode Training for VERL Integration.

In hybrid mode, Actor and Rollout share the same GPUs.
"""

from .mcp_trainer import MCPPPOTrainer

__all__ = ["MCPPPOTrainer"]
