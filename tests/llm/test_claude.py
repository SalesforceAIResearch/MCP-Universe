import os
import unittest
import pytest
from pydantic import BaseModel
from mcpuniverse.llm.claude import ClaudeModel
from mcpuniverse.common.context import Context


class Response(BaseModel):
    code: str
    explanation: str


class TestClaude(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = ClaudeModel()
        system_message = "As a professional python developer"
        user_message = """
        please write a program to generate a fibonacci sequence. The output should be in a json format as follows: 
        {"code": the generated code, "explanation": explain the generated code}
        """
        response = model.get_response(system_message, user_message, response_format=Response)
        print(response.code)
        print(response.explanation)

    def test_list_undefined_env_vars(self):
        os.environ["ANTHROPIC_API_KEY"] = ""
        model = ClaudeModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["ANTHROPIC_API_KEY"])

        context = Context(env={"ANTHROPIC_API_KEY": "xxx"})
        model = ClaudeModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
