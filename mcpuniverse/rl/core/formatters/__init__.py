"""
Model-specific formatters for trajectory prompt/response splitting.

Different models have different formats (Harmony, ChatML, etc.),
so we need model-specific parsers to correctly split prompt/response
and build loss masks.
"""

from .base import BaseFormatter, FormatterOutput
from .gemma4 import Gemma4Formatter
from .gpt_oss import GptOssFormatter
from .qwen3 import Qwen3Formatter

# Formatter registry
FORMATTERS = {
    "gpt_oss": GptOssFormatter,
    "gpt-oss": GptOssFormatter,
    "harmony": GptOssFormatter,  # Alias
    "qwen3": Qwen3Formatter,
    "qwen": Qwen3Formatter,  # Alias
    "chatml": Qwen3Formatter,  # Alias
    "react_train": Qwen3Formatter,  # Alias
    "gemma4": Gemma4Formatter,
    "gemma-4": Gemma4Formatter,
}


def get_formatter(model_type: str) -> BaseFormatter:
    """
    Get formatter for a model type.

    Args:
        model_type: Model type name (e.g., "gpt_oss", "llama", "qwen")

    Returns:
        Formatter instance
    """
    formatter_cls = FORMATTERS.get(model_type.lower())
    if formatter_cls is None:
        raise ValueError(f"Unknown model type: {model_type}. "
                        f"Available: {list(FORMATTERS.keys())}")
    return formatter_cls()


__all__ = [
    "BaseFormatter",
    "FormatterOutput",
    "Gemma4Formatter",
    "GptOssFormatter",
    "Qwen3Formatter",
    "get_formatter",
    "FORMATTERS",
]
