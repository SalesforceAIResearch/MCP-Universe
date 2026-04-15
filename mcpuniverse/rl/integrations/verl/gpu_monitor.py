"""
GPU utilization monitor for RL training.

Polls nvidia-smi at regular intervals and correlates GPU util with training
stages by parsing the training log. Outputs a CSV and optionally logs to wandb.

Usage:
    python -m mcpuniverse.rl.integrations.verl.gpu_monitor \
        --log-file /tmp/rl_training_500.log \
        --output /tmp/gpu_util.csv \
        --interval 2 \
        [--wandb-project mcp-u-rl --wandb-run y-finance-gpu-monitor]
"""

import argparse
import csv
import os
import re
import subprocess
import time
from datetime import datetime


# Stage detection patterns (matched against training log lines)
STAGE_PATTERNS = [
    (r"Starting validation", "validation"),
    (r"Validation generation complete", "validation_done"),
    (r"val_before_train.*Running initial", "val_before_train"),
    (r"update_weights done", "weight_sync"),
    (r"generate_sequences|agent_loop.*generate|Pipeline: \d+ trajectories", "rollout"),
    (r"Pipeline complete", "rollout_done"),
    (r"compute_log_prob|old_log_prob", "log_prob"),
    (r"compute_advantage|adv_estimator", "advantage"),
    (r"update_actor|actor.*grad_norm", "actor_update"),
    (r"sleep_replicas", "sleep"),
    (r"MCP PPO Training:.*\d+%", "training_step"),
    (r"step:\d+", "step_summary"),
]


def get_gpu_stats():
    """Query nvidia-smi for per-GPU utilization and memory."""
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "index": int(parts[0]),
                    "gpu_util": float(parts[1]),
                    "mem_util": float(parts[2]),
                    "mem_used_mb": float(parts[3]),
                    "mem_total_mb": float(parts[4]),
                    "power_w": float(parts[5]) if parts[5] != "[N/A]" else 0,
                })
        return gpus
    except Exception:
        return []


def detect_stage(log_file, last_pos):
    """Read new lines from the log file and detect the current training stage."""
    stage = None
    try:
        with open(log_file, "r") as f:
            f.seek(last_pos)
            new_lines = f.read()
            new_pos = f.tell()

        for pattern, name in STAGE_PATTERNS:
            if re.search(pattern, new_lines):
                stage = name

        return stage, new_pos
    except Exception:
        return None, last_pos


def main():
    parser = argparse.ArgumentParser(description="GPU utilization monitor for RL training")
    parser.add_argument("--log-file", type=str, default="/tmp/rl_training_500.log",
                        help="Training log file to parse for stage detection")
    parser.add_argument("--output", type=str, default="/tmp/gpu_util.csv",
                        help="Output CSV path")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Polling interval in seconds")
    parser.add_argument("--wandb-project", type=str, default=None,
                        help="Wandb project name (enables wandb logging)")
    parser.add_argument("--wandb-run", type=str, default=None,
                        help="Wandb run name")
    args = parser.parse_args()

    # Optional wandb
    wandb_run = None
    if args.wandb_project:
        import wandb
        wandb_run = wandb.init(
            project=args.wandb_project,
            name=args.wandb_run or f"gpu-monitor-{datetime.now().strftime('%Y%m%d-%H%M')}",
            tags=["gpu-monitor"],
        )

    # CSV output
    csv_file = open(args.output, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow([
        "timestamp", "wall_time_s", "stage",
        "gpu_util_mean", "gpu_util_max", "mem_util_mean",
        "mem_used_gb_mean", "power_w_total",
        # Per-GPU columns
        *[f"gpu{i}_util" for i in range(8)],
        *[f"gpu{i}_mem_used_gb" for i in range(8)],
    ])

    start_time = time.time()
    last_log_pos = 0
    current_stage = "init"
    step_count = 0

    print(f"GPU monitor started. Polling every {args.interval}s")
    print(f"  Log file: {args.log_file}")
    print(f"  Output CSV: {args.output}")
    if wandb_run:
        print(f"  Wandb: {wandb_run.url}")

    try:
        while True:
            wall_time = time.time() - start_time
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Detect training stage from log
            new_stage, last_log_pos = detect_stage(args.log_file, last_log_pos)
            if new_stage:
                if new_stage == "step_summary":
                    step_count += 1
                current_stage = new_stage

            # Get GPU stats
            gpus = get_gpu_stats()
            if not gpus:
                time.sleep(args.interval)
                continue

            # Aggregate
            gpu_utils = [g["gpu_util"] for g in gpus]
            mem_utils = [g["mem_util"] for g in gpus]
            mem_used = [g["mem_used_mb"] / 1024 for g in gpus]
            power = sum(g["power_w"] for g in gpus)

            gpu_util_mean = sum(gpu_utils) / len(gpu_utils)
            gpu_util_max = max(gpu_utils)
            mem_util_mean = sum(mem_utils) / len(mem_utils)
            mem_used_mean = sum(mem_used) / len(mem_used)

            # Pad to 8 GPUs
            per_gpu_util = (gpu_utils + [0] * 8)[:8]
            per_gpu_mem = (mem_used + [0] * 8)[:8]

            # Write CSV
            writer.writerow([
                timestamp, f"{wall_time:.1f}", current_stage,
                f"{gpu_util_mean:.1f}", f"{gpu_util_max:.1f}", f"{mem_util_mean:.1f}",
                f"{mem_used_mean:.2f}", f"{power:.1f}",
                *[f"{u:.1f}" for u in per_gpu_util],
                *[f"{m:.2f}" for m in per_gpu_mem],
            ])
            csv_file.flush()

            # Wandb log
            if wandb_run:
                log_data = {
                    "gpu/util_mean": gpu_util_mean,
                    "gpu/util_max": gpu_util_max,
                    "gpu/mem_util_mean": mem_util_mean,
                    "gpu/mem_used_gb_mean": mem_used_mean,
                    "gpu/power_w_total": power,
                    "training/stage_id": hash(current_stage) % 100,
                    "training/step": step_count,
                }
                for i, g in enumerate(gpus):
                    log_data[f"gpu/gpu{i}_util"] = g["gpu_util"]
                    log_data[f"gpu/gpu{i}_mem_gb"] = g["mem_used_mb"] / 1024
                wandb_run.log(log_data)

            # Print summary every 30s
            if int(wall_time) % 30 < args.interval:
                print(f"[{timestamp}] stage={current_stage} step={step_count} "
                      f"gpu_util={gpu_util_mean:.0f}% mem={mem_used_mean:.1f}GB "
                      f"power={power:.0f}W")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        csv_file.close()
        if wandb_run:
            wandb_run.finish()
        print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
