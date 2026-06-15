import os
import unittest

from mcpuniverse.extensions.mcpplus.tools.wrap_mcp_config import (
    _get_gateway_env_vars,
    _get_gateway_llm_config_fields,
)


class TestWrapMcpConfigAzure(unittest.TestCase):

    def test_gateway_llm_config_fields(self):
        fields = _get_gateway_llm_config_fields("azure")
        self.assertEqual(fields, {
            "azure_endpoint": "$AZURE_API_BASE",
            "api_version": "$AZURE_API_VERSION",
        })

    def test_gateway_env_vars(self):
        os.environ["AZURE_API_KEY"] = "key-123"
        os.environ["AZURE_API_BASE"] = "https://example.openai.azure.com/"
        os.environ["AZURE_API_VERSION"] = "2024-12-01-preview"
        try:
            env_vars = _get_gateway_env_vars("azure")
            self.assertEqual(env_vars, {
                "AZURE_API_KEY": "key-123",
                "AZURE_API_BASE": "https://example.openai.azure.com/",
                "AZURE_API_VERSION": "2024-12-01-preview",
            })
        finally:
            del os.environ["AZURE_API_KEY"]
            del os.environ["AZURE_API_BASE"]
            del os.environ["AZURE_API_VERSION"]


if __name__ == "__main__":
    unittest.main()
