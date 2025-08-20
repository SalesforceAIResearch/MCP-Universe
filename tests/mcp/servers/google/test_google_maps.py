import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestGoogleMaps(unittest.IsolatedAsyncioTestCase):
    """
    MCP for Google Maps: https://github.com/modelcontextprotocol/servers/tree/main/src/google-maps

    Get a Google Maps API key by following the instructions:
    https://developers.google.com/maps/documentation/javascript/get-api-key#create-api-keys
    """

    @pytest.mark.skip
    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="google-maps")
        tools = await client.list_tools()
        self.assertEqual(len(tools), 7)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
