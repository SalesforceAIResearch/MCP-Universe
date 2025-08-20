import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.agent.utils import get_tools_description


class TestGoogleSheets(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="google-sheets")
        tools = await client.list_tools()
        print(tools)
        results = await client.execute_tool("list_spreadsheets", arguments={})
        print(results)
        print(get_tools_description({"google-sheets": tools}))
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
