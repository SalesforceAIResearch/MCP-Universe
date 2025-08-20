import unittest
import pytest
import pprint
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.agent.function_call import FunctionCall
from mcpuniverse.workflows.orchestrator import Orchestrator
from mcpuniverse.tracer import Tracer


class TestOrchestrator(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        mcp_manager = MCPManager()
        llm = ModelManager().build_model(name="openai")
        workflow = Orchestrator(
            llm=llm,
            agents=[
                BasicAgent(
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
                )
            ]
        )
        await workflow.initialize()
        output_format = {"city": "<City>", "weather": "<Weather forecast results>"}
        response = await workflow.execute(
            message="what is the weather today in San Francisco?", output_format=output_format, tracer=tracer)
        print(response)
        pprint.pprint(tracer.get_trace())
        await workflow.cleanup()


if __name__ == "__main__":
    unittest.main()
