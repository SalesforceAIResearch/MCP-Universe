"""
MCP Fully Async Training for VERL Integration.

Provides a fully asynchronous training mode where Rollouter and Trainer
run in parallel, communicating via a MessageQueue. This maximizes GPU
utilization for MCP agent trajectories which can take minutes per batch.

Supports both FSDP/FSDP2 and Megatron training strategies.

Components:
  - MCPFullyAsyncRollouter: Continuous batch generation via MCPLoopManager
  - MCPFullyAsyncTrainer: Queue-consuming PPO trainer
  - MCPRolloutSample: Data class for individual rollout samples
  - MCPAsyncRolloutWorker: FSDP rollout worker with ServerAdapter-based weight sync
  - MCPMegatronAsyncRolloutWorker: Megatron rollout worker with ServerAdapter-based weight sync
  - MCPMegatronDetachActorWorker: Megatron actor worker with Bridge weight conversion
  - MCPParameterSynchronizer: Parameter synchronizer with actual NCCL weight sync
  - MCPAsyncTaskRunner: Orchestrator entry point

Usage:
    # FSDP mode
    python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \\
        --config-path=config --config-name=mcp_fully_async

    # Megatron mode
    python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \\
        --config-path=config --config-name=mcp_fully_async_megatron
"""

from .mcp_async_data import MCPRolloutSample, assemble_mcp_training_batch
from .mcp_async_rollouter import MCPFullyAsyncRollouter
from .mcp_async_trainer import MCPFullyAsyncTrainer
from .mcp_async_workers import MCPAsyncRolloutWorker
from .mcp_param_sync import MCPParameterSynchronizer
from .mcp_async_main import MCPAsyncTaskRunner

__all__ = [
    "MCPRolloutSample",
    "assemble_mcp_training_batch",
    "MCPFullyAsyncRollouter",
    "MCPFullyAsyncTrainer",
    "MCPAsyncRolloutWorker",
    "MCPParameterSynchronizer",
    "MCPAsyncTaskRunner",
]

try:
    from .mcp_megatron_async_workers import MCPMegatronAsyncRolloutWorker, MCPMegatronDetachActorWorker
    __all__ += ["MCPMegatronAsyncRolloutWorker", "MCPMegatronDetachActorWorker"]
except ImportError:
    pass
