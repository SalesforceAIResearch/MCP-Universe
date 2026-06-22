"""
MCPMark integration helpers (path setup).

Prepare handlers are registered in :mod:`mcpuniverse.benchmark.mcpmark.prepares`.
Cleanup handlers are registered in :mod:`mcpuniverse.benchmark.mcpmark.cleanups`.
This module intentionally defines no ``@prepare_func`` / ``@cleanup_func`` entries to
avoid duplicate registration with those packages.
"""
