"""
Context information for user requests.
"""
import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class Context(BaseModel):
    """
    The class for user request context.
    The context will include environment variables, e.g., API keys for OpenAI or Anthropic,
    and some related metadata.
    """
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata")

    def get_env(self, var_name: str, default_value: str = "") -> str:
        """
        Return the value of an environment variable. If the context doesn't define this variable,
        it will try to get the value from `os.environ`.

        Args:
            var_name (str): A variable name.
            default_value (str): A default value

        Returns:
            str: The value of this variable.
        """
        return self.env.get(var_name, os.environ.get(var_name, default_value))
