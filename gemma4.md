# Plan: Replace gpt-oss with Gemma 4 for RL Training

## Context

Current RL training uses gpt-oss-20b (dequantized bf16) with Harmony protocol for tool calling. We want to evaluate Gemma 4 models (both dense 31B and MoE 26B-A4B) as alternatives. This requires upgrading the inference stack and adapting the agent/formatter pipeline.

## Model Comparison

| | gpt-oss-20b | Gemma4-31B (dense) | Gemma4-26B-A4B (MoE) |
|---|---|---|---|
| **Params** | 20B MoE (32 experts) | 31B dense | 26B MoE (128 experts, 8 active) |
| **Architecture** | GptOssForCausalLM | Gemma4ForConditionalGeneration | Gemma4ForConditionalGeneration |
| **model_type** | gpt_oss | gemma4 | gemma4 |
| **Multimodal** | No | Yes (vision+audio) | Yes (vision+audio) |
| **Vocab size** | 201,088 | 262,144 | 262,144 |
| **Tool calling** | Harmony protocol (`<\|start\|>`, `<\|call\|>`) | Gemma4 format (`<\|tool_call>`, `<\|tool_response>`) | Same |
| **Size on disk** | 42GB (bf16) | 59GB | 49GB |
| **vLLM support** | 0.11.0+ | **0.19.0+ only** | **0.19.0+ only** |
| **Transformers** | 4.57.1 | **≥5.5.0 required** | **≥5.5.0 required** |

## Risk Assessment

### HIGH RISK: vLLM + transformers upgrade (Effort: 2-3 days)

**Problem**: Gemma4 requires vLLM ≥0.19.0 and transformers ≥5.5.0. We're on vLLM 0.11.0 and transformers 4.57.1 — a major version jump (8 releases).

**Impact**:
- verl (our RL framework) is pinned to a specific git commit that was validated against vllm 0.11.0
- verl's `vllm_async_server.py`, `vllm_rollout.py`, checkpoint engine, and weight sync all have vLLM-version-specific code
- The mxfp4 `load_weights` bug we hit was already a vLLM 0.11.0 compatibility issue — upgrading to 0.19.0 could introduce new ones
- torch, flash-attn, triton, xformers may all need version bumps
- The `deep_gemm` ABI issue may resurface with new torch versions

**Mitigation**: Use vLLM's recommended Docker image `vllm/vllm-openai:gemma4` for inference, or create a separate conda env for Gemma4.

### MEDIUM RISK: Tool calling format change (Effort: 1 day)

**Problem**: Gemma4 uses its own tool format (`<|tool_call>call:func_name{...}<tool_call|>`, `<|tool_response>response:func_name{...}<tool_response|>`), not Harmony.

**Impact**:
- `agent_mode: harmony` and `formatter_type: gpt_oss` won't work
- Need a new `AgentMode.GEMMA4` or use `react_train` with Gemma4's native format
- verl's `ToolAgentLoop` already has active Gemma4 tool parser work (PRs #39070, #39484, #39311 — all fixing Gemma4 parsing bugs in vLLM 0.19.0)
- MCPLoopManager's `GptOssFormatter` needs a Gemma4 equivalent for TITO tokenization

**Mitigation**: vLLM 0.19.0 already includes a Gemma4 tool parser. verl's `ToolAgentLoop` with `format: gemma4` should work once vLLM is upgraded.

### LOW RISK: Multimodal architecture (Effort: minimal)

**Problem**: Gemma4 is `ForConditionalGeneration` (multimodal) not `ForCausalLM` (text-only).

**Impact**: vLLM handles this transparently — text-only requests work fine with multimodal models. FSDP loading may need `trust_remote_code: true`. No code changes needed.

### LOW RISK: Memory/GPU fit (Effort: config tuning)

- Gemma4-31B dense (59GB bf16) on 8x H200: ~7.4GB per GPU with TP=8, plenty of room
- Gemma4-26B-A4B MoE (49GB bf16) on 8x H200: similar, plus expert parallelism available
- Both fit comfortably with `gpu_memory_utilization: 0.4`

## Recommended Approach

### Option A: Upgrade vLLM stack (recommended for production)

1. **Create new conda env** `mcp312-gemma4` with vLLM 0.19.0, transformers ≥5.5.0
2. **Update verl** to latest commit that supports vLLM 0.19.0 (check verl releases)
3. **Add Gemma4 formatter** to `mcpuniverse/rl/formatters/` (similar to Qwen3Formatter but for Gemma4 token format)
4. **Add `AgentMode.GEMMA4`** or reuse `REACT_TRAIN` with Gemma4 chat template
5. **Create new YAML config** `mcp_gemma4_31b_financial.yaml`
6. **Test with verl native ToolAgentLoop** (which already works) using `format: gemma4` tool parser

### Option B: Use react_train mode with current stack (quick experiment)

Gemma4 models can't load in vLLM 0.11.0 at all — `Gemma4ForConditionalGeneration` is not in the model registry. This option is **not viable** without a vLLM upgrade.

## Implementation Steps (Option A)

### Step 1: Create new environment
```bash
conda create -n mcp-gemma4 python=3.12
pip install vllm==0.19.0  # pulls transformers>=5.5.0
pip install -e "path/to/verl"  # need compatible verl version
pip install -e ".[rl]"
```

### Step 2: Verify verl compatibility with vLLM 0.19.0
- Check verl's latest main branch for vLLM 0.19.0 support
- Key files: `verl/workers/rollout/vllm_rollout/vllm_async_server.py`, `utils.py`

