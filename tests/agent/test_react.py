import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.react import ReAct
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import Printer
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks


class TestReActAgent(unittest.IsolatedAsyncioTestCase):

    async def test_prompt(self):
        agent = ReAct(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        agent._history.append("History 1")
        agent._history.append("History 2")
        prompt = agent._build_prompt(question="What's the weather in San Francisco now?")
        self.assertTrue("History 1" in prompt)
        self.assertTrue("History 2" in prompt)
        self.assertTrue("What's the weather in San Francisco now?" in prompt)
        await agent.cleanup()

    @pytest.mark.skip
    async def test_execute(self):
        question = "I live in San Francisco. Do I need to bring an umbrella if I need to go outside?"
        tracer = Tracer()
        agent = ReAct(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        response = await agent.execute(
            message=question,
            tracer=tracer,
            callbacks=[Printer()] + get_vprint_callbacks()
        )
        print(response)
        print(agent.get_history())
        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
