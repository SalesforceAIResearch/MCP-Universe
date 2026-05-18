#!/bin/bash
# =============================================================================
# Openseeker Deep Research RL Training
#
# Steps:
#   1. Prepare data: sample N tasks, split into train/val
#   2. Verify Docker (gateway image is built lazily by EnvPoolManager)
#   3. Launch fully async training: ROLLOUT_GPUS + TRAINER_GPUS
#
# Prerequisites:
#   - GPUs: ROLLOUT_GPUS + TRAINER_GPUS available on one node (default 4 + 4)
#   - Docker daemon reachable (docker_pool transport spawns one container per
#     trajectory and mounts /var/run/docker.sock indirectly via the env pool)
#   - Environment variables for the 3 MCP servers (export these or set defaults
#     in your shell before invoking):
#       SERPER_API_KEY            - Serper web search
#       SERPER_BASE_URL           - default https://google.serper.dev
#       JINA_API_KEY              - Jina scraping
#       JINA_BASE_URL             - default https://r.jina.ai
#       SUMMARY_LLM_BASE_URL      - LLM endpoint used by jina-scrape-llm-summary
#       SUMMARY_LLM_MODEL_NAME    - e.g. gemini-2.5-flash
#       SUMMARY_LLM_API_KEY       - bearer token / api key for the summary LLM
#       SANDBOX_ADDRESS           - python-code-sandbox host
#       SANDBOX_HOST_PORT         - python-code-sandbox port
#       OPENAI_API_KEY            - REQUIRED: o3-mini judge in the HLE evaluator
#                                   (reward is silently 0 without it)
#   - Model weights accessible at MODEL_PATH
#   - verl and mcpuniverse installed (pip install -e ".[rl,vllm]")
#
# Required positional configuration (set as env vars):
#   MODEL_PATH               Path to base model weights (HF format)
#   OPENSEEKER_INPUT_DIR     Directory containing openseeker_*.json source tasks
#
# Optional knobs (with defaults shown):
#   DATA_OUTPUT_DIR=${PROJECT_DIR}/data/openseeker_100
#   NUM_SAMPLES=100   VAL_RATIO=0.1   SEED=42
#   TRAINER_GPUS=4    ROLLOUT_GPUS=4
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MODEL_PATH="${MODEL_PATH:-}"
OPENSEEKER_INPUT_DIR="${OPENSEEKER_INPUT_DIR:-}"
DATA_OUTPUT_DIR="${DATA_OUTPUT_DIR:-${PROJECT_DIR}/data/openseeker_100}"

NUM_SAMPLES="${NUM_SAMPLES:-100}"
VAL_RATIO="${VAL_RATIO:-0.1}"
SEED="${SEED:-42}"

TRAINER_GPUS="${TRAINER_GPUS:-4}"
ROLLOUT_GPUS="${ROLLOUT_GPUS:-4}"

MCP_SERVERS="serper-search,jina-scrape-llm-summary,python-code-sandbox"

# ── MCP server defaults (only URLs / non-secrets) ────────────────────────────
export SERPER_BASE_URL="${SERPER_BASE_URL:-https://google.serper.dev}"
export JINA_BASE_URL="${JINA_BASE_URL:-https://r.jina.ai}"

# vLLM SageMaker workaround (harmless if unused by your verl build)
export SAGEMAKER_MODEL_PATH="${SAGEMAKER_MODEL_PATH:-/tmp/vllm_sagemaker_model}"

# VERL config path (needed by Hydra to find ppo_trainer base config). The
# openseeker yaml references this via ${oc.env:VERL_CONFIG_PATH}.
export VERL_CONFIG_PATH="${VERL_CONFIG_PATH:-$(python3 -c 'import verl, os; print(os.path.join(os.path.dirname(verl.__file__), "trainer", "config"))' 2>/dev/null || true)}"
if [ -z "${VERL_CONFIG_PATH}" ]; then
    echo "ERROR: could not locate verl's trainer config dir."
    echo "  Install verl into the active environment, or export VERL_CONFIG_PATH=/path/to/verl/verl/trainer/config"
    exit 1
fi

# Cleanup on exit: stop any leftover docker_pool containers
cleanup() {
    echo ""
    echo "Cleaning up mcp-env-* containers..."
    docker ps -q  --filter "label=mcp.managed=true" | xargs -r docker stop  2>/dev/null || true
    docker ps -aq --filter "label=mcp.managed=true" | xargs -r docker rm -f 2>/dev/null || true
    echo "  Done."
}
trap cleanup EXIT INT TERM

# ── Validate required env vars ───────────────────────────────────────────────
require() {
    local name="$1"
    if [ -z "${!name:-}" ]; then
        echo "ERROR: ${name} is not set."
        exit 1
    fi
}
require MODEL_PATH
require OPENSEEKER_INPUT_DIR
require SERPER_API_KEY
require JINA_API_KEY
require SUMMARY_LLM_BASE_URL
require SUMMARY_LLM_MODEL_NAME
require SUMMARY_LLM_API_KEY
require SANDBOX_ADDRESS
require SANDBOX_HOST_PORT
require OPENAI_API_KEY

if [ ! -d "${MODEL_PATH}" ]; then
    echo "ERROR: MODEL_PATH does not exist: ${MODEL_PATH}"
    exit 1
fi

# ── Step 1: Prepare Data ─────────────────────────────────────────────────────
echo "============================================"
echo "Step 1: Preparing openseeker data"
echo "  Input:   ${OPENSEEKER_INPUT_DIR}"
echo "  Output:  ${DATA_OUTPUT_DIR}"
echo "  Samples: ${NUM_SAMPLES} (val_ratio=${VAL_RATIO})"
echo "============================================"

