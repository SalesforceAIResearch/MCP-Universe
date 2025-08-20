import unittest
from mcpuniverse.mcp.manager import MCPManager


class TestGoogleSearch(unittest.IsolatedAsyncioTestCase):

    async def test_search(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="google-search")
        tools = await client.list_tools()
        self.assertEqual(len(tools), 1)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
