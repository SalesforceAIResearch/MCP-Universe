"""
Provides the base class for configuration objects.

This module defines the BaseConfig class, which serves as a foundation for
creating and managing configuration objects with JSON serialization and
deserialization capabilities.
"""
from __future__ import annotations

import json
import dataclasses
from typing import Dict
from dataclasses import dataclass


@dataclass
class BaseConfig:
    """
    Base class for configuration objects.

    This class provides methods for loading, converting, and serializing
    configuration data. It supports creation from dictionaries and JSON strings,
    as well as conversion to these formats.

    Attributes are defined by subclasses using dataclass fields.
    """

    @classmethod
    def load(cls, data: Dict | str):
        """
        Builds a config object from a dict or a JSON string.

        Args:
            data: Configuration data as a dict or a JSON string.

        Returns:
            An instance of the configuration class.

        Raises:
            json.JSONDecodeError: If the input is a string and not valid JSON.
        """
        if data is None:
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls.from_json(data)

    @classmethod
    def from_dict(cls, data: Dict):
        """
        Builds a config object from a dict.

        Args:
            data: Configuration data as a dict.

        Returns:
            An instance of the configuration class.
        """
        config = cls(**data)
        subclasses = [f"{c.__module__}.{c.__name__}" for c in BaseConfig.__subclasses__()]
        for field_name, field_type in cls.__annotations__.items():
            if f"{field_type.__module__}.{field_type.__name__}" in subclasses:
                v = getattr(config, field_name)
                if isinstance(v, dict):
                    setattr(config, field_name, field_type.from_dict(v))
        return config

    @classmethod
    def from_json(cls, data: str):
        """
        Builds a config object from a JSON string.

        Args:
            data: Configuration data as a JSON string.

        Returns:
            An instance of the configuration class.

        Raises:
            json.JSONDecodeError: If the input is not valid JSON.
        """
        return cls.from_dict(json.loads(data))

    def to_dict(self) -> Dict:
        """
        Converts the config object to a dict.

        This method excludes any fields with names that contain 'api_key'
        (case-insensitive) for security reasons.

        Returns:
            A dictionary representation of the configuration object.
        """
        data = dataclasses.asdict(self)
        return {key: val for key, val in data.items() if key.lower() not in ["api_key"]}

    def to_json(self) -> str:
        """
        Converts the config object to a JSON string.

        This method uses the to_dict method, so it also excludes API key fields.

        Returns:
            A JSON string representation of the configuration object.
        """
        return json.dumps(self.to_dict())
