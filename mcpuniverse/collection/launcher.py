"""Agent collection configuration and loading utilities.

This module provides classes for defining and loading agent collection
configurations, supporting both YAML file and programmatic configuration.
"""
from __future__ import annotations
from typing import List, Dict, Literal

import yaml
from pydantic import BaseModel, Field


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
