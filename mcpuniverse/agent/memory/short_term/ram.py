"""
An in-memory short-term memory for agents.
"""
from typing import Dict, Union, Optional
from dataclasses import dataclass
from collections import defaultdict, deque
from mcpuniverse.common.config import BaseConfig
from ..base import BaseMemory, MemoryRecord


@dataclass
class RAMConfig(BaseConfig):
    """
    Configuration for an in-memory short-team memory.

    Attributes:
        max_num_records (int): The maximum number of records in the memory.
    """
    max_num_records: int = 100


class RAM(BaseMemory):
    """
    The class for an in-memory short-term memory for agents.
    """
    config_class = RAMConfig
    alias = ["ram", "in-memory"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        """
        Initialize an in-memory short-term memory.

        Args:
            config (Optional[Union[Dict, str]]): Configuration for the memory.
                Can be a dictionary or a string. If None, default configuration will be used.
        """
        super().__init__()
        self.config = RAM.config_class.load(config)
        self._memory: Dict[str, deque] = defaultdict(deque)

    def add(self, record: MemoryRecord):
        """
        Add a memory record.

        Args:
            record (MemoryRecord): A memory record.
        """
        agent_id = record.agent_id
        if len(self._memory.get(agent_id, [])) < max(self.config.max_num_records, 1):
            self._memory[agent_id].append(record)
        else:
            self._memory[agent_id].popleft()
            self._memory[agent_id].append(record)

    def retrieve(self, agent_id: str, **kwargs) -> str:
        """
        Retrieve all the memory.

        Args:
            agent_id (str): The agent ID.

        Return:
            str: Stored memory.
        """
        return self.memory_to_str(self._memory.get(agent_id, []))

    def remove_all(self, agent_id: str):
        """
        Remove all the memory records.

        Args:
            agent_id (str): The agent ID.
        """
        self._memory = defaultdict(deque)
