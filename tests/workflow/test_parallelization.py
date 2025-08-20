import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.agent.function_call import FunctionCall
from mcpuniverse.workflows.parallelization import Parallelization
from mcpuniverse.tracer import Tracer


class TestParallelization(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        mcp_manager = MCPManager()
        llm = ModelManager().build_model(name="openai")
        agent = Parallelization(
            agents=[
                BasicAgent(
                    mcp_manager=mcp_manager,
                    llm=llm,
                    config={
                        "instruction": "Describe the place at the given latitude and the longitude"
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
                )
            ],
            aggregator=BasicAgent(
                mcp_manager=mcp_manager,
                llm=llm,
                config={
                    "instruction": "Merge the results from the agents and return a summary"
                }
            )
        )
        await agent.initialize()
        output_format = {"summary": "<Summarized results>"}
        response = await agent.execute(
            message="34.05° N latitude and 118.25° W longitude", output_format=output_format, tracer=tracer)
        print(response)
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())


if __name__ == "__main__":
    unittest.main()
