"""VERL integration for MCP-Universe."""

from .data_proto_adapter import (
    data_proto_to_rollout_samples,
    tokenized_rollout_batch_to_data_proto,
)
from .mcp_loop_manager import MCPLoopManager
from .hybrid.mcp_trainer import MCPPPOTrainer
from .mcp_reward_manager import MCPRewardManager
from .mcp_dataset import MCPDataset, create_mcp_dataset, mcp_collate_fn

_FULLY_ASYNC_EXPORTS = {
    "MCPFullyAsyncRollouter",
    "MCPFullyAsyncTrainer",
    "MCPAsyncTaskRunner",
    "MCPRolloutSample",
    "assemble_mcp_training_batch",
}

__all__ = [
    # Core components
    "data_proto_to_rollout_samples",
    "tokenized_rollout_batch_to_data_proto",
    "MCPLoopManager",
    "MCPRewardManager",
    "MCPDataset",
    "create_mcp_dataset",
    "mcp_collate_fn",

    # Hybrid mode trainer
    "MCPPPOTrainer",
] + sorted(_FULLY_ASYNC_EXPORTS)


def __getattr__(name):
    """Import fully async components lazily to avoid train-mode side effects."""
    if name not in _FULLY_ASYNC_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .fully_async import (  # pylint: disable=import-outside-toplevel
        MCPFullyAsyncRollouter,
        MCPFullyAsyncTrainer,
        MCPAsyncTaskRunner,
        MCPRolloutSample,
        assemble_mcp_training_batch,
    )

    exports = {
        "MCPFullyAsyncRollouter": MCPFullyAsyncRollouter,
        "MCPFullyAsyncTrainer": MCPFullyAsyncTrainer,
        "MCPAsyncTaskRunner": MCPAsyncTaskRunner,
        "MCPRolloutSample": MCPRolloutSample,
        "assemble_mcp_training_batch": assemble_mcp_training_batch,
    }
    globals().update(exports)
    return exports[name]
