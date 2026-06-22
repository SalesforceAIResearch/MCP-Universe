"""LLM module containing various language model implementations."""

from .openai import OpenAIModel
from .mistral import MistralModel
from .claude import ClaudeModel
from .ollama import OllamaModel
from .deepseek import DeepSeekModel
from .claude_gateway import ClaudeGatewayModel
from .grok import GrokModel
from .openai_agent import OpenAIAgentModel
from .openrouter import OpenRouterModel
from .gemini import GeminiModel
from .local_llm import LocalLLMModel
# Backward compatibility alias
VLLMLocalModel = LocalLLMModel
from .claude_wr import ClaudeWRModel
from .sf_llm_express_gateway import SFLLMExpressGatewayModel
from .sf_research_gateway import SFResearchGatewayModel
# TITO (Token In Token Out) — direct inference engines, trajectory manager, agent wrapper
# Three backend options with identical async ``generate`` contract:
#   - AsyncVLLMEngine: wraps ``vllm.AsyncLLMEngine`` (in-process)
#   - AsyncSGLangEngine: wraps ``sglang.srt.entrypoints.engine.Engine`` (in-process)
#   - AsyncSGLangHTTPEngine: HTTP client to a SGLang server owned elsewhere (e.g. slime)
from .tito import (
    AsyncVLLMEngine, AsyncVLLMBackend, VLLMEngineConfig,
    AsyncSGLangEngine, SGLangEngineConfig,
    AsyncSGLangHTTPEngine,
    TokenTrajectoryManager, TokenTrajectory, TokenSegment,
    TITOLLMWrapper, TITOLLMConfig,
)

__all__ = [
    "OpenAIModel",
    "MistralModel",
    "ClaudeModel",
    "OllamaModel",
    "DeepSeekModel",
    "ClaudeGatewayModel",
    "ClaudeWRModel",
    "GrokModel",
    "OpenAIAgentModel",
    "OpenRouterModel",
    "GeminiModel",
    "LocalLLMModel",
    "VLLMLocalModel",  # backward compat alias
    "SFLLMExpressGatewayModel",
    "SFResearchGatewayModel",
    # Direct inference engines
    "AsyncVLLMEngine",
    "AsyncVLLMBackend",
    "VLLMEngineConfig",
    "AsyncSGLangEngine",
    "SGLangEngineConfig",
    "AsyncSGLangHTTPEngine",  # for HTTP-attached SGLang servers (e.g. slime)
    # TITO (Token In Token Out) for RL training
    "TokenTrajectoryManager",
    "TokenTrajectory",
    "TokenSegment",
    "TITOLLMWrapper",
    "TITOLLMConfig",
]
