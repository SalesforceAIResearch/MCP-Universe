import unittest
from mcpuniverse.mcp.servers.weather.server import build_server


class TestWeather(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mcp = build_server(port=12345)

    async def test_server(self):
        tools = await self.mcp.list_tools()
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0].name, "get_alerts")
        self.assertEqual(tools[1].name, "get_forecast")


if __name__ == "__main__":
    unittest.main()
