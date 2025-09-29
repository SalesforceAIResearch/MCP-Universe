import os
import unittest
import pytest
from mcpuniverse.pipeline.launcher import AgentPipeline


class TestAgentPipeline(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(folder, "../data/collection/agent-collection.yaml")
        launcher = AgentPipeline(config_path)

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
        a = launcher._get_queue_size(queue_name='agent-collection-1_0')
        b = launcher._get_queue_size(queue_name='agent-collection-1_1')
        print(f"Queue size: {(a, b)}")

        launcher.send_task(
            agent_collection_name="agent-collection-1",
            task_config=task_config
        )
        launcher.send_task(
            agent_collection_name="agent-collection-1",
            task_config=task_config
        )
        a = launcher._get_queue_size(queue_name='agent-collection-1_0')
        b = launcher._get_queue_size(queue_name='agent-collection-1_1')
        print(f"Queue size: {(a, b)}")


if __name__ == "__main__":
    unittest.main()
