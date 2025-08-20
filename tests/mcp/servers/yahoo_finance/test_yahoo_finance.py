import unittest
import pytest
from mcpuniverse.mcp.servers.yahoo_finance.server import build_server


class TestYahooFinance(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mcp = build_server(port=12345)

    @pytest.mark.skip
    async def test_search(self):
        tools = await self.mcp.list_tools()
        print(tools)
        result = await self.mcp.call_tool("get_stock_info", arguments={"ticker": "AAPL"})
        print(result)


if __name__ == "__main__":
    unittest.main()
