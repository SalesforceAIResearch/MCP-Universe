# Design Discussion: FSDP ↔ TP Weight Transfer Optimization

## Problem

In verl's hybrid mode, switching between FSDP (training) and DP+TP (inference) requires a full weight gather + broadcast. For a 31B model on 8 GPUs, this moves ~60GB of weights through the interconnect twice per training step — even though each GPU already holds a significant portion of the weights it needs.

## Proposed Optimization

Exploit overlap between FSDP shards and TP partitions so each GPU only transfers the weights it doesn't already have.

### Current flow (naive)
```
FSDP step done → all-gather full weights → broadcast to each vLLM replica → inference
inference done → discard vLLM weights → FSDP re-shards from scratch
```

### Optimized flow
```
FSDP step done → compute overlap map → each GPU keeps overlapping portion
                → targeted send/recv for missing slices only → inference
inference done → each GPU keeps what maps to its FSDP shard
               → gather only missing pieces from TP peers → resume FSDP
```

## Analysis

### Where overlap exists

GPU layout (8 GPUs, TP=2, 4 replicas):
```
Training (FSDP):     GPU 0,1,2,3,4,5,6,7  — all 8 share weight shards
Inference (vLLM):    Replica 0: GPU 0,1 (TP=2)
                     Replica 1: GPU 2,3 (TP=2)
                     Replica 2: GPU 4,5 (TP=2)
                     Replica 3: GPU 6,7 (TP=2)
```

For a parameter split by TP on dim=0 (e.g., `q_proj` split by attention heads):
- TP rank 0 of replica 0 (GPU 0) needs the first half of the parameter
- FSDP shard 0 (GPU 0) holds 1/8 of the parameter (contiguous byte range)
- **Overlap**: GPU 0's FSDP shard covers 1/8 of the param, but GPU 0's TP partition needs 1/2 → 25% of what's needed is already local

### Theoretical savings

With 4 replicas on 8 GPUs:
- Each TP rank needs 1/2 of every param (for TP=2)
- Each FSDP rank already holds 1/8 of every param
- Local overlap per GPU: 1/8 ÷ 1/2 = 25% already available
- **Transfer reduction: ~25% fewer bytes per GPU** (rough estimate, varies by parameter sharding)

For parameters that aren't TP-split (biases, norms), all replicas need the full tensor but each FSDP rank only has 1/8 — minimal savings there.

### Challenges

1. **FSDP1 flat-buffer sharding**: Parameters are concatenated into a flat buffer, then chunked by byte offset. Shard boundaries don't align with parameter boundaries, making overlap computation complex.

2. **FSDP2 per-parameter sharding**: Much more tractable — each parameter is independently sharded, so overlap can be computed per-parameter. The shard dimension (first axis chunk) may still differ from TP's split dimension (specific columns/rows).

3. **Format mismatch**: TP splits semantically (attention heads, MLP columns by weight matrix role), FSDP splits mechanically (byte ranges or axis-0 chunks). Converting requires a per-parameter reshape/gather/scatter plan.

4. **MoE expert parallelism**: Adds another sharding dimension. Expert weights may have EP placement that doesn't align with either FSDP or TP sharding.

5. **Implementation complexity**: Need a custom sync engine that understands both FSDP and TP sharding specs for every parameter in the model.

## Implementation Sketch

### Weight transfer plan (computed once at init)

```python
class WeightTransferPlan:
    """Pre-computed mapping between FSDP shards and TP partitions."""
    
    def __init__(self, model, fsdp_world_size, tp_world_size, num_replicas):
        self.param_plans = {}
        for name, param in model.named_parameters():
            tp_spec = get_tp_split_spec(name, model)  # which dim, which slice per rank
            fsdp_spec = get_fsdp_shard_spec(name, fsdp_world_size)  # byte range per rank
            
            self.param_plans[name] = ParamTransferPlan(
                tp_spec=tp_spec,
                fsdp_spec=fsdp_spec,
                overlap_map=compute_overlap(tp_spec, fsdp_spec),
            )
    
    def fsdp_to_tp(self, gpu_id, replica_id, tp_rank):
        """Return: {param_name: (local_slice, needed_from_peers)}"""
        ...
    
    def tp_to_fsdp(self, gpu_id):
        """Return: {param_name: (local_slice, needed_from_peers)}"""
        ...
```

### Sync engine

```python
class PartialSyncEngine:
    def update_weights(self, plan: WeightTransferPlan):
        for param_name, param_plan in plan.param_plans.items():
            # Keep local overlap (zero-copy)
            local_data = self.get_local_fsdp_shard(param_name)
            
            # Only transfer missing slices via NCCL point-to-point
            for src_gpu, byte_range in param_plan.needed_from_peers[self.gpu_id]:
                nccl_recv(src_gpu, byte_range)
            
            # Reassemble into TP partition layout
            self.set_tp_weight(param_name, reassembled_data)
```

## Prerequisites

- **FSDP2** strongly preferred over FSDP1 for per-parameter sharding
- **verl's checkpoint engine** needs a new backend (beyond `naive` and `mbridge`)
- **TP split specs** need to be extractable from the model architecture (vLLM already has this via `weight_loader` methods)

## Next Steps

1. Profile current `update_weights` to measure actual transfer time and bandwidth
2. Compute theoretical overlap percentages for Gemma4-31B and gpt-oss-20b
3. Prototype with FSDP2 + a single parameter to validate the approach
4. If promising, propose as verl RFC (relates to [#5790 Agent Abstractions RFC](https://github.com/verl-project/verl/issues/5790))
