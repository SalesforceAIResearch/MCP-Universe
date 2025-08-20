import unittest
import pytest
import pprint
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import Printer


class TestBasicAgent(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        agent = BasicAgent(
            llm=ModelManager().build_model(name="openai"),
            config={"instruction": "You are a Python developer"}
        )
        await agent.initialize()
        print(agent.get_description())
        response = await agent.execute(
            message="Write a quick sort algorithm",
            tracer=tracer,
            callbacks=Printer()
        )
        print(response)
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())


if __name__ == "__main__":
    unittest.main()
