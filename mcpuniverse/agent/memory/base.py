"""
Provides the base class for agent short-term and long-term memories.
"""
from abc import abstractmethod
from typing import List
from pydantic import BaseModel
from mcpuniverse.common.misc import ComponentABCMeta, ExportConfigMixin


class MemoryRecord(BaseModel):
    """
    The data object for a memory record.
    """
    agent_id: str
    tag: str
    content: str


class BaseMemory(ExportConfigMixin, metaclass=ComponentABCMeta):
    """
    Base class for short-term and long-term memories.

    This abstract base class defines the interface and common functionality
    for agent memory implementations.
    """

    @abstractmethod
    def add(self, record: MemoryRecord):
        """Add a memory record."""

    @abstractmethod
    def retrieve(self, agent_id: str, **kwargs):
        """Retrieve stored memory."""

    @abstractmethod
    def remove_all(self, agent_id: str):
        """Remove all the memory records."""

    @staticmethod
    def memory_to_str(records: List[MemoryRecord]):
        """Convert a list of memory records into string."""
        strs = [f"{r.tag}: {r.content}" for r in records]
        return "\n".join(strs)
