import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestFetch(unittest.IsolatedAsyncioTestCase):
    """
    Fetch MCP server: https://github.com/modelcontextprotocol/servers/tree/main/src/fetch
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="fetch")
        tools = await client.list_tools()
        print(tools)
        r = await client.execute_tool(
            "fetch", arguments={"url": "https://en.wikipedia.org/wiki/Chihuahua_(state)"})
        print(r)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
