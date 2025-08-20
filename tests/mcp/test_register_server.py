import unittest
from mcpuniverse.mcp.manager import MCPManager


class TestRegisterServer(unittest.IsolatedAsyncioTestCase):

    async def test_register_server(self):
        manager = MCPManager()

        new_server_config = {
            "stdio": {
                "command": "python3",
                "args": ["-m", "my.dynamic.server"]
            },
            "env": {
                "API_KEY": "{{MY_API_KEY}}"
            }
        }
        manager.add_server_config("dynamic-server", new_server_config)
        self.assertTrue("dynamic-server" in manager.list_server_names())
        config = manager.get_config("dynamic-server")
        self.assertIsNotNone(config)

        updated_config = {
            "stdio": {
                "command": "python3",
                "args": ["-m", "my.updated.server", "--verbose"]
            },
            "sse": {
                "command": "python3",
                "args": ["-m", "my.updated.server", "--transport", "sse", "--port", "{{PORT}}"]
            }
        }
        manager.update_server_config("dynamic-server", updated_config)
        config = manager.get_config("dynamic-server")
        self.assertEqual(config.sse.command, "python3")

        manager.remove_server_config("dynamic-server")
        self.assertTrue("dynamic-server" not in manager.list_server_names())


if __name__ == "__main__":
    unittest.main()
