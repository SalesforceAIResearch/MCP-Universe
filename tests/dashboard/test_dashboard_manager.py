import os
import unittest
from mcpuniverse.dashboard.manager import Manager


class TestDashboardManager(unittest.TestCase):

    def test_add_agent(self):
        if not os.environ.get("OPENAI_API_KEY", ""):
            return
        manager = Manager()
        config = """
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  is_main: true
  config:
    llm: llm-1
    instruction: You are an agent for weather forecasting.
    servers:
      - name: weather
        """
        manager.upsert_agent(name="weather", config=config)

    def test_add_mcp(self):
        manager = Manager()
        config = """
{
    "stdio": {
      "command": "python3",
      "args": [
        "-m", "mcpuniverse.mcp.servers.weather"
      ]
    },
    "sse": {
      "command": "python3",
      "args": [
        "-m", "mcpuniverse.mcp.servers.weather",
        "--transport", "sse",
        "--port", "{{PORT}}"
      ]
    }
}
        """
        manager.upsert_mcp_server(name="weather-1", config=config)


if __name__ == "__main__":
    unittest.main()
