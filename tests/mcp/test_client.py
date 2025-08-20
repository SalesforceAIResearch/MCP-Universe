import unittest
import socket
from mcpuniverse.mcp.manager import MCPManager


class TestMCPClient(unittest.IsolatedAsyncioTestCase):

    async def test_client(self):
        manager = MCPManager()
        client = await manager.build_client(server_name="weather", transport="stdio")
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "get_alerts")
        self.assertEqual(tools[1].name, "get_forecast")
        await client.cleanup()

    async def test_client_sse(self):
        port = 8000
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) != 0:
                return
        manager = MCPManager()
        client = await manager.build_client(server_name="weather", transport="sse")
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "get_alerts")
        self.assertEqual(tools[1].name, "get_forecast")
        await client.cleanup()

        client = await manager.build_client(server_name="echo", transport="sse")
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "echo_tool")
        output = await client.execute_tool(tool_name="echo_tool", arguments={"text": "Hello world!"})
        self.assertEqual(output.content[0].text, "Hello world!")
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()
