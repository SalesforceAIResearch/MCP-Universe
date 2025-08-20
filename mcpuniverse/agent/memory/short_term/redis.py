"""
A redis-based short-term memory for agents.
"""
import json
from typing import Dict, Union, Optional
from dataclasses import dataclass

import redis
from pydantic_core import from_json
from mcpuniverse.common.config import BaseConfig
from ..base import BaseMemory, MemoryRecord


@dataclass
class RedisMemoryConfig(BaseConfig):
    """
    Configuration for a redis-based short-team memory.

    Attributes:
        max_num_records (int): The maximum number of records in the memory.
    """
    host: str = "localhost"
    port: int = 6379
    max_num_records: int = 100
    expiration_time: int = 600


class RedisMemory(BaseMemory):
    """
    The class for a redis-based short-term memory for agents.
    """
    config_class = RedisMemoryConfig
    alias = ["redis"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize a redis-based short-term memory.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the memory.
                Can be a dictionary or a string. If None, default configuration will be used.
        """
        super().__init__()
        self.config = RedisMemory.config_class.load(config)
        self._redis = redis.Redis(host=self.config.host, port=self.config.port)

    def add(self, record: MemoryRecord):
        """
        Add a memory record.

        Args:
            record (MemoryRecord): A memory record.
        """
        n = self._redis.llen(record.agent_id)
        data = json.dumps(record.model_dump(mode="json"))
        if n < max(self.config.max_num_records, 1):
            self._redis.rpush(record.agent_id, data)
        else:
            self._redis.lpop(record.agent_id)
            self._redis.rpush(record.agent_id, data)
        self._redis.expire(record.agent_id, self.config.expiration_time)

    def retrieve(self, agent_id: str, **kwargs) -> str:
        """
        Retrieve all the memory.

        Args:
            agent_id (str): The agent ID.

        Return:
            str: Stored memory.
        """
        values = self._redis.lrange(agent_id, 0, -1)
        self._redis.expire(agent_id, self.config.expiration_time)
        records = [MemoryRecord.model_validate(from_json(v)) for v in values]
        return self.memory_to_str(records)

    def remove_all(self, agent_id: str):
        """
        Remove all the memory records.

        Args:
            agent_id (str): The agent ID.
        """
        self._redis.ltrim(agent_id, 1, 0)
