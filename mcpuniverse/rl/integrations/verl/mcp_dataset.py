"""
MCP Dataset for VERL integration.

Loads MCP training data with evaluators and MCP server configs.
"""
# pylint: disable=fixme

import json
from typing import Any, Dict, List

from torch.utils.data import Dataset
from loguru import logger


class MCPDataset(Dataset):
    """
    Dataset for MCP agent training.

    Loads JSON data with:
    - instance_id: Unique identifier
    - instruction: Task instruction (question)
    - output_format: Expected output format
    - mcp_servers: List of MCP server configs
    - evaluators: List of evaluator configs
    """

    def __init__(
        self,
        data_path: str,
        tokenizer: Any = None,
        max_length: int = 4096,
        is_train: bool = True,
    ):
        """
        Initialize MCP dataset.

        Args:
            data_path: Path to JSON data file
            tokenizer: Tokenizer (reserved for future tokenization support)
            max_length: Max sequence length (reserved for future use)
            is_train: Whether this is training data
        """
        self.data_path = data_path
        self.tokenizer = tokenizer  # TODO: add optional pre-tokenization support
        self.max_length = max_length  # TODO: add optional length filtering
        self.is_train = is_train

        with open(data_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        logger.info(f"Loaded {len(self.data)} samples from {data_path}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        """
        Get a single sample.

        Passes through all fields from the JSON data so that downstream
        consumers (e.g. MCPLoopManager) can access task-specific keys
        like ``dockerfile_path`` without needing changes here.
        """
        item = self.data[idx]

        instruction = item.get("instruction", "")
        output_format = item.get("output_format")

        if output_format:
            instruction = f"{instruction}\n\nOutput format:\n{json.dumps(output_format, indent=2)}"

        # Start with all original fields so new keys (e.g. dockerfile_path)
        # are automatically passed through to downstream consumers.
        result = dict(item)
        # Override/ensure defaults for core fields
        result.update({
            "instance_id": item.get("instance_id", f"sample_{idx}"),
            "instruction": instruction,
            "question": item.get("instruction", ""),
            "output_format": output_format,
            "dockerfile_path": item.get("dockerfile_path", ""),
            "mcp_servers": item.get("mcp_servers", []),
            "evaluators": item.get("evaluators", []),
            "category": item.get("category", "unknown"),
        })
        return result


def create_mcp_dataset(
    data_path: str,
    config: Any,
    tokenizer: Any = None,
    processor: Any = None,  # pylint: disable=unused-argument
    is_train: bool = True,
) -> MCPDataset:
    """
    Create MCP dataset.

    Args:
        data_path: Path to JSON data file
        config: Data configuration
        tokenizer: Tokenizer
        processor: Processor (optional, unused)
        is_train: Whether training data

    Returns:
        MCPDataset instance
    """
    max_length = config.get("max_length", 4096) if hasattr(config, "get") else 4096

    return MCPDataset(
        data_path=data_path,
        tokenizer=tokenizer,
        max_length=max_length,
        is_train=is_train,
    )


def mcp_collate_fn(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Collate function for MCP dataset.

    Returns the batch as non_tensor_batch for MCPLoopManager.
    """
    all_keys = set()
    for item in batch:
        all_keys.update(item.keys())

    non_tensor_batch = {}
    for key in all_keys:
        non_tensor_batch[key] = [item.get(key) for item in batch]

    return {"non_tensor_batch": non_tensor_batch}
