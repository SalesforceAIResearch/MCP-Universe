"""
Provides a memory-based trace collector for storing and retrieving trace records.

This module contains the MemoryCollector class, which implements the BaseCollector
interface for in-memory storage of trace records.
"""
import threading
from typing import List
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer.types import TraceRecord


class MemoryCollector(BaseCollector):
    """
    A memory-based trace collector for storing and retrieving trace records.

    This collector stores trace records in memory using a thread-safe list. It provides
    methods for inserting new records and retrieving records by trace ID.

    Attributes:
        _records (List[TraceRecord]): A list to store trace records.
        _lock (threading.Lock): A lock for ensuring thread-safe operations.
    """

    def __init__(self):
        self._records: List[TraceRecord] = []
        self._lock = threading.Lock()

    def insert(self, record: TraceRecord):
        """
        Inserts a trace record into the collector.

        Args:
            record (TraceRecord): The trace record to be inserted.
        """
        with self._lock:
            self._records.append(record)

    def get(self, trace_id: str) -> List[TraceRecord]:
        """
        Retrieves trace records corresponding to the given trace ID.

        Args:
            trace_id (str): The trace ID to filter records by.

        Returns:
            List[TraceRecord]: A list of trace records matching the given trace ID.
        """
        with self._lock:
            return [record for record in self._records if record.trace_id == trace_id]
