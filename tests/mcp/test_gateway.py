import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestGateway(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_connection(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="fetch", transport="sse")
        tools = await client.list_tools()
        print(tools)
        r = await client.execute_tool(
            "fetch", arguments={"url": "https://www.promptingguide.ai/agents/introduction"})
        print(r)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
