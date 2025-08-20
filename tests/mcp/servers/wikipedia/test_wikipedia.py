import unittest
import pytest
from mcpuniverse.mcp.servers.wikipedia.server import build_server


class TestWikipedia(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mcp = build_server(port=12345)

    @pytest.mark.skip
    async def test_search(self):
        tools = await self.mcp.list_tools()
        self.assertEqual(len(tools), 1)
        result = await self.mcp.call_tool("search", arguments={"query": "Singapore"})
        print(result)


if __name__ == "__main__":
    unittest.main()
