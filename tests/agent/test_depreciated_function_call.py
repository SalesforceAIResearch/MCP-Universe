import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.depreciated_function_call import DepreciatedFunctionCall
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import SQLiteCollector
from mcpuniverse.callbacks.base import Printer
from mcpuniverse.callbacks.handlers.redis import RedisHandler
from mcpuniverse.callbacks.handlers.sqlite import SQLiteHandler


class TestDepreciatedFunctionCall(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer(collector=SQLiteCollector())
        agent = DepreciatedFunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are an agent for weather forecast",
                "servers": [{"name": "weather"}]
            }
        )
        await agent.initialize()
        print(agent.get_description())
        output_format = {"weather": "<Weather forecast results>"}
        response = await agent.execute(
            message="what is the weather today at 34.05° N latitude and 118.25° W longitude?",
            output_format=output_format,
            tracer=tracer,
            callbacks=[Printer(), RedisHandler(), SQLiteHandler()]
        )
        print(response)
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    @pytest.mark.skip
    async def test_google_sheets(self):
        tracer = Tracer()
        agent = DepreciatedFunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are an agent for managing Google Sheets",
                "servers": [{"name": "google-sheets"}, {"name": "weather"}]
            }
        )
        await agent.initialize()
        print(agent.get_description())
        response = await agent.execute(
            message="list all spreadsheets in the Google Drive folder",
            tracer=tracer
        )
        print(response)
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())


if __name__ == "__main__":
    unittest.main()