### Step 3: Add Gemma4 formatter
- File: `mcpuniverse/rl/formatters/gemma4.py`
- Pattern: follow `Qwen3Formatter` structure
- Token format: `<|tool_call>call:name{args}<tool_call|>` / `<|tool_response>response:name{result}<tool_response|>`

### Step 4: Create training config
- File: `mcpuniverse/rl/integrations/verl/config/mcp_gemma4_31b_financial.yaml`
- Key changes: model path, formatter_type, agent_mode, remove Harmony-specific settings

### Step 5: Test and validate
```bash
source env_init_gemma4.sh
python -m mcpuniverse.rl.integrations.verl.hybrid.mcp_main_ppo --config-name=mcp_gemma4_31b_financial
```

## Effort Estimate

| Task | Effort | Risk |
|------|--------|------|
| New conda env + vLLM 0.19.0 | 1 day | High (dependency conflicts) |
| verl compatibility with vLLM 0.19.0 | 1-2 days | High (may need verl patches) |
| Gemma4 formatter + agent mode | 0.5 day | Medium |
| Training config + testing | 0.5 day | Low |
| **Total** | **3-4 days** | |

## Critical Files

- `mcpuniverse/rl/formatters/gemma4.py` (new)
- `mcpuniverse/rl/formatters/__init__.py` (add gemma4 entry)
- `mcpuniverse/rl/config.py` (add GEMMA4 agent mode if needed)
- `mcpuniverse/rl/integrations/verl/config/mcp_gemma4_31b_financial.yaml` (new)
- `env_init_gemma4.sh` (new)
- `pyproject.toml` (optional: add gemma4 extras)

## Key Blocker

**vLLM 0.11.0 → 0.19.0 is a breaking upgrade**. This is the single biggest risk. The verl integration was painstakingly debugged for vLLM 0.11.0 over this session. Upgrading vLLM may break:
- `update_weights` / weight sync path
- `vLLMHttpServer` Ray actor interface
- Sleep/wake mode behavior
- Checkpoint engine compatibility

Recommend: test vLLM 0.19.0 in a **separate env** without touching the working gpt-oss setup.

## Progress Log

### 2026-04-15: Environment setup + model verification

**Conda env `mcp-u-gemma4` created with:**
- Python 3.12, vLLM 0.19.0, torch 2.10.0+cu128, transformers 5.6.0.dev0 (from source)
- verl 0.8.0.dev0 installed with `--no-deps` (bypasses vllm<=0.12.0 pin)
- mcpuniverse installed editable with RL extras
- `LD_LIBRARY_PATH="/opt/conda/envs/mcp-u-gemma4/lib:/usr/lib/x86_64-linux-gnu"` needed for libstdc++ compat

**Gemma4-26B-A4B-it verified:**
- Loads in vLLM 0.19.0 with TP=2, 25GB per GPU, 8s load time
- Chat generation works: "2+2=4" ✅
- Tool calling works: `get_stock_info({"ticker": "AAPL"})` parsed correctly ✅
- Requires `--enable-auto-tool-choice --tool-call-parser gemma4`

**Key findings:**
- transformers 4.57.x does NOT support gemma4 — need >=5.5.0 (installed from source)
- vLLM 0.19.0 pins transformers<5 but works with 5.6.0.dev0
- verl pins vllm<=0.12.0 — installed with --no-deps, verl compat with vLLM 0.19.0 untested
- openai-harmony upgraded to 0.0.8 (from 0.0.4)
- Gemma4 uses its own tool format, not Harmony — `<|tool_call>call:name{args}<tool_call|>`

**Remaining:**
- [x] Add Gemma4 formatter for TITO tokenization → used `react_train` / `chatml` (Qwen3Formatter), works for Gemma4
- [x] Create training YAML config → `mcp_gemma4_26b_financial.yaml`
- [x] Test verl hybrid mode training (FSDP + vLLM weight sync) → WORKING
- [x] Run 4-step test training on yfinance tasks → IN PROGRESS

### 2026-04-15: Training integration (continued)

**Additional verl patches needed:**
- `verl/utils/fsdp_utils.py`: Added fallback for `get_module_class_from_name` — Gemma4's multimodal arch nests decoder layers deeper than verl's search traverses
- `verl/utils/model.py`, `verl/workers/fsdp_workers.py`, `verl/utils/checkpoint/fsdp_checkpoint_manager.py`, `verl/model_merger/base_model_merger.py`: `AutoModelForVision2Seq` → `AutoModelForImageTextToText` compat shim
- `mcpuniverse/rl/integrations/verl/utils.py`: Added conda env bin to PATH in Ray runtime env (subprocess `python3` was resolving to base env)

**Attention backend:**
- `flash_attention_2` (flash-attn 2.8.3) **FAILS** — Gemma4 has `global_head_dim=512`, FA2 max is 256
- `sdpa` (torch SDPA) **WORKS** — set via `model.override_config.attn_implementation: sdpa`
- vLLM 0.19.0 uses FlashInfer (flashinfer-python 0.6.6) + Triton attention for inference — unaffected

**First rollout result:**
- Gemma4-26B-A4B: 12.5% success rate (2/16 trajectories correct) on step 1
- Same baseline as gpt-oss-20b on yfinance tasks

**LD_LIBRARY_PATH for mcp-u-gemma4:**
```
/opt/conda/envs/mcp-u-gemma4/lib:/usr/local/nvidia/lib64
```
(conda libs for ICU/libstdc++, nvidia libs for libcuda)
