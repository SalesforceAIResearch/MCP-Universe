import os
import unittest

from mcpuniverse.workflows.builder import WorkflowConfig


class TestWorkflowConfig(unittest.TestCase):

    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/yaml_config.yaml")
        objects = WorkflowConfig.load(config_file)
        self.assertEqual(objects[0].kind, "llm")
        self.assertEqual(objects[1].kind, "agent")


if __name__ == "__main__":
    unittest.main()
