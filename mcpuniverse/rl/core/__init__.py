"""Framework-neutral core of the MCP-Universe RL rollout engine.

Submodules:
    config            - rollout / dispatcher / env-pool configuration dataclasses
    types             - data protocols (RolloutSample, TrajectoryResult, ...)
    trajectory        - single-trajectory lifecycle
    pipeline          - concurrent init -> run -> eval execution (RolloutPipeline)
    rollout           - orchestration glue (samples in, tokenized batch out)
    postprocess       - tokenization + metrics collection
    env_pool_runtime  - shared docker / apptainer env-pool runtime
    trace_logger      - JSONL trajectory trace logging
    formatters        - model-specific prompt/output splitting
"""
