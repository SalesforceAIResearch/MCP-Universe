import os
import unittest
import pytest
from mcpuniverse.llm.gemini import GeminiModel
from mcpuniverse.common.context import Context


class TestGemini(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = GeminiModel()
        system_message = "As a professional python developer"
        user_message = "please write a program to generate a fibonacci sequence"
        response = model.get_response(system_message, user_message)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["GEMINI_API_KEY"] = ""
        model = GeminiModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["GEMINI_API_KEY"])

        context = Context(env={"GEMINI_API_KEY": "xxx"})
        model = GeminiModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
