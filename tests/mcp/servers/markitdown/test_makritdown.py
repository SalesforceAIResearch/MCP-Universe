import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestMarkitdown(unittest.IsolatedAsyncioTestCase):
    """
    Markitdown MCP server: https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="markitdown")
        tools = await client.list_tools()
        print(tools)
        r = await client.execute_tool(
            "convert_to_markdown", arguments={"uri": "https://en.wikipedia.org/wiki/Chihuahua_(state)"})
        print(r)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
