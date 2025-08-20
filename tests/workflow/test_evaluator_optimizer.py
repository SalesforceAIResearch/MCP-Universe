import unittest
import pytest
import pprint
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.workflows.evaluator_optimizer import EvaluatorOptimizer
from mcpuniverse.tracer import Tracer


class TestEvaluatorOptimizer(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        tracer = Tracer()
        llm = ModelManager().build_model(name="openai")
        workflow = EvaluatorOptimizer(
            optimizer=BasicAgent(
                llm=llm,
                config={"instruction": "You are a Python developer. Write high quality code for user requests."}
            ),
            evaluator=BasicAgent(
                llm=llm,
                config={"instruction": "You are an expert in Python. Check whether the input code is optimized, "
                                       "and provide feedbacks on how to optimize it."}
            )
        )
        await workflow.initialize()
        output_format = {"code": "<Generated Python code>"}
        response = await workflow.execute(
            message="write a quick sort algorithm", output_format=output_format, tracer=tracer)
        print(response)
        await workflow.cleanup()
        pprint.pprint(tracer.get_trace())


if __name__ == "__main__":
    unittest.main()
