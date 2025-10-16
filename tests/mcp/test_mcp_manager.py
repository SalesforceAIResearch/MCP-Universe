import unittest
import pytest
import asyncio
from mcpuniverse.mcp.manager import MCPManager


class TestMCPManager(unittest.IsolatedAsyncioTestCase):

    async def test(self):
        manager = MCPManager()
        print(manager.get_configs())
        print(manager.list_unspecified_params())
        manager.set_params("weather", {"PORT": 8001})
        print(manager.get_configs())
        print(manager.list_unspecified_params())

    @pytest.mark.skip
    async def test_list_tools(self):
        manager = MCPManager()
        servers = manager.list_server_names()
        servers = [s for s in servers if s not in ["markitdown", "filesystem", "postgres", "paypal"]]
        results = await asyncio.gather(*[manager.list_tools(s) for s in servers])
        print(results)


if __name__ == "__main__":
    unittest.main()
