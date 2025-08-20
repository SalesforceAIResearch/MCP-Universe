import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.function_call import FunctionCall
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.workflows.chain import Chain
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import Printer


class TestChain(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        mcp_manager = MCPManager()
        llm = ModelManager().build_model(name="openai")
        chain = Chain(
            agents=[
                BasicAgent(
                    mcp_manager=mcp_manager,
                    llm=llm,
                    config={
                        "instruction": "Return the latitude and the longitude of a place"
                    }
                ),
                FunctionCall(
                    mcp_manager=mcp_manager,
                    llm=llm,
                    config={
                        "instruction": "You are an agent for weather forecast. "
                                       "Please return the weather today at the given latitude and longitude",
                        "servers": [{"name": "weather"}]
                    }
                ),
                BasicAgent(
                    llm=llm,
                    config={
                        "instruction": "Summarize the weather forecasting results"
                    }
                )
            ]
        )
        await chain.initialize()
        output_format = {"weather": "<Weather forecast results>"}
        response = await chain.execute(
            message="San Francisco",
            output_format=output_format,
            tracer=tracer,
            callbacks=Printer()
        )
        print(response)
        await chain.cleanup()
        pprint.pprint(tracer.get_trace())


if __name__ == "__main__":
    unittest.main()
