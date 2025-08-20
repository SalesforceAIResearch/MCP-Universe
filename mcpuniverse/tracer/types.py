"""
Trace record data classes
"""
import re
import json
import inspect
import dataclasses
from collections import OrderedDict
from typing import Dict, Union, List
from dataclasses import dataclass


@dataclass
class BaseDataClass:
    """
    Base class for trace data objects.

    This class provides common functionality for loading, converting, and
    accessing data for trace-related objects.
    """

    @classmethod
    def load(cls, data: Union[Dict, str]):
        """
        Load a data object from a dict or a JSON string.

        Args:
            data (Union[Dict, str]): The data to load, either as a dictionary or JSON string.

        Returns:
            BaseDataClass: An instance of the class initialized with the provided data.
        """
        if data is None:
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls.from_json(data)

    @classmethod
    def from_dict(cls, data: Dict):
        """
        Load a data object from a dict.

        Args:
            data (Dict): The dictionary containing the data to load.

        Returns:
            BaseDataClass: An instance of the class initialized with the provided data.
        """
        return cls(**data)

    @classmethod
    def from_json(cls, data: str):
        """
        Load a data object from a JSON string.

        Args:
            data (str): The JSON string containing the data to load.

        Returns:
            BaseDataClass: An instance of the class initialized with the provided data.
        """
        return cls.from_dict(json.loads(data))

    def to_dict(self) -> Dict:
        """
        Convert a data object to a dict.

        Returns:
            Dict: An ordered dictionary representation of the object.
        """
        return OrderedDict(dataclasses.asdict(self))

    def to_json(self) -> str:
        """
        Convert a data object to a JSON string.

        Returns:
            str: A JSON string representation of the object.
        """
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def get_field_names(cls) -> List[dataclasses.Field]:
        """
        Get the field names of the class.

        Returns:
            List[dataclasses.Field]: A list of Field objects representing the class fields.
        """
        members = inspect.getmembers(cls)
        fields = list(dict(members)['__dataclass_fields__'].values())
        return fields

    @classmethod
    def get_class_name(cls, snake_case: bool = False) -> str:
        """
        Get the class name.

        Args:
            snake_case (bool, optional): If True, return the name in snake_case format. Defaults to False.

        Returns:
            str: The class name in the specified format.
        """
        if not snake_case:
            return cls.__name__
        return re.sub(r"([a-z])([A-Z])", r"\1_\2", cls.__name__).lower()


@dataclass
class DataRecord(BaseDataClass):
    """
    A single data record containing a timestamp and associated data.

    Attributes:
        timestamp (float): The timestamp of the record.
        data (dict): The data associated with the record.
    """
    timestamp: float
    data: dict


@dataclass
class TraceRecord(BaseDataClass):
    """
    A trace record containing information about a specific trace.

    Attributes:
        id (str): The unique identifier for this trace record.
        trace_id (str): The identifier for the overall trace.
        parent_id (str): The identifier of the parent trace record.
        records (List[DataRecord]): A list of DataRecord objects associated with this trace.
        running_time (float): The total running time of the trace.
        timestamp (float): The timestamp of the trace record.
        span_index (int): The index of this span within the trace.
    """
    id: str
    trace_id: str
    parent_id: str
    records: List[DataRecord]
    running_time: float
    timestamp: float
    span_index: int

    @classmethod
    def from_dict(cls, data: Dict):
        """
        Load a TraceRecord object from a dict.

        This method overrides the base class method to handle the conversion
        of records from dict to DataRecord objects.

        Args:
            data (Dict): The dictionary containing the data to load.

        Returns:
            TraceRecord: An instance of the TraceRecord class initialized with the provided data.
        """
        o = cls(**data)
        for i, r in enumerate(o.records):
            if isinstance(r, dict):
                o.records[i] = DataRecord.from_dict(r)
        return o
