"""
Tracer module for agent output management.

This module provides a Tracer class for storing, managing, and retrieving agent outputs
in a structured manner. It supports hierarchical tracing and uses collectors for data storage.
"""
from __future__ import annotations

import time
import uuid
import threading
import datetime
from typing import Dict, List, Any
from mcpuniverse.common.misc import AutodocABCMeta
from mcpuniverse.tracer.types import TraceRecord, DataRecord
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer.collectors.memory import MemoryCollector


class Tracer(metaclass=AutodocABCMeta):
    """
    A tracer for storing and managing agent outputs in a hierarchical structure.

    This class provides methods for creating traces, adding data records, and retrieving
    trace information. It supports creating child tracers and uses collectors for data storage.
    """

    def __init__(self, collector: BaseCollector = None, trace_id: str = ""):
        """
        Initialize a new tracer.

        Args:
            collector: A collector implementing how to receive and process trace data.
                If not provided, a MemoryCollector is used by default.
            trace_id: A unique identifier for the trace. If not provided, a new UUID is generated.
        """
        self._lock: threading.Lock = threading.Lock()
        self._collector: BaseCollector = collector if collector else MemoryCollector()
        self._id: str = str(uuid.uuid4())
        self._trace_id: str = trace_id if trace_id else str(uuid.uuid4())
        self._parent_id: str = ""
        self._records: List[DataRecord] = []
        self._start_time: float = time.time()
        self._num_spans: int = 0
        self._index: int = 0

    def __enter__(self):
        with self._lock:
            self._start_time = time.time()
            self._records = []
            return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with self._lock:
            self._collector.insert(
                TraceRecord(
                    id=self._id,
                    trace_id=self._trace_id,
                    parent_id=self._parent_id,
                    records=self._records,
                    running_time=time.time() - self._start_time,
                    timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
                    span_index=self._index
                ))

    @property
    def id(self) -> str:
        """Getter for id"""
        return self._id

    @id.setter
    def id(self, value: str):
        self._id = value

    @property
    def trace_id(self) -> str:
        """Getter for trace_id"""
        return self._trace_id

    @trace_id.setter
    def trace_id(self, value: str):
        self._trace_id = value

    @property
    def parent_id(self) -> str:
        """Getter for parent_id"""
        return self._parent_id

    @parent_id.setter
    def parent_id(self, value: str):
        self._parent_id = value

    @property
    def index(self) -> int:
        """Getter for index"""
        return self._index

    @index.setter
    def index(self, value: int):
        self._index = value

    def sprout(self) -> Tracer:
        """
        Create a child tracer with a hierarchical relationship to the current tracer.

        The child tracer inherits the trace_id of the parent and sets its parent_id to the
        parent's id. This allows for creating a tree-like structure of related traces.

        Returns:
            Tracer: A new Tracer instance representing a child of the current tracer.
        """
        with self._lock:
            self._num_spans += 1
            tracer = Tracer(collector=self._collector, trace_id=self._trace_id)
            if self.parent_id == "":
                tracer.id = self.id
            tracer.parent_id = self.id
            tracer.index = self._num_spans
            return tracer

    def add(self, record: Dict[str, Any]):
        """
        Add a new data record to the tracer.

        This method wraps the provided record in a DataRecord object, automatically
        adding a timestamp, and appends it to the internal list of records.

        Args:
            record: A dictionary containing the data to be recorded.
        """
        with self._lock:
            self._records.append(
                DataRecord(
                    timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
                    data=record
                ))

    def get_trace(self) -> List[TraceRecord]:
        """
        Retrieve all trace records associated with this tracer's trace ID.

        This method uses the tracer's collector to fetch all TraceRecord objects
        that share the same trace_id as this tracer.

        Returns:
            List[TraceRecord]: A list of TraceRecord objects corresponding to the trace ID.
        """
        with self._lock:
            return self._collector.get(trace_id=self._trace_id)
