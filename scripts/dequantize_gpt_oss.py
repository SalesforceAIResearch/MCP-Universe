"""Dequantize a mxfp4-quantized GPT-OSS checkpoint to a plain bf16 HF checkpoint.

The original openai/gpt-oss-20b checkpoint is shipped with mxfp4-quantized MoE
weights. HF transformers dequantizes mxfp4 -> bf16 at load time. We save the
dequantized weights to a new path with `quantization_config` removed from the
config so vLLM also treats it as a non-quantized bf16 model. Both training
(FSDP) and inference (vLLM) then agree on the architecture, eliminating the
weight name/shape mismatch that breaks the runtime weight sync.
"""

import argparse
import json
import os
import shutil
import sys
import time

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="Source HF checkpoint dir (mxfp4)")
    parser.add_argument("--dst", required=True, help="Destination dir (bf16)")
    parser.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16"])
    args = parser.parse_args()

    if os.path.exists(args.dst) and os.listdir(args.dst):
        sys.exit(f"Destination {args.dst} already exists and is non-empty. Refusing to overwrite.")
    os.makedirs(args.dst, exist_ok=True)

    dtype = getattr(torch, args.dtype)
    print(f"[dequant] Loading {args.src} into {dtype} ...", flush=True)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        args.src,
        dtype=dtype,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    print(f"[dequant] Loaded in {time.time() - t0:.1f}s. Param count: {sum(p.numel() for p in model.parameters()) / 1e9:.2f}B", flush=True)

    # Strip quantization_config so vLLM treats this as a plain bf16 model.
    if hasattr(model.config, "quantization_config"):
        del model.config.quantization_config
        print("[dequant] Removed quantization_config from model.config", flush=True)

    print(f"[dequant] Saving to {args.dst} ...", flush=True)
    t0 = time.time()
    model.save_pretrained(args.dst, safe_serialization=True, max_shard_size="5GB")
    print(f"[dequant] save_pretrained done in {time.time() - t0:.1f}s", flush=True)

    # Save tokenizer alongside.
    tok = AutoTokenizer.from_pretrained(args.src, trust_remote_code=True)
    tok.save_pretrained(args.dst)
    print("[dequant] Tokenizer saved", flush=True)

    # Copy any chat template / generation config / extras the model_save didn't include.
    for fname in ("chat_template.jinja", "generation_config.json"):
        src_path = os.path.join(args.src, fname)
        dst_path = os.path.join(args.dst, fname)
        if os.path.exists(src_path) and not os.path.exists(dst_path):
            shutil.copy2(src_path, dst_path)
            print(f"[dequant] Copied {fname}", flush=True)

    # Sanity check the saved config.
    saved_cfg = AutoConfig.from_pretrained(args.dst, trust_remote_code=True)
    has_qc = hasattr(saved_cfg, "quantization_config") and saved_cfg.quantization_config is not None
    print(f"[dequant] Saved config has quantization_config? {has_qc}", flush=True)
    if has_qc:
        sys.exit("ERROR: saved config still has quantization_config; vLLM will still try mxfp4")

    # Print summary.
    total = 0
    for fname in os.listdir(args.dst):
        if fname.endswith(".safetensors"):
            total += os.path.getsize(os.path.join(args.dst, fname))
    print(f"[dequant] Done. Total .safetensors size: {total / 1024**3:.1f} GB at {args.dst}", flush=True)


if __name__ == "__main__":
    main()
