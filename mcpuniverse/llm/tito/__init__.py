"""
TITO (Token In Token Out) subpackage for RL training.

Components:
- AsyncVLLMEngine: Direct vLLM inference engine (token[] -> token[])
- AsyncSGLangEngine: Direct SGLang inference engine (same API as AsyncVLLMEngine)
- TokenTrajectoryManager: Maintains token sequence, builds loss mask
- TITOLLMWrapper: Agent-compatible wrapper combining engine + manager
"""

from .engine import (
    AsyncVLLMEngine,
    AsyncVLLMBackend,
    VLLMEngineConfig,
    create_ray_vllm_actor,
    AsyncSGLangEngine,
    SGLangEngineConfig,
    create_ray_sglang_actor,
    AsyncSGLangHTTPEngine,
)
from .manager import TokenTrajectoryManager, TokenTrajectory, TokenSegment
from .wrapper import TITOLLMWrapper, TITOLLMConfig

# Re-export for convenience; engine classes are always importable but
# raise ImportError at instantiation if vllm/sglang/ray are not installed.

__all__ = [
    # vLLM backend (in-process)
    "AsyncVLLMEngine",
    "AsyncVLLMBackend",
    "VLLMEngineConfig",
    "create_ray_vllm_actor",
    # SGLang backend, in-process (same async generate contract)
    "AsyncSGLangEngine",
    "SGLangEngineConfig",
    "create_ray_sglang_actor",
    # SGLang backend, HTTP client (for callers like slime that own SGLang
    # lifecycle elsewhere and only need a thin TITO-compatible client)
    "AsyncSGLangHTTPEngine",
    # Token trajectory + agent wrapper
    "TokenTrajectoryManager",
    "TokenTrajectory",
    "TokenSegment",
    "TITOLLMWrapper",
    "TITOLLMConfig",
]
