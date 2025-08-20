import unittest
import pytest
from mcpuniverse.llm.openai_agent import OpenAIAgentModel


class TestOpenAIAgent(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = OpenAIAgentModel(config={"model_name": "gpt-4.1"})
        system_message = "As OpenAI smart agent"
        user_message = "What transport protocols are supported in the 2025-03-26 version of the MCP spec?"
        response = model.get_response(
            system_message,
            user_message,
            remote_mcp=[
                {
                    "type": "mcp",
                    "server_label": "deepwiki",
                    "server_url": "https://mcp.deepwiki.com/mcp",
                    "require_approval": "never",
                }
            ]
        )
        print(response)


if __name__ == "__main__":
    unittest.main()
