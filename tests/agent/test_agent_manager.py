import os
import unittest
import pytest
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.manager import AgentManager
from mcpuniverse.mcp.manager import MCPManager


class TestAgentManager(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        manager = AgentManager()
        agent = manager.build_agent(
            class_name="basic",
            llm=ModelManager().build_model(name="openai")
        )
        await agent.initialize()
        print(agent.get_description())
        response = await agent.execute(message="Write a quick sort algorithm")
        print(response)
        await agent.cleanup()

    async def test_check(self):
        os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"] = "xxx"
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = ""
        manager = AgentManager()
        agent = manager.build_agent(
            class_name="function_call",
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "servers": [{"name": "google-sheets"}]
            }
        )
        r = agent.list_undefined_env_vars()
        self.assertListEqual(r, ["GOOGLE_DRIVE_FOLDER_ID"])


if __name__ == "__main__":
    unittest.main()
