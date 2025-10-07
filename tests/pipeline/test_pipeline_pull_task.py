import os
import unittest
import pytest
from mcpuniverse.pipeline.launcher import AgentPipeline


class TestPipelinePullTask(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(folder, "../data/collection/agent-collection.yaml")
        launcher = AgentPipeline(config_path)
        for output in launcher.pull_task_outputs():
            print("Received:")
            print(output)


if __name__ == "__main__":
    unittest.main()
