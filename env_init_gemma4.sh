#!/bin/bash
# =============================================================================
# MCP-Universe — Gemma 4 Environment Setup
# =============================================================================
#
# Gemma 4 models (google/gemma-4-31B-it, google/gemma-4-26B-A4B-it) require
# newer versions of vLLM and transformers than the default MCP-Universe stack.
#
# WHAT'S DIFFERENT FROM THE DEFAULT SETUP (pyproject.toml):
#   - vLLM:         0.19.0  (default project uses >=0.15.0)
#   - torch:        2.10.0  (default uses >=2.6.0)
#   - transformers: >=5.5.0 from source (default uses what vllm pulls in)
#   - openai-harmony: 0.0.8 (auto-installed with vLLM 0.19.0)
#
# WHY A SEPARATE ENV:
#   vLLM 0.19.0 pulls in torch 2.10 and newer CUDA/triton libs that are
#   incompatible with the default MCP-Universe deps. Creating a dedicated
#   conda env avoids breaking the base installation.
#
# SETUP (one-time):
#   1. Create conda env:
#        conda create -n mcp-u-gemma4 python=3.12 -y
#
#   2. Install vLLM 0.19.0 (brings torch, triton, etc.):
#        conda activate mcp-u-gemma4
#        pip install vllm==0.19.0
#
#   3. Install transformers from source (Gemma4 model_type needs >=5.5):
#        pip install git+https://github.com/huggingface/transformers.git
#
#   4. Install MCP-Universe (skip version-pinned deps that conflict):
#        pip install -e ".[dev]" --no-deps
#        pip install mcp yfinance redis celery bcrypt pyseto kafka-python \
#            pika tenacity aiohttp beautifulsoup4 pytz notion-client \
#            sqlalchemy peewee mcp-server-calculator loguru playwright \
#            mistralai==1.6.0 google-genai xai-sdk openai-agents \
#            wikipedia-api claude-code-sdk blender-mcp
#
#   5. Download Gemma 4 model weights (requires HuggingFace license acceptance):
#        huggingface-cli download google/gemma-4-26B-A4B-it --local-dir ~/model_weights/gemma-4-26B-A4B-it
#        huggingface-cli download google/gemma-4-31B-it --local-dir ~/model_weights/gemma-4-31B-it
#
# USAGE:
#   source env_init_gemma4.sh
#
# RUNNING INFERENCE WITH GEMMA 4:
#   # Start vLLM server with tool calling support:
#   python -m vllm.entrypoints.openai.api_server \
#       --model ~/model_weights/gemma-4-26B-A4B-it \
#       --tensor-parallel-size 2 \
#       --dtype bfloat16 \
#       --trust-remote-code \
#       --enforce-eager \
#       --enable-auto-tool-choice \
#       --tool-call-parser gemma4
#
#   # Then use MCP-Universe agents with:
#   #   llm_type: openai
#   #   base_url: http://localhost:8000/v1
#   #   model_name: ~/model_weights/gemma-4-26B-A4B-it
# =============================================================================

# Conda Python environment
eval "$(conda shell.bash hook)" 2>/dev/null
conda activate mcp-u-gemma4

# Resolve project root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MCPUniverse_DIR="$SCRIPT_DIR"

# Conda env lib path (for libstdc++ / ICU compatibility)
CONDA_ENV_LIB="$(python -c 'import sys; print(sys.prefix)')/lib"
export LD_LIBRARY_PATH="${CONDA_ENV_LIB}:/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Strip Google Cloud SDK's bundled third-party libs from PYTHONPATH.
PYTHONPATH=$(echo "${PYTHONPATH:-}" | tr ':' '\n' | grep -v 'google-cloud-sdk' | paste -sd ':' -)
export CLOUDSDK_PYTHON_SITEPACKAGES=0

# Project root on PYTHONPATH
export PYTHONPATH="${MCPUniverse_DIR}${PYTHONPATH:+:$PYTHONPATH}"

# vLLM settings for Gemma4
export VLLM_USE_DEEP_GEMM=0
export TIKTOKEN_CACHE_DIR="/tmp/tiktoken-rs-cache"

# Load .env if present (API keys, etc.)
if [ -f "$MCPUniverse_DIR/.env" ]; then
    set -a
    source "$MCPUniverse_DIR/.env"
    set +a
fi

echo "MCP-Universe Gemma4 environment activated."
echo "  Python:  $(python --version 2>&1)"
echo "  vLLM:    $(python -c 'import vllm; print(vllm.__version__)' 2>&1)"
echo "  torch:   $(python -c 'import torch; print(torch.__version__)' 2>&1)"
