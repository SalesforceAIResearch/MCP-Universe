import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.reflection import Reflection
from mcpuniverse.tracer import Tracer


class TestReflectionAgent(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_execute(self):
        question = "I live in San Francisco. Do I need to bring an umbrella if I need to go outside?"
        tracer = Tracer()
        agent = Reflection(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        response = await agent.execute(message=question, tracer=tracer)
        print(response)
        print(agent.get_history())
        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
