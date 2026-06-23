"""Central registry for benchmark task preparation functions."""

from mcpuniverse.benchmark.configs.mcpmark.prepares import (  # noqa: F401
    PREPARE_FUNCTIONS,
    prepare_func,
)

__all__ = ["PREPARE_FUNCTIONS", "prepare_func"]
