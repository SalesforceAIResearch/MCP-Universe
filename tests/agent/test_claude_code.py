import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.agent.claude_code import ClaudeCodeAgent
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import SQLiteCollector
from mcpuniverse.callbacks.base import Printer
from mcpuniverse.callbacks.handlers.redis import RedisHandler
from mcpuniverse.callbacks.handlers.sqlite import SQLiteHandler


class TestClaudeCodeAgent(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer(collector=SQLiteCollector())
        agent = ClaudeCodeAgent(
            mcp_manager=MCPManager(),
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


if __name__ == "__main__":
    unittest.main()
