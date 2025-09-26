import os
import unittest
from mcpuniverse.pipeline.launcher import AgentLauncher


class TestLauncher(unittest.TestCase):

    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(folder, "../data/collection/agent-collection.yaml")
        launcher = AgentLauncher(config_path=config_path)
        agent_collection = launcher.create_agents()
        self.assertEqual(len(agent_collection["agent-collection-1"]), 1)
        self.assertEqual(len(agent_collection["agent-collection-2"]), 2)
        self.assertEqual(len(agent_collection["agent-collection-3"]), 2)


if __name__ == "__main__":
    unittest.main()
