#!/bin/bash

# Script to run all JSON task files from a folder in parallel using the new config-based test script
# Usage: ./test_deepresearch_paralell_config.sh [benchmark_yaml] [task_folder] [num_processes] [special_name] [limit|start] [end]
#   - benchmark_yaml: Path to the benchmark YAML config file (required)
#   - task_folder: Folder containing JSON task files (default: mcpuniverse/benchmark/deepresearch/task_yamls/browse_comp_2025_11_19)
#   - num_processes: Number of parallel processes (default: 10)
#   - special_name: Special name for the benchmark run (optional)
#   - Range mode: If both arg 5 and arg 6 are numbers, process files from start to end (inclusive)
#   - Limit mode: If only arg 5 is a number, process first N files

# Get the benchmark YAML path from first argument (required)
BENCHMARK_YAML="${1:-}"
if [ -z "$BENCHMARK_YAML" ]; then
    echo "Error: Benchmark YAML path is required as first argument"
    echo "Usage: $0 <benchmark_yaml> [task_folder] [num_processes] [special_name] [limit|start] [end]"
    exit 1
fi

# Get the task folder path from second argument or use default
TASK_FOLDER="${2:-mcpuniverse/benchmark/deepresearch/task_yamls/browse_comp_2025_11_19}"
# Get the number of parallel processes from third argument (optional, default 10)
NUM_PROCESSES="${3:-10}"
# Get the special name from fourth argument (optional)
SPECIAL_NAME="${4:-}"
# Get the limit/start from fifth argument (optional)
ARG5="${5:-}"
# Get the end from sixth argument (optional)
ARG6="${6:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Change to project root directory
cd "$PROJECT_ROOT"

# Check if benchmark YAML exists
if [ ! -f "$BENCHMARK_YAML" ]; then
    echo "Error: Benchmark YAML file '$BENCHMARK_YAML' does not exist"
    exit 1
fi

# Check if task folder exists
if [ ! -d "$TASK_FOLDER" ]; then
    echo "Error: Task folder '$TASK_FOLDER' does not exist"
    exit 1
fi

# Function to build and execute the command for a single task file
run_task() {
    local task_path="$1"
    python tests/benchmark/test_benchmark_deepresearch_config.py "$BENCHMARK_YAML" "$SPECIAL_NAME" "$task_path"
}
export -f run_task
export BENCHMARK_YAML SPECIAL_NAME

# Check if both arg5 and arg6 are numbers (range mode)
if [ -n "$ARG5" ] && [ -n "$ARG6" ] && [[ "$ARG5" =~ ^[0-9]+$ ]] && [[ "$ARG6" =~ ^[0-9]+$ ]]; then
    # Range mode: process files from START to END (inclusive)
    START="$ARG5"
    END="$ARG6"
    
    if [ "$START" -gt "$END" ]; then
        echo "Error: Start position ($START) must be less than or equal to end position ($END)"
        exit 1
    fi
    
    echo "Using $NUM_PROCESSES parallel processes"
    echo "Processing JSON task files from position $START to $END (inclusive) from '$TASK_FOLDER'"
    echo "Benchmark YAML: $BENCHMARK_YAML"
    [ -n "$SPECIAL_NAME" ] && echo "Special name: $SPECIAL_NAME"
    
    # Get total count of files
    TOTAL_FILES=$(find "$TASK_FOLDER" -name "*.json" -type f | wc -l)
    
    if [ "$END" -gt "$TOTAL_FILES" ]; then
        echo "Warning: End position ($END) exceeds total number of files ($TOTAL_FILES). Processing up to file $TOTAL_FILES."
        END="$TOTAL_FILES"
    fi
    
    # Use sed to extract lines from START to END (inclusive), then process each file
    find "$TASK_FOLDER" -name "*.json" -type f | sort | sed -n "${START},${END}p" | \
        xargs -P "$NUM_PROCESSES" -I {} bash -c 'run_task "{}"'
elif [ -n "$ARG5" ] && [[ "$ARG5" =~ ^[0-9]+$ ]]; then
    # Limit mode: process first N files
    LIMIT="$ARG5"
    
    echo "Using $NUM_PROCESSES parallel processes"
    echo "Processing first $LIMIT JSON task files from '$TASK_FOLDER'"
    echo "Benchmark YAML: $BENCHMARK_YAML"
    [ -n "$SPECIAL_NAME" ] && echo "Special name: $SPECIAL_NAME"
    
    find "$TASK_FOLDER" -name "*.json" -type f | sort | head -n "$LIMIT" | \
        xargs -P "$NUM_PROCESSES" -I {} bash -c 'run_task "{}"'
else
    # No limit: process all files
    echo "Using $NUM_PROCESSES parallel processes"
    echo "Processing all JSON task files from '$TASK_FOLDER'"
    echo "Benchmark YAML: $BENCHMARK_YAML"
    [ -n "$SPECIAL_NAME" ] && echo "Special name: $SPECIAL_NAME"
    
    find "$TASK_FOLDER" -name "*.json" -type f | sort | \
        xargs -P "$NUM_PROCESSES" -I {} bash -c 'run_task "{}"'
fi

echo "All JSON task files processed"

