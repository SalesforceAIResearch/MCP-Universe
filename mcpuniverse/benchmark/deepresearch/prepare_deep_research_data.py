#!/usr/bin/env python3
"""
CLI to download Deep Research benchmarks and transform them to the benchmark
task JSON format. Supports gaia-benchmark/GAIA, cais/hle, and smolagents/browse_comp.

Run with: python -m mcpuniverse.benchmark.deepresearch.prepare_deep_research_data
"""

import argparse

from mcpuniverse.benchmark.deepresearch.data_utils import (
    process_browse_comp_dataset,
    process_gaia_dataset,
    process_hle_dataset,
)


def main():
    """Parse arguments and run the selected dataset processor."""
    parser = argparse.ArgumentParser(
        description="Transform dataset to benchmark task format"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        choices=["gaia", "hle", "browse_comp", "all"],
        default="gaia",
        help="Dataset to transform",
    )
    parser.add_argument(
        "--tools",
        type=str,
        default="serper-search,jina-scrape-llm-summary",
        help=(
            "Comma-separated list of tool names (e.g., 'serper-search,jina-scrape-llm-summary'). "
            "Uses dataset defaults if not provided."
        ),
    )
    parser.add_argument(
        "--special_name",
        type=str,
        default=None,
        help=(
            "Special name to add to folder name (before date) and filename "
            "(before number). If not provided, no special name is added."
        ),
    )
    parser.add_argument(
        "--exclude_output_format",
        action="store_true",
        help="Exclude output_format from generated task files. Default: include it.",
    )
    args = parser.parse_args()
    output_format = not args.exclude_output_format

    tools = None
    if args.tools:
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
        print(f"Using tools from command line: {tools}")

    dataset_funcs = [
        (
            "gaia",
            lambda: process_gaia_dataset(
                tools=tools,
                special_name=args.special_name,
                output_format=output_format,
            ),
        ),
        (
            "hle",
            lambda: process_hle_dataset(
                tools=tools,
                special_name=args.special_name,
                output_format=output_format,
            ),
        ),
        (
            "browse_comp",
            lambda: process_browse_comp_dataset(
                tools=tools,
                special_name=args.special_name,
                output_format=output_format,
            ),
        ),
    ]

    if args.dataset == "all":
        for _, func in dataset_funcs:
            func()
            print("\n" + "=" * 80 + "\n")
    else:
        for name, func in dataset_funcs:
            if args.dataset == name:
                func()
                break


if __name__ == "__main__":
    main()
