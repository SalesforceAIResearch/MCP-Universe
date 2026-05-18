"""
Sample tasks from openseeker_distill and prepare training/validation JSON
for MCPDataset (VERL integration).

Usage:
    python scripts/prepare_openseeker_data.py \
        --input_dir /path/to/openseeker_distill \
        --output_dir /path/to/data/openseeker_100 \
        --num_samples 100 \
        --val_ratio 0.1 \
        --seed 42
"""

import argparse
import json
import os
import random
import glob


MCP_SERVERS = [
    {"name": "serper-search"},
    {"name": "jina-scrape-llm-summary"},
    {"name": "python-code-sandbox"},
]


def transform_task(task: dict, idx: int) -> dict:
    """Transform openseeker task format to MCPDataset format."""
    return {
        "instance_id": f"openseeker_{idx:06d}",
        "instruction": task["question"],
        "output_format": task.get("output_format", {"answer": "[Your answer]"}),
        "category": task.get("category", "general"),
        "mcp_servers": MCP_SERVERS,
        "evaluators": task.get("evaluators", []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--num_samples", type=int, default=100)
    parser.add_argument("--val_ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    files = sorted(glob.glob(os.path.join(args.input_dir, "openseeker_*.json")))
    print(f"Found {len(files)} openseeker files")

    sampled_files = random.sample(files, min(args.num_samples, len(files)))
    print(f"Sampled {len(sampled_files)} files")

    tasks = []
    for i, fpath in enumerate(sampled_files):
        with open(fpath, "r", encoding="utf-8") as f:
            task = json.load(f)
        tasks.append(transform_task(task, i))

    random.shuffle(tasks)
    val_count = max(1, int(len(tasks) * args.val_ratio))
    val_tasks = tasks[:val_count]
    train_tasks = tasks[val_count:]

    os.makedirs(args.output_dir, exist_ok=True)

    train_path = os.path.join(args.output_dir, "train.json")
    val_path = os.path.join(args.output_dir, "val.json")

    with open(train_path, "w", encoding="utf-8") as f:
        json.dump(train_tasks, f, indent=2)

    with open(val_path, "w", encoding="utf-8") as f:
        json.dump(val_tasks, f, indent=2)

    print(f"Train: {len(train_tasks)} samples -> {train_path}")
    print(f"Val:   {len(val_tasks)} samples -> {val_path}")


if __name__ == "__main__":
    main()
