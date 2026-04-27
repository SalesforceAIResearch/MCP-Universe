"""
Resolve isolated benchmark bundles (server_list, task_configs) from a runner YAML path.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BenchmarkBundle:
    """Filesystem layout for one benchmark under ``mcpuniverse/benchmark/<id>/``."""

    root: str
    task_config_root: str
    bundle_id: str
    server_list_path: Optional[str]

    @property
    def has_server_list(self) -> bool:
        return bool(self.server_list_path and os.path.isfile(self.server_list_path))


def benchmark_package_dir() -> str:
    """Directory containing ``bundle.py`` (the ``mcpuniverse.benchmark`` package root)."""
    return str(Path(__file__).resolve().parent)


def resolve_runner_config_file(config: str) -> str:
    """
    Resolve a user-supplied config path to an absolute path of an existing file.

    Search order: as given, then ``mcpuniverse/benchmark/<relpath>``, then
    ``mcpuniverse/benchmark/configs/<relpath>`` (legacy).
    """
    benchmark_pkg = benchmark_package_dir()
    configs_dir = os.path.join(benchmark_pkg, "configs")
    if os.path.isfile(config):
        return os.path.abspath(config)
    candidate = os.path.join(benchmark_pkg, config)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    candidate = os.path.join(configs_dir, config)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    raise ValueError(f"Cannot find config file: {config}")


def infer_benchmark_bundle(resolved_config_path: str) -> Optional[BenchmarkBundle]:
    """
    If ``resolved_config_path`` lies under a directory that contains ``task_configs/``,
    treat that directory as an isolated benchmark bundle root.

    Paths under ``benchmark/configs/`` are ignored (legacy layout uses ``tasks/`` there).
    """
    abs_cfg = os.path.abspath(resolved_config_path)
    benchmark_pkg = benchmark_package_dir()
    prefix = benchmark_pkg + os.sep
    if not abs_cfg.startswith(prefix):
        return None

    current = os.path.dirname(abs_cfg)
    pkg_prefix = benchmark_pkg + os.sep
    while True:
        inside_pkg = current == benchmark_pkg or current.startswith(pkg_prefix)
        if not inside_pkg:
            break
        try:
            rel = os.path.relpath(current, benchmark_pkg)
        except ValueError:
            break
        if rel.startswith(".."):
            break
        parts = rel.split(os.sep)
        # Legacy: ``benchmark/configs/<suite>/...`` — never treat as a bundle root.
        if parts[0] == "configs":
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
            continue

        task_configs = os.path.join(current, "task_configs")
        if os.path.isdir(task_configs):
            bundle_id = os.path.basename(current)
            sl = os.path.join(current, "server_list.json")
            return BenchmarkBundle(
                root=os.path.abspath(current),
                task_config_root=os.path.abspath(task_configs),
                bundle_id=bundle_id,
                server_list_path=os.path.abspath(sl) if os.path.isfile(sl) else None,
            )
        if current == benchmark_pkg:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def load_benchmark_package(bundle_id: str) -> None:
    """Import ``mcpuniverse.benchmark.<bundle_id>`` if it exists (bundle ``__init__`` hooks)."""
    if not bundle_id or bundle_id in {"configs", "benchmark"}:
        return
    modname = f"mcpuniverse.benchmark.{bundle_id}"
    try:
        importlib.import_module(modname)
    except ImportError:
        pass
