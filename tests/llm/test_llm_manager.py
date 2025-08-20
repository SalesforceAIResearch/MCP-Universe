import unittest
from mcpuniverse.llm.manager import ModelManager


class TestModelManager(unittest.TestCase):
    def test(self):
        manager = ModelManager()
        model = manager.build_model("openai", config={"model_name": "gpt-4o-mini"})
        self.assertIsNotNone(model)
        self.assertEqual(model.config.model_name, "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
