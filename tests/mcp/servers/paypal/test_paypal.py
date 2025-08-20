import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestPayPal(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_server(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="paypal")
        tools = await client.list_tools()
        print(tools)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
