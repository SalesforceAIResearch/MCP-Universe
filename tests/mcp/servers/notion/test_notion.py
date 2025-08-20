import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestNotion(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_notion(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="notion")
        tools = await client.list_tools()
        print(tools)
        results = await client.execute_tool("API-get-users", arguments={})
        print(results)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
