import os
import unittest
import pytest
from mcpuniverse.pipeline.task import AgentTask


class TestAgentTask(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(folder, "../data/collection/agent-collection.yaml")
        task = AgentTask(config_path)

        task_config = {
            "category": "general",
            "question": "What's the weather in San Francisco now?",
            "mcp_servers": [
                {
                    "name": "weather"
                }
            ],
            "output_format": {
                "city": "<CITY>",
                "weather": "<Weather forecast results>"
            },
            "evaluators": [
                {
                    "func": "json -> get(city)",
                    "op": "=",
                    "value": "San Francisco"
                }
            ]
        }
        task.run(
            agent_collection_name="agent-collection-1",
            agent_index=0,
            task_config=task_config
        )


if __name__ == "__main__":
    unittest.main()
