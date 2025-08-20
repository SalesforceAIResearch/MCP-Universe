import unittest
import pytest
from mcpuniverse.callbacks.handlers.redis import RedisHandler
from mcpuniverse.callbacks.base import CallbackMessage, MessageType, Event


class TestRedisHandler(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        handler = RedisHandler()
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
