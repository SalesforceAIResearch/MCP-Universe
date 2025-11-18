"""
Base login helper abstract class.

This module provides the abstract base class for login helpers
used across different MCP services.
"""
from abc import ABC, abstractmethod


class BaseLoginHelper(ABC):  # pylint: disable=too-few-public-methods
    """Abstract base class for login helpers."""

    def __init__(self):
        """Initialize the base login helper."""

    @abstractmethod
    def login(self, **kwargs):
        """
        Perform login operation.

        Args:
            **kwargs: Login parameters specific to the service
        """
