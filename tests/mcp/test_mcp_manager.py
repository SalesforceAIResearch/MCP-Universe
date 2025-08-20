import unittest
from mcpuniverse.mcp.manager import MCPManager


class TestMCPManager(unittest.TestCase):

    def test(self):
        manager = MCPManager()
        print(manager.get_configs())
        print(manager.list_unspecified_params())
        manager.set_params("weather", {"PORT": 8001})
        print(manager.get_configs())
        print(manager.list_unspecified_params())


if __name__ == "__main__":
    unittest.main()
