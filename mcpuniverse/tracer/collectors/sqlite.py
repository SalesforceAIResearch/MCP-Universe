"""
Provides a SQLite3-based trace collector for storing and retrieving trace records.
"""
import os
import json
from typing import List, Any

import sqlite3
from dotenv import load_dotenv
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.tracer.types import TraceRecord

load_dotenv()


class SQLiteCollector(BaseCollector):
    """
    A collector for storing trace records in a SQLite database.

    This class implements the BaseCollector interface for SQLite storage.
    It handles database connection, table creation, and CRUD operations
    for TraceRecord objects.
    """

    def __init__(self, name: str = ""):
        """
        Initialize a new SQLiteCollector instance.

        Args:
            name (str, optional): The name of the SQLite database file.
                If not provided, defaults to "traces".

        Raises:
            AssertionError: If the SQLITE_TRACER_COLLECTOR_ADDRESS environment
                variable is not set or empty.
        """
        self._address = os.environ["SQLITE_TRACER_COLLECTOR_ADDRESS"]
        assert self._address, "SQLite address is empty"
        self._db_name = name if name else "traces"
        self._db = None
        self._create_table(TraceRecord)

    def __del__(self):
        if self._db is not None:
            self._db.close()

    def _connect_db(self):
        self._db = sqlite3.connect(os.path.join(self._address, self._db_name))

    def _create_table(self, data_class: Any):
        """
        Create a table in the SQLite database based on the given data class.

        Args:
            data_class (Type[TraceRecord]): The data class used to define
                the table schema.

        Note:
            This method creates a table with columns corresponding to the
            fields of the data class. The 'id' field is treated as a unique
            identifier.
        """
        self._connect_db()
        cursor = self._db.cursor()
        table_name = data_class.get_class_name()
        fields = data_class.get_field_names()
        type_map = {int: "INTEGER", float: "REAL"}
        definitions = []
        for field in fields:
            if field.name != "id":
                definitions.append(f"{field.name} {type_map.get(field.type, 'TEXT')}")
            else:
                definitions.append(f"{field.name} {type_map.get(field.type, 'TEXT')} UNIQUE")
        create_table_query = f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                {', '.join(definitions)}
            );
            '''
        cursor.execute(create_table_query)
        self._db.commit()

    def insert(self, record: TraceRecord):
        """
        Insert a TraceRecord into the SQLite database.

        Args:
            record (TraceRecord): The trace record to be inserted.

        Note:
            This method automatically serializes complex data types to JSON
            before insertion.
        """
        self._connect_db()
        cursor = self._db.cursor()
        table_name = type(record).get_class_name()
        fields = type(record).get_field_names()
        insert_query = f'''
                    INSERT INTO {table_name} ({', '.join(field.name for field in fields)})
                    VALUES ({', '.join('?' * len(fields))});
                    '''
        values = record.to_dict()
        data = tuple(values[field.name] if field.type in [str, int, float] else json.dumps(values[field.name])
                     for field in fields)
        cursor.execute(insert_query, data)
        self._db.commit()

    def get(self, trace_id: str) -> List[TraceRecord]:
        """
        Retrieve TraceRecords from the database by trace ID.

        Args:
            trace_id (str): The unique identifier of the trace.

        Returns:
            List[TraceRecord]: A list of TraceRecord objects matching the given trace_id.

        Note:
            This method automatically deserializes JSON-encoded fields back into
            their original data types.
        """
        self._connect_db()
        cursor = self._db.cursor()
        table_name = TraceRecord.get_class_name()
        fields = TraceRecord.get_field_names()

        values = (trace_id,)
        select_query = f"SELECT {', '.join(field.name for field in fields)} FROM {table_name} WHERE trace_id = ?"
        cursor.execute(select_query + ";", values)
        records = cursor.fetchall()

        outputs = []
        for record in records:
            assert len(record) == len(fields), "Database record is inconsistent"
            d = {field.name: record[i] if field.type in [str, int, float] else json.loads(record[i])
                 for i, field in enumerate(fields)}
            outputs.append(TraceRecord.from_dict(d))
        return outputs
