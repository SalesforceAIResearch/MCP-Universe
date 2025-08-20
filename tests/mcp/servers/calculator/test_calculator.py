import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestCalculator(unittest.IsolatedAsyncioTestCase):
    """
    Calculator MCP server: https://github.com/githejie/mcp-server-calculator
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="calculator")
        tools = await client.list_tools()
        print(tools)
        results = await client.execute_tool("calculate", arguments={"expression": "1 + 2"})
        print(results)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
