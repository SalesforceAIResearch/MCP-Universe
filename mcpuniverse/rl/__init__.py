"""
MCP-Universe RL - Rollout engine for RL training.

Uses MCP-Universe's native Agent and LLM components.

Quick Start:
```python
from mcpuniverse.rl import RolloutEngine

engine = RolloutEngine.from_config("config.yaml")
output = await engine.run([{"instruction": "What's the weather?"}])
```
"""

from .core.config import (
    RolloutConfig,
    TrajectoryConfig,
    GeneratorConfig,
    DispatcherConfig,
    ServerConfig,
    AgentMode,
    EnvPoolConfig,
    DockerBuildConfig,
    ContainerResourceConfig,
)

from .core.trajectory import (
    Trajectory,
    create_trajectory,
    create_llm
)

from .core.pipeline import RolloutPipeline

from .runner import (
    RolloutEngine,
    RolloutOutput,
    rollout
)
from .core.types import (
    RolloutBatchResult,
    RolloutSample,
    TokenizedRolloutBatch,
    TrajectoryResult,
    TrajectoryStep,
    TraceData,
    TokenData,
)

from .core.formatters import (
    BaseFormatter,
    FormatterOutput,
    GptOssFormatter,
    get_formatter,
    FORMATTERS
)


__all__ = [
    # Config
    "RolloutConfig",
    "TrajectoryConfig",
    "GeneratorConfig",
    "DispatcherConfig",
    "ServerConfig",
    "AgentMode",
    "EnvPoolConfig",
    "DockerBuildConfig",
    "ContainerResourceConfig",

    # Trajectory
    "Trajectory",
    "TrajectoryResult",
    "TrajectoryStep",
    "TraceData",
    "TokenData",
    "create_trajectory",
    "create_llm",

    # Pipeline (unified batch + continuous dispatcher engine)
    "RolloutPipeline",

    # Runner
    "RolloutEngine",
    "RolloutOutput",
    "RolloutBatchResult",
    "RolloutSample",
    "TokenizedRolloutBatch",
    "rollout",

    # Formatters (model-specific prompt/output splitting)
    "BaseFormatter",
    "FormatterOutput",
    "GptOssFormatter",
    "get_formatter",
    "FORMATTERS",
]
