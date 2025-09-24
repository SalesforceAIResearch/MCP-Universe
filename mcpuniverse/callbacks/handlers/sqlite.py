"""
Provides a SQLite3-based callback handler for processing callback messages.
"""
import os
import json
from typing import Optional
from enum import Enum

import sqlite3
from dotenv import load_dotenv
from mcpuniverse.callbacks.base import CallbackMessage, BaseCallback

load_dotenv()


class SQLiteHandler(BaseCallback):
    """
    A callback handler for storing callback messages in a SQLite database.
    """

    def __init__(self, address: str = "", name: str = ""):
        """
        Initialize a new SQLiteHandler instance.

        Args:
            address (str, optional): The address of the SQLite database.
                If not provided, defaults to the environment variable "SQLITE_CALLBACK_HANDLER_ADDRESS".
            name (str, optional): The name of the SQLite database file.
                If not provided, defaults to "callback".
        """
        super().__init__()
        self._address = address if address else os.environ["SQLITE_CALLBACK_HANDLER_ADDRESS"]
        assert self._address, "SQLite address is empty"
        self._db_name = name if name else "callback"
        self._table_name = "message"
        self._fields = [
            ("source", "TEXT"),
            ("type", "VARCHAR(64)"),
            ("data", "TEXT"),
            ("metadata", "TEXT"),
            ("timestamp", "REAL"),
            ("project_id", "TEXT")
        ]
        self._keys = ("source", "type")
        self._db = None
        self._create_table()

    def __del__(self):
        if self._db is not None:
            self._db.close()

    def _connect_db(self):
        self._db = sqlite3.connect(os.path.join(self._address, self._db_name))

    def _create_table(self):
        """
        Create a table in the SQLite database for callback messages.

        Note:
            This method creates a table with columns corresponding to the
            fields of `CallbackMessage`.
        """
        self._connect_db()
        cursor = self._db.cursor()
        definitions = [f"{attr} {attr_type}" for attr, attr_type in self._fields]
        create_table_query = f'''
        CREATE TABLE IF NOT EXISTS {self._table_name} (
            {", ".join(definitions)},
            PRIMARY KEY ({", ".join(self._keys)})
        );
        '''
        cursor.execute(create_table_query)
        self._db.commit()

    def call(self, message: CallbackMessage, **kwargs):
        """
        Process the callback message, i.e., upsert the message into the SQLite database.

        Args:
            message (CallbackMessage): The message to be processed.
        """
        self.upsert(message)

    def insert(self, message: CallbackMessage):
        """
        Insert a callback message into the SQLite database.

        Args:
            message (CallbackMessage): The message to be inserted.
        """
        self._connect_db()
        cursor = self._db.cursor()
        insert_query = f'''
        INSERT INTO {self._table_name} ({', '.join(attr for attr, _ in self._fields)})
        VALUES ({', '.join('?' * len(self._fields))});
        '''
        values = message.model_dump(mode="json")
        data = tuple(values[attr] if isinstance(values[attr], (str, int, float)) else json.dumps(values[attr])
                     for attr, _ in self._fields)
        cursor.execute(insert_query, data)
        self._db.commit()

    def upsert(self, message: CallbackMessage):
        """
        Upsert a callback message into the SQLite database.

        Args:
            message (CallbackMessage): The message to be inserted.
        """
        self._connect_db()
        cursor = self._db.cursor()
        insert_query = f'''
        INSERT OR REPLACE INTO {self._table_name} ({', '.join(attr for attr, _ in self._fields)})
        VALUES ({', '.join('?' * len(self._fields))});
        '''
        values = message.model_dump(mode="json")
        data = tuple(values[attr] if isinstance(values[attr], (str, int, float)) else json.dumps(values[attr])
                     for attr, _ in self._fields)
        cursor.execute(insert_query, data)
        self._db.commit()

    def get(self, source: str, message_type: str | Enum) -> Optional[CallbackMessage]:
        """
        Retrieve callback messages from the database.

        Args:
            source (str): The unique identifier of the source.
            message_type (str | Enum): The message type, e.g., "event", "response", etc.

        Returns:
            CallbackMessage: A message object.

        Note:
            This method automatically deserializes JSON-encoded fields back into
            their original data types.
        """
        self._connect_db()
        cursor = self._db.cursor()
        if isinstance(message_type, Enum):
            message_type = message_type.value
        values = (source, message_type)
        select_query = (f"SELECT {', '.join(attr for attr, _ in self._fields)} FROM {self._table_name} "
                        f"WHERE source = ? AND type = ?;")
        cursor.execute(select_query, values)
        records = cursor.fetchall()

        outputs = []
        for record in records:
            d = {}
            for i, (attr, _) in enumerate(self._fields):
                if (isinstance(record[i], str) and
                        (record[i].startswith('"') or record[i].startswith('[') or record[i].startswith('{'))):
                    d[attr] = json.loads(record[i])
                else:
                    d[attr] = record[i]
            outputs.append(CallbackMessage.model_validate(d))
        return outputs[0] if outputs else None
