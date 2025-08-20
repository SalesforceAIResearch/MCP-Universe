import unittest
from mcpuniverse.agent.memory.short_term.redis import RedisMemory, MemoryRecord


class TestShortTermRedisMemory(unittest.TestCase):

    def test_1(self):
        memory = RedisMemory()
        memory.remove_all("123")
        memory.add(MemoryRecord(
            agent_id="123",
            tag="system",
            content="test"
        ))
        memory.add(MemoryRecord(
            agent_id="123",
            tag="user",
            content="yes"
        ))
        res = memory.retrieve(agent_id="123")
        self.assertEqual(res, "system: test\nuser: yes")
        res = memory.retrieve(agent_id="1")
        self.assertEqual(res, "")

    def test_2(self):
        memory = RedisMemory({"max_num_records": 1})
        memory.remove_all("456")
        memory.add(MemoryRecord(
            agent_id="456",
            tag="system",
            content="test"
        ))
        memory.add(MemoryRecord(
            agent_id="456",
            tag="user",
            content="yes"
        ))
        res = memory.retrieve(agent_id="456")
        self.assertEqual(res, "user: yes")


if __name__ == "__main__":
    unittest.main()
