"""Agent collection configuration and loading utilities.

This module provides classes for defining and loading agent collection
configurations, supporting both YAML file and programmatic configuration.
"""
# pylint: disable=too-few-public-methods
from __future__ import annotations
import os
from typing import List, Dict, Literal

import yaml
from pydantic import BaseModel, Field
from mcpuniverse.common.misc import AutodocABCMeta


class AgentCollectionSpec(BaseModel):
    """
    The specification for an agent collection.
    
    Defines the structure for configuring a collection of agents with
    shared settings and contexts.
    """

    # Agent collection name
    name: str
    # Agent config file path
    config: str
    # Agent contexts defining environment variables and settings
    context: List[Dict[str, str]] = Field(default_factory=list)
    # Number of agents to create for each context
    number: int = 1


class AgentCollectionConfig(BaseModel):
    """Configuration for an agent collection.
    
    Contains the collection specification and metadata.
    """
    # Configuration type identifier
    kind: Literal["collection"]
    # Agent collection specification
    spec: AgentCollectionSpec

    @staticmethod
    def load(config: str | dict | List[dict]) -> List[AgentCollectionConfig]:
        """
        Load agent collection configurations from various sources.
        
        Args:
            config: Configuration source - YAML file path, dict, or list of dicts.
            
        Returns:
            List of AgentCollectionConfig instances.
            
        Raises:
            AssertionError: If config file doesn't have .yml or .yaml extension.
        """
        if not config:
            return []
        if isinstance(config, str):
            assert config.endswith(".yml") or config.endswith(".yaml"), \
                "Config should be a YAML file"
            with open(config, "r", encoding="utf-8") as f:
                objects = yaml.safe_load_all(f)
                if isinstance(objects, dict):
                    objects = [objects]
                return [AgentCollectionConfig.model_validate(o) for o in objects]
        if isinstance(config, dict):
            config = [config]
        return [AgentCollectionConfig.model_validate(o) for o in config]


class Launcher(metaclass=AutodocABCMeta):
    """
    Launcher for managing agent collections.
    
    Loads and validates agent collection configurations, ensuring all
    required files exist and collection names are unique.
    """

    def __init__(self, config_path: str):
        """
        Initialize the launcher with configuration.
        
        Args:
            config_path: Path to the YAML configuration file.
            
        Raises:
            ValueError: If invalid kind, missing config files, or duplicate names.
        """
        self._collection_configs = AgentCollectionConfig.load(config_path)

        # Check if all the configs are "collection"
        for config in self._collection_configs:
            if config.kind != "collection":
                raise ValueError(f"Agent collection configs have invalid kind `{config.kind}`")

        # Check if agent config file exists
        folder = os.path.dirname(config_path)
        for config in self._collection_configs:
            path = config.spec.config
            if not os.path.exists(path):
                path = os.path.join(folder, path)
                if not os.path.exists(path):
                    raise ValueError(f"Missing agent config file `{config.spec.config}`")

        self._name_to_configs = {}
        for config in self._collection_configs:
            if config.spec.name in self._name_to_configs:
                raise ValueError(f"Found duplicated collection name `{config.spec.name}`")
            self._name_to_configs[config.spec.name] = config
