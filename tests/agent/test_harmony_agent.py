import unittest
import pytest

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.llm.openrouter import OpenRouterModel
from mcpuniverse.agent.harmony_agent import HarmonyReAct
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import Printer
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks


class TestHarmonyAgent(unittest.IsolatedAsyncioTestCase):

    async def test_prompt(self):
        """Ensure Harmony prompt includes history and question."""
        llm = ModelManager().build_model(name="openrouter", config={"model_name": "GPTOSS120B_OR"})
        agent = HarmonyReAct(
            mcp_manager=MCPManager(),
            llm=llm,
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        # Add minimal history entries
        agent._add_history(
            analysis="History 1: thinking about the task",
        )
        agent._add_history(
            analysis="History 2: preparing to call a tool",
        )
        prompt = agent._build_prompt(question="What's the weather in San Francisco now?")

        # History content should be present in the prompt
        self.assertIn("History 1", prompt)
        self.assertIn("History 2", prompt)
        # The question should be present
        self.assertIn("What's the weather in San Francisco now?", prompt)
        await agent.cleanup()

    @pytest.mark.skip
    async def test_execute(self):
        llm = ModelManager().build_model(name="openrouter", config={"model_name": "GPTOSS120B_OR"})
        # Ensure the correct LLM and model are used
        self.assertIsInstance(llm, OpenRouterModel)
        self.assertEqual(llm.config.model_name, "GPTOSS120B_OR")

        tracer = Tracer()
        agent = HarmonyReAct(
            mcp_manager=MCPManager(),
            llm=llm,
            config={
                "instruction": "You are a helpful assistant.",
                "max_iterations": 2,
                "servers": [{"name": "weather"}]
            }
        )
        await agent.initialize()
        response = await agent.execute(
            message="What's the current weather in San Francisco?",
            tracer=tracer,
            callbacks=[Printer()] + get_vprint_callbacks()
        )

        self.assertIsNotNone(response)
        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
