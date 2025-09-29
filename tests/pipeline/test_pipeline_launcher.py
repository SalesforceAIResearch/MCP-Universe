import os
import unittest
import pytest
from mcpuniverse.pipeline.launcher import PipelineLauncher


class TestPipelineLauncher(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_path = os.path.join(folder, "../data/collection/agent-collection.yaml")
        launcher = PipelineLauncher(config_path)
        launcher.start_celery_workers()


if __name__ == "__main__":
    unittest.main()
