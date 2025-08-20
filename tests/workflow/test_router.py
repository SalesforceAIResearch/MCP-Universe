import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.function_call import FunctionCall
from mcpuniverse.workflows.router import Router
from mcpuniverse.tracer import Tracer


class TestRouter(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        mcp_manager = MCPManager()
        llm = ModelManager().build_model(name="openai")
        agent_a = FunctionCall(
            mcp_manager=mcp_manager,
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are an agent for managing Google Sheets",
                "servers": [{"name": "google-sheets"}]
            }
        )
        agent_b = FunctionCall(
            mcp_manager=mcp_manager,
            llm=llm,
            config={
                "instruction": "You are an agent for weather forecast. "
                               "Please return the weather today at the given latitude and longitude",
                "servers": [{"name": "weather"}]
            }
        )
        router = Router(
            llm=llm,
            agents=[agent_a, agent_b],
        )
        await router.initialize()
        response = await router.execute(
            message="what is the weather today at 34.05° N latitude and 118.25° W longitude?", tracer=tracer)
        print(response)
        pprint.pprint(tracer.get_trace())
        await router.cleanup()


if __name__ == "__main__":
    unittest.main()
