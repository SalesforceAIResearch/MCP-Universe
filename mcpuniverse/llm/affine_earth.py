"""
Affine.Earth OpenAI-compatible client adapter for MCP-Universe.
"""
# pylint: disable=broad-exception-caught
import os
import logging
from dataclasses import dataclass
from typing import Dict, Union, Optional, Type, List
from openai import OpenAI
from pydantic_core import from_json
from dotenv import load_dotenv
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context
from .base import BaseLLM

load_dotenv()


@dataclass
class AffineEarthConfig(BaseConfig):
    """Configuration for Affine.Earth models over https://affine.earth/v1."""
    model_name: str = "affine-uum8d-s4"
    base_url: str = os.getenv("AFFINE_BASE_URL", "https://affine.earth/v1")
    api_key: str = os.getenv("AFFINE_API_KEY", "")
    max_completion_tokens: int = 2048
    seed: int = 0


class AffineEarthModel(BaseLLM):
    """Interacts with Affine.Earth OpenAI-compatible endpoints."""
    config_class = AffineEarthConfig
    alias = "affine_earth"
    env_vars = ["AFFINE_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = AffineEarthModel.config_class.load(config)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )
        req_kwargs = {
            "messages": messages,
            "model": self.config.model_name,
            "timeout": int(kwargs.pop("timeout", 30)),
            "seed": self.config.seed,
            **kwargs,
        }
        if response_format is not None:
            req_kwargs["response_format"] = {"type": "json_object"}
        chat = client.chat.completions.create(**req_kwargs)
        content = chat.choices[0].message.content
        if response_format is None:
            return content
        try:
            return response_format.model_validate(from_json(content))
        except Exception:
            self.logger.error("Failed to parse structured output:\n%s", str(content))
            return None

    def set_context(self, context: Context):
        super().set_context(context)
        self.config.api_key = context.env.get("AFFINE_API_KEY", self.config.api_key)
        self.config.base_url = context.env.get("AFFINE_BASE_URL", self.config.base_url)
