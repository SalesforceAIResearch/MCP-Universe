"""
Provides a file-based trace collector for storing and retrieving trace records.
"""
import os
import json
import threading
from typing import List
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer.types import TraceRecord


class FileCollector(BaseCollector):
    """
    A file-based trace collector for storing and retrieving trace records.

    Attributes:
        _records (List[TraceRecord]): A list to store trace records.
        _lock (threading.Lock): A lock for ensuring thread-safe operations.
        _file_path (str): The log file path.
    """

    def __init__(self, log_file: str):
        self._records: List[TraceRecord] = []
        self._lock = threading.Lock()
        self._file_path = log_file
        folder = os.path.dirname(log_file)
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    @staticmethod
    def _format(record: TraceRecord):
        json_str = record.to_json()
        return json.dumps(json.loads(json_str), indent=2)

    def insert(self, record: TraceRecord):
        """
        Inserts a trace record into the collector.

        Args:
            record (TraceRecord): The trace record to be inserted.
        """
        with self._lock:
            self._records.append(record)
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write('-' * 66)
                f.write('\n')
                f.write(self._format(record))
                f.write('\n')

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
