import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestFilesystem(unittest.IsolatedAsyncioTestCase):
    """
    Filesystem MCP server: https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="filesystem")
        tools = await client.list_tools()
        print(tools)
        results = await client.execute_tool("list_allowed_directories", arguments={})
        print(results)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
