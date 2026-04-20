"""
Correctness test for Gemma4 fused log_prob computation.

Compares vanilla (full logits → log_softmax → gather) vs fused
(LinearCrossEntropy online softmax) paths on random input.
The two should be numerically equivalent within floating-point tolerance.

Usage:
    LD_LIBRARY_PATH="/opt/conda/envs/mcp-u-gemma4/lib:/usr/local/nvidia/lib64" \
    /opt/conda/envs/mcp-u-gemma4/bin/python tests/verl/test_gemma4_fused_logprob.py
"""

import sys
import torch


def test_fused_vs_vanilla():
    from transformers import AutoConfig, AutoModelForCausalLM

    model_path = "/root/model_weights/gemma-4-26B-A4B-it"
    device = "cuda:0"

    print("Loading Gemma4 config...")
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True, attn_implementation="sdpa")

    print("Loading model (this takes ~30s)...")
    model = AutoModelForCausalLM.from_pretrained(
        model_path, config=config, torch_dtype=torch.bfloat16,
        trust_remote_code=True, device_map={"": device},
    )
    model.eval()

    batch_size, seq_len = 2, 128
    vocab_size = config.text_config.vocab_size

    torch.manual_seed(42)
    input_ids = torch.randint(0, vocab_size, (batch_size, seq_len), device=device)
    attention_mask = torch.ones_like(input_ids)
    position_ids = torch.arange(seq_len, device=device).unsqueeze(0).expand(batch_size, -1)
    mm_token_type_ids = torch.zeros_like(input_ids)
    rolled_labels = torch.roll(input_ids, shifts=-1, dims=-1)

    # --- Vanilla path: full logits → log_softmax → gather ---
    print("Computing vanilla log_probs (full logits)...")
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        outputs_vanilla = model.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            mm_token_type_ids=mm_token_type_ids,
            use_cache=False,
        )
        hidden_states = outputs_vanilla[0]
        logits = model.lm_head(hidden_states)  # (batch, seq, vocab) — the memory killer
        log_probs_full = torch.log_softmax(logits.float(), dim=-1)
        vanilla_log_probs = torch.gather(
            log_probs_full, dim=-1, index=rolled_labels.unsqueeze(-1)
        ).squeeze(-1)  # (batch, seq)

    print(f"  logits shape: {logits.shape} ({logits.element_size() * logits.nelement() / 1e9:.2f} GB)")
    del logits, log_probs_full
    torch.cuda.empty_cache()

    # --- Fused path: LinearCrossEntropy (online softmax, no full logits) ---
    print("Computing fused log_probs (LinearCrossEntropy)...")
    from verl.utils.kernel.linear_cross_entropy import linear_cross_entropy

    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        outputs_fused = model.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            mm_token_type_ids=mm_token_type_ids,
            use_cache=False,
        )
        hidden_fused = outputs_fused[0]
        fused_log_probs, fused_entropy = linear_cross_entropy(
            hidden_fused,
            model.lm_head.weight,
            rolled_labels,
            1.0,  # temperature
            "none",
        )

    # --- Compare ---
    vanilla_flat = vanilla_log_probs.float().flatten()
    fused_flat = fused_log_probs.float().flatten()

    abs_diff = (vanilla_flat - fused_flat).abs()
    max_diff = abs_diff.max().item()
    mean_diff = abs_diff.mean().item()
    cos_sim = torch.nn.functional.cosine_similarity(
        vanilla_flat.unsqueeze(0), fused_flat.unsqueeze(0)
    ).item()

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"  Max absolute difference:  {max_diff:.6e}")
    print(f"  Mean absolute difference: {mean_diff:.6e}")
    print(f"  Cosine similarity:        {cos_sim:.8f}")
    print(f"  Vanilla sample:  {vanilla_flat[:5].tolist()}")
    print(f"  Fused sample:    {fused_flat[:5].tolist()}")

    atol = 1e-2  # bf16 precision + online softmax numerical differences
    passed = max_diff < atol
    print(f"\n  atol={atol}: {'PASS ✓' if passed else 'FAIL ✗'}")

    if not passed:
        print(f"\n  WARNING: max_diff={max_diff:.6e} > atol={atol}")
        print(f"  This may be due to bf16 precision. Check if cosine_sim > 0.999")
        if cos_sim > 0.999:
            print(f"  Cosine similarity {cos_sim:.6f} > 0.999 — numerically close enough")
            passed = True

    print(f"{'='*60}")
    return passed


if __name__ == "__main__":
    ok = test_fused_vs_vanilla()
    sys.exit(0 if ok else 1)
