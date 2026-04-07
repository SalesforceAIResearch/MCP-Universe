"""
VERL Integration for MCP-Universe.

Provides two training modes:
1. Hybrid Mode (MCPPPOTrainer): Actor and Rollout share GPUs
2. Fully Async Mode (MCPFullyAsyncTrainer + MCPFullyAsyncRollouter):
   Decoupled trainer and rollouter via MessageQueue for parallel execution

Fully Async Mode is recommended for:
- MCP agent trajectories that take minutes per batch (multi-turn tool calls)
- Maximum GPU utilization (trainer never waits for rollout)
"""

from .mcp_backend import MCPGeneratorInput, MCPGeneratorOutput
from .mcp_loop_manager import MCPLoopManager
from .hybrid.mcp_trainer import MCPPPOTrainer
from .mcp_reward_manager import MCPRewardManager
from .mcp_dataset import MCPDataset, create_mcp_dataset, mcp_collate_fn

__all__ = [
    # Core components
    "MCPGeneratorInput",
    "MCPGeneratorOutput",
    "MCPLoopManager",
    "MCPRewardManager",
    "MCPDataset",
    "create_mcp_dataset",
    "mcp_collate_fn",

    # Hybrid mode trainer
    "MCPPPOTrainer",
]

# Fully async mode (optional — module may not exist yet)
try:
    from .fully_async import (
        MCPFullyAsyncRollouter,
        MCPFullyAsyncTrainer,
        MCPAsyncTaskRunner,
        MCPRolloutSample,
        assemble_mcp_training_batch,
    )
    __all__ += [
        "MCPFullyAsyncRollouter",
        "MCPFullyAsyncTrainer",
        "MCPAsyncTaskRunner",
        "MCPRolloutSample",
        "assemble_mcp_training_batch",
    ]
except ImportError:
    pass