python3 "${SCRIPT_DIR}/prepare_openseeker_data.py" \
    --input_dir "${OPENSEEKER_INPUT_DIR}" \
    --output_dir "${DATA_OUTPUT_DIR}" \
    --num_samples "${NUM_SAMPLES}" \
    --val_ratio "${VAL_RATIO}" \
    --seed "${SEED}"

TRAIN_FILE="${DATA_OUTPUT_DIR}/train.json"
VAL_FILE="${DATA_OUTPUT_DIR}/val.json"

echo ""
echo "Data prepared:"
echo "  Train: ${TRAIN_FILE}"
echo "  Val:   ${VAL_FILE}"
echo ""

# ── Step 2: Verify prerequisites ─────────────────────────────────────────────
echo "============================================"
echo "Step 2: Checking prerequisites"
echo "============================================"

echo "  MCP server env vars (truncated):"
echo "    SERPER_API_KEY:         ${SERPER_API_KEY:0:6}..."
echo "    JINA_API_KEY:           ${JINA_API_KEY:0:6}..."
echo "    SUMMARY_LLM_BASE_URL:   ${SUMMARY_LLM_BASE_URL:0:40}..."
echo "    SUMMARY_LLM_MODEL_NAME: ${SUMMARY_LLM_MODEL_NAME}"
echo "    SANDBOX_ADDRESS:        ${SANDBOX_ADDRESS}:${SANDBOX_HOST_PORT}"

GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l || echo 0)
REQUIRED_GPUS=$((TRAINER_GPUS + ROLLOUT_GPUS))
echo "  GPUs available: ${GPU_COUNT}"
echo "  GPUs required:  ${REQUIRED_GPUS} (${ROLLOUT_GPUS} rollout + ${TRAINER_GPUS} training)"
if [ "${GPU_COUNT}" -lt "${REQUIRED_GPUS}" ]; then
    echo "ERROR: Not enough GPUs. Need ${REQUIRED_GPUS}, found ${GPU_COUNT}."
    exit 1
fi
echo "  Prerequisites OK"
echo ""

# ── Step 3: Verify Docker for docker_pool transport ─────────────────────────
echo "============================================"
echo "Step 3: Checking Docker (docker_pool transport)"
echo "  Servers: ${MCP_SERVERS}"
echo "  Image:   mcp-universe/gateway:latest"
echo "============================================"

if ! docker info &>/dev/null; then
    echo "ERROR: Docker is not running or not accessible."
    exit 1
fi

if ! docker image inspect mcp-universe/gateway:latest &>/dev/null; then
    echo "  Gateway image not found. Building..."
    docker build -f "${PROJECT_DIR}/docker/gateway/Dockerfile" -t mcp-universe/gateway:latest "${PROJECT_DIR}"
fi
echo "  Docker OK. Containers will be managed by EnvPoolManager."

# Clean up any stale mcp-env containers from previous runs
docker ps -aq --filter "label=mcp.managed=true" | xargs -r docker rm -f 2>/dev/null || true
echo ""

# ── Step 4: Launch Training ──────────────────────────────────────────────────
echo "============================================"
echo "Step 4: Starting fully async training (docker_pool)"
echo "  Model:        ${MODEL_PATH}"
echo "  Config:       openseeker_deepresearch_async"
echo "  Rollout GPUs: ${ROLLOUT_GPUS}"
echo "  Trainer GPUs: ${TRAINER_GPUS}"
echo "  MCP Transport: docker_pool"
echo "  VERL config:  ${VERL_CONFIG_PATH}"
echo "============================================"
echo ""

cd "${PROJECT_DIR}"

CONFIG_DIR="$(cd "${PROJECT_DIR}/mcpuniverse/rl/integrations/verl/config" && pwd)"

python -m mcpuniverse.rl.integrations.verl.fully_async.mcp_async_main \
    --config-path="${CONFIG_DIR}" \
    --config-name=openseeker_deepresearch_async \
    actor_rollout_ref.model.path="${MODEL_PATH}" \
    data.train_files="${TRAIN_FILE}" \
    data.val_files="${VAL_FILE}" \
    trainer.n_gpus_per_node="${TRAINER_GPUS}" \
    rollout.n_gpus_per_node="${ROLLOUT_GPUS}" \
    actor_rollout_ref.model.use_fused_kernels=true \
    ++actor_rollout_ref.model.fused_kernel_options.impl_backend=torch \
    ++algorithm.rollout_correction.bypass_mode=true \
    actor_rollout_ref.actor.ppo_max_token_len_per_gpu=81920 \
    actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
    data.max_prompt_length=81920 \
    data.max_response_length=81920 \
    actor_rollout_ref.rollout.prompt_length=81920 \
    actor_rollout_ref.rollout.response_length=81920 \
    actor_rollout_ref.rollout.max_model_len=81920
# ── Notes on the trailing overrides ───────────────────────────────────────────
# These overrides were determined by trial-and-error to make the 20B model fit
# on 4 training GPUs (~21GB free per GPU after FSDP-sharded model + Adam states).
# Without them the run OOMs during compute_log_prob. See deep-research-readme.md
# §"Critical Launch Script Overrides" for the full rationale.
#   - use_fused_kernels + impl_backend=torch : avoid materializing the full
#     [seq_len, vocab_size] logits tensor (62GB for 128K x 131K vocab).
#   - bypass_mode=true : reuse rollout log-probs as old_log_probs so we skip the
#     extra compute_log_prob forward pass entirely.
#   - ppo_micro_batch_size_per_gpu=1 : prevent FSDP desync from per-worker
#     dynamic packing producing different micro-batch counts (NCCL timeouts).
#   - max_*_length=81920 : cap sequence length so a single forward pass fits
#     within the per-GPU memory budget with fused kernels.
