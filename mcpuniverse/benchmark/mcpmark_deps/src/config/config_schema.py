#!/usr/bin/env python3
"""
Centralized Configuration Schema for MCPMark
=============================================

This module provides a unified configuration system with validation,
type safety, and support for multiple configuration sources.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

from src.logger import get_logger

logger = get_logger(__name__)


# Lazy import to avoid circular dependencies
def get_service_definition(service_name: str) -> dict:
    from src.services import get_service_definition as _get_service_def

    return _get_service_def(service_name)


@dataclass
class ConfigValue:
    """Represents a configuration value with metadata."""

    key: str
    value: Any
    source: str  # 'env', 'file', 'default'
    required: bool = True
    description: str = ""
    validator: Optional[callable] = None

    def validate(self) -> bool:
        """Validate the configuration value."""
        if self.required and self.value is None:
            raise ValueError(f"Required configuration '{self.key}' is missing")

        if self.validator and self.value is not None:
            if not self.validator(self.value):
                raise ValueError(f"Invalid value for '{self.key}': {self.value}")

        return True


class ConfigSchema(ABC):
    """Abstract base class for service configuration schemas."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._values: Dict[str, ConfigValue] = {}
        self._load_dotenv()
        self._define_schema()
        self._load_values()
        self._validate()

    @abstractmethod
    def _define_schema(self) -> None:
        """Define the configuration schema for this service."""
        pass

    def _load_dotenv(self) -> None:
        """Load environment variables from .mcp_env file."""
        load_dotenv(dotenv_path=".mcp_env", override=False)

    def _add_config(
        self,
        key: str,
        env_var: Optional[str] = None,
        default: Any = None,
        required: bool = True,
        description: str = "",
        validator: Optional[callable] = None,
        transform: Optional[callable] = None,
    ) -> None:
        """Add a configuration value to the schema."""
        # Try to get value from environment first
        value = None
        source = "default"

        if env_var:
            env_value = os.getenv(env_var)
            if env_value is not None:
                value = transform(env_value) if transform else env_value
                source = "env"

        # Use default if no environment value
        if value is None and default is not None:
            value = default
            source = "default"

        self._values[key] = ConfigValue(
            key=key,
            value=value,
            source=source,
            required=required,
            description=description,
            validator=validator,
        )

    def _load_values(self) -> None:
        """Load configuration values from file if available."""
        config_file = Path(f"config/{self.service_name}.yaml")
        if config_file.exists():
            with open(config_file) as f:
                file_config = yaml.safe_load(f)

            for key, value in file_config.items():
                if key in self._values and self._values[key].value is None:
                    self._values[key].value = value
                    self._values[key].source = "file"

    def _validate(self) -> None:
        """Validate all configuration values."""
        for config_value in self._values.values():
            config_value.validate()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        if key in self._values:
            return self._values[key].value
        return default

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values as a dictionary."""
        return {k: v.value for k, v in self._values.items()}

    def get_debug_info(self) -> Dict[str, Dict[str, Any]]:
        """Get detailed configuration information for debugging."""
        return {
            k: {
                "value": v.value,
                "source": v.source,
                "required": v.required,
                "description": v.description,
            }
            for k, v in self._values.items()
        }


class GenericConfigSchema(ConfigSchema):
    """Generic configuration schema that reads from service definitions."""

    def __init__(self, service_name: str):
        # Get service definition before calling parent init
        self.service_definition = get_service_definition(service_name)
        super().__init__(service_name)

    def _define_schema(self) -> None:
        """Define schema from service definition."""
        config_schema = self.service_definition.get("config_schema", {})

        for key, config in config_schema.items():
            # Handle transform strings
            transform = None
            transform_str = config.get("transform")
            if transform_str == "bool":
                transform = lambda x: x.lower() in ["true", "1", "yes"]
            elif transform_str == "int":
                transform = int
            elif transform_str == "path":
                transform = lambda x: Path(x) if x else None
            elif transform_str == "list":
                transform = lambda x: [t.strip() for t in x.split(",")] if x else []

            # Handle validator strings
            validator = None
            validator_str = config.get("validator")
            if validator_str == "port":
                validator = lambda x: 1 <= x <= 65535
            elif validator_str and validator_str.startswith("in:"):
                valid_values = validator_str[3:].split(",")
                validator = lambda x, values=valid_values: x in values

            self._add_config(
                key=key,
                env_var=config.get("env_var"),
                default=config.get("default"),
                required=config.get("required", True),
                description=config.get("description", ""),
                validator=validator,
                transform=transform,
            )


# Configuration Registry


class ConfigRegistry:
    """Central registry for all service configurations."""

    _instances: Dict[str, ConfigSchema] = {}

    @classmethod
    def get_config(cls, service_name: str) -> ConfigSchema:
        """Get or create configuration for a service."""
        if service_name not in cls._instances:
            cls._instances[service_name] = GenericConfigSchema(service_name)
        return cls._instances[service_name]

    @classmethod
    def validate_all(cls) -> Dict[str, bool]:
        """Validate all registered configurations."""
        from src.services import get_supported_mcp_services

        results = {}
        for service_name in get_supported_mcp_services():
            try:
                cls.get_config(service_name)
                results[service_name] = True
            except Exception as e:
                logger.error(f"Configuration validation failed for {service_name}: {e}")
                results[service_name] = False
        return results

    @classmethod
    def export_template(cls, service_name: str, output_path: Path) -> None:
        """Export a configuration template for a service."""
        config = cls.get_config(service_name)

        template = {"service": service_name, "configuration": {}}

        for key, config_value in config._values.items():
            template["configuration"][key] = {
                "value": config_value.value
                if config_value.source == "default"
                else None,
                "description": config_value.description,
                "required": config_value.required,
                "env_var": f"${{{key.upper()}}}",
            }

        with open(output_path, "w") as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)


# Utility Functions


def get_service_config(service_name: str) -> Dict[str, Any]:
    """Get service configuration as a dictionary."""
    return ConfigRegistry.get_config(service_name).get_all()
