"""
Resolve benchmark runner configs and suite paths from ``benchmark_id``.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Optional


def benchmark_package_dir() -> str:
    """Directory containing ``bundle.py`` (the ``mcpuniverse.benchmark`` package root)."""
    return str(Path(__file__).resolve().parent)


def resolve_runner_config_file(config: str) -> str:
    """
    Resolve a user-supplied config path to an absolute path of an existing file.

    Search order: path as given if it exists, else ``mcpuniverse/benchmark/<relpath>``.
    """
    benchmark_pkg = benchmark_package_dir()
    if os.path.isfile(config):
        return os.path.abspath(config)
    candidate = os.path.join(benchmark_pkg, config)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    raise ValueError(f"Cannot find config file: {config}")


def suite_task_config_root(benchmark_id: str) -> Optional[str]:
    """``.../mcpuniverse/benchmark/<benchmark_id>/task_configs`` if that directory exists."""
    if not benchmark_id:
        return None
    root = os.path.join(benchmark_package_dir(), benchmark_id, "task_configs")
    return os.path.abspath(root) if os.path.isdir(root) else None


def suite_server_list_path(benchmark_id: str) -> Optional[str]:
    """``.../mcpuniverse/benchmark/<benchmark_id>/server_list.json`` if that file exists."""
    if not benchmark_id:
        return None
    path = os.path.join(benchmark_package_dir(), benchmark_id, "server_list.json")
    return os.path.abspath(path) if os.path.isfile(path) else None


def load_benchmark_package(bundle_id: str) -> None:
    """Import ``mcpuniverse.benchmark.<bundle_id>`` if it exists (bundle ``__init__`` hooks)."""
    if not bundle_id or bundle_id in {"configs", "benchmark"}:
        return
    modname = f"mcpuniverse.benchmark.{bundle_id}"
    try:
        importlib.import_module(modname)
    except ImportError:
        pass
