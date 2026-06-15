"""
Shared LLM-as-judge helper for evaluators.

Evaluators historically called OpenAI() directly, bypassing ModelManager.
This module routes judge calls through the same provider stack as agents
(openai, azure, etc.) using environment configuration.
"""
# pylint: disable=broad-exception-caught
from dataclasses import dataclass
from typing import Optional, Type

from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.context import Context
from mcpuniverse.llm.manager import ModelManager

DEFAULT_OPENAI_JUDGE_MODEL = "gpt-4.1"
DEFAULT_OPENAI_HLE_JUDGE_MODEL = "o3-mini-2025-01-31"

_JUDGE_SYSTEM_PROMPT = "You are a helpful assistant."


@dataclass
class JudgeConfig:
    """Resolved provider and model/deployment for evaluator judges."""

    provider: str
    model_name: str


def _has_azure_credentials(context: Context) -> bool:
    return bool(context.get_env("AZURE_API_KEY") and context.get_env("AZURE_API_BASE"))


def resolve_judge_config(
        context: Context,
        default_model_name: str = DEFAULT_OPENAI_JUDGE_MODEL,
) -> JudgeConfig:
    """
    Resolve evaluator judge provider and model from environment.

    When EVAL_LLM_PROVIDER is unset, defaults to azure if Azure credentials
    are present, otherwise openai.
    """
    explicit_provider = context.get_env("EVAL_LLM_PROVIDER").strip().lower()
    if explicit_provider:
        provider = explicit_provider
    elif _has_azure_credentials(context):
        provider = "azure"
    else:
        provider = "openai"

    model_name = context.get_env("EVAL_LLM_MODEL_NAME")
    if not model_name and provider == "azure":
        model_name = context.get_env("AZURE_JUDGE_DEPLOYMENT")
    if not model_name:
        model_name = default_model_name

    return JudgeConfig(provider=provider, model_name=model_name)


def build_judge_model(
        context: Context,
        default_model_name: str = DEFAULT_OPENAI_JUDGE_MODEL,
):
    """Build an LLM client for evaluator judging via ModelManager."""
    config = resolve_judge_config(context, default_model_name)
    model_config = {"model_name": config.model_name}
    if config.provider == "openai":
        api_key = context.get_env("OPENAI_API_KEY")
        if api_key:
            model_config["api_key"] = api_key
    model = ModelManager().build_model(config.provider, model_config)
    model.set_context(context)
    return model


def call_judge_text(
        prompt: str,
        context: Optional[Context] = None,
        temperature: float = 0.0,
        default_model_name: str = DEFAULT_OPENAI_JUDGE_MODEL,
) -> Optional[str]:
    """Call the configured judge model and return plain text."""
    context = context or Context()
    model = build_judge_model(context, default_model_name)
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    attempt = 5
    while attempt > 0:
        try:
            return model.generate(messages, temperature=temperature)
        except Exception as e:
            attempt -= 1
            print(f"Error: {e}")
    return None


def call_judge_structured(
        prompt: str,
        response_format: Type[PydanticBaseModel],
        context: Optional[Context] = None,
        max_completion_tokens: int = 4096,
        default_model_name: str = DEFAULT_OPENAI_HLE_JUDGE_MODEL,
) -> Optional[PydanticBaseModel]:
    """Call the configured judge model and return a parsed Pydantic object."""
    context = context or Context()
    model = build_judge_model(context, default_model_name)
    messages = [{"role": "user", "content": prompt}]
    attempt = 5
    while attempt > 0:
        try:
            return model.generate(
                messages,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
            )
        except Exception as e:
            attempt -= 1
            print(f"Error: {e}")
    return None
