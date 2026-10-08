"""Run a configured deep-research benchmark and persist traces and results.

Usage: python -m mcpuniverse.benchmark.deep_research --config benchmark.yaml
"""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv


async def run(config: str, output: str, resume: bool = False) -> list:
    """Use the standard benchmark runner, retaining its evaluator contracts."""
    # Load credentials before importing adapters whose defaults read the environment.
    load_dotenv()
    from mcpuniverse.benchmark.runner import BenchmarkRunner  # pylint: disable=import-outside-toplevel
    from mcpuniverse.tracer.collectors.file import FileCollector  # pylint: disable=import-outside-toplevel

    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    collector = FileCollector(str(destination / "traces.log"))
    results = await BenchmarkRunner(config).run(
        trace_collector=collector,
        store_folder=str(destination / "tasks"),
        overwrite=not resume,
    )
    serialized = [result.model_dump(mode="json") for result in results]
    (destination / "results.json").write_text(
        json.dumps(serialized, indent=2) + "\n", encoding="utf-8"
    )
    return serialized


def main() -> None:
    """Parse the benchmark configuration and output location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Standard MCP-Universe benchmark YAML")
    parser.add_argument("--output", default="results/deep-research")
    parser.add_argument("--resume", action="store_true", help="Reuse completed task results")
    args = parser.parse_args()
    asyncio.run(run(args.config, args.output, args.resume))


if __name__ == "__main__":
    main()
