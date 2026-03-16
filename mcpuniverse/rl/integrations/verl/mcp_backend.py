"""
Data classes for MCP-VERL integration.
"""

from typing import Any, List, Dict
from dataclasses import dataclass, field


@dataclass
class MCPGeneratorInput:
    """Input batch for MCP agent rollout."""
    input_batch: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_data_proto(cls, data_proto: Any) -> "MCPGeneratorInput":
        """Create from VERL DataProto."""
        input_batch = []
        non_tensor_batch = data_proto.non_tensor_batch

        # Handle empty batch
        if not non_tensor_batch:
            return cls(input_batch=input_batch)

        # Get number of entries from first key
        # All keys should have the same length (batch consistency)
        first_key = next(iter(non_tensor_batch.keys()))
        num_entries = len(non_tensor_batch[first_key])

        # Validate that all keys have the same length
        for key in non_tensor_batch.keys():
            if len(non_tensor_batch[key]) != num_entries:
                raise ValueError(
                    f"Inconsistent batch sizes: key '{first_key}' has {num_entries} entries, "
                    f"but key '{key}' has {len(non_tensor_batch[key])} entries"
                )

        # Build batch items
        for i in range(num_entries):
            item = {key: non_tensor_batch[key][i] for key in non_tensor_batch.keys()}
            input_batch.append(item)

        return cls(input_batch=input_batch)


@dataclass
class MCPGeneratorOutput:
    """Output from MCP agent rollout."""
    prompt_token_ids: List[List[int]] = field(default_factory=list)
    response_ids: List[List[int]] = field(default_factory=list)
    loss_masks: List[List[int]] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    rollout_metrics: Dict[str, Any] = field(default_factory=dict)
    trajectories: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        """Validate that all fields have consistent lengths.

        Raises:
            ValueError: If any field lengths are inconsistent.
        """
        num_sequences = len(self.prompt_token_ids)

        for field_name, field_val in [
            ("response_ids", self.response_ids),
            ("loss_masks", self.loss_masks),
            ("rewards", self.rewards),
        ]:
            if len(field_val) != num_sequences:
                raise ValueError(
                    f"Inconsistent lengths: prompt_token_ids has {num_sequences} entries, "
                    f"but {field_name} has {len(field_val)} entries"
                )

        for i, (response_ids_item, loss_mask) in enumerate(zip(self.response_ids, self.loss_masks)):
            if len(loss_mask) != len(response_ids_item):
                raise ValueError(
                    f"Inconsistent mask length at index {i}: response_ids has {len(response_ids_item)} tokens, "
                    f"but loss_mask has {len(loss_mask)} elements"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Convert output to a dictionary."""
        return {
            "prompt_token_ids": self.prompt_token_ids,
            "response_ids": self.response_ids,
            "loss_masks": self.loss_masks,
            "rewards": self.rewards,
            "rollout_metrics": self.rollout_metrics,
            "trajectories": self.trajectories,
        }
