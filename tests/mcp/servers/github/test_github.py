import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestGithub(unittest.IsolatedAsyncioTestCase):
    """
    Github MCP server: https://github.com/modelcontextprotocol/servers/tree/main/src/github
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="github")
        tools = await client.list_tools()
        print(tools)
        result = await client.execute_tool(
            "search_repositories", arguments={"query": "kserve-helper"})
        print(result)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
