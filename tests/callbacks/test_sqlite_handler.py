import unittest
import pytest
from mcpuniverse.callbacks.handlers.sqlite import SQLiteHandler
from mcpuniverse.callbacks.base import CallbackMessage, MessageType, Event


class TestSQLiteHandler(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        handler = SQLiteHandler()
        message = CallbackMessage(
            source="test",
            type=MessageType.EVENT,
            data=Event.BEFORE_CALL,
            metadata={"method": "test"}
        )
        handler(message)
        records = handler.get(source="test", message_type=MessageType.EVENT)
        print(records)


if __name__ == "__main__":
    unittest.main()
