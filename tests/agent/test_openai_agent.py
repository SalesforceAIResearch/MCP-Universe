import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import SQLiteCollector
from mcpuniverse.callbacks.base import Printer


class TestOpenAIAgent(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer(collector=SQLiteCollector())
        agent = BasicAgent(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(
                name="openai-agent",
                config={"model_name": "gpt-4.1"}
            ),
            config={
                "instruction": "You are an agent for weather forecast",
                "servers": [{"name": "weather"}],
                "mcp_gateway_url": "https://c132867eabac.ngrok-free.app",
                "use_llm_tool_api": "yes"
            }
        )
        await agent.initialize()
        print(agent.get_description())
        output_format = {"weather": "<Weather forecast results>"}
        response = await agent.execute(
            message="what is the weather today at 34.05° N latitude and 118.25° W longitude?",
            output_format=output_format,
            tracer=tracer,
            callbacks=[Printer()]
        )
        print(response)
        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
