"""
Base classes for trace collectors
"""
from abc import abstractmethod
from typing import List
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.tracer.types import TraceRecord


class BaseCollector(metaclass=AutodocABCMeta):
    """
    The base class for trace collectors
    """

    @abstractmethod
    def insert(self, record: TraceRecord):
        """
        Insert a trace record.
        """

    @abstractmethod
    def get(self, trace_id: str) -> List[TraceRecord]:
        """
        Return trace records corresponding to the trace ID.
        """
