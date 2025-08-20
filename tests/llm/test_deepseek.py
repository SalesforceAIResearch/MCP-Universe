import os
import unittest
import pytest
from pydantic import BaseModel
from mcpuniverse.llm.deepseek import DeepSeekModel
from mcpuniverse.common.context import Context


class Response(BaseModel):
    code: str
    explanation: str


class TestDeepSeek(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = DeepSeekModel()
        system_message = "As a professional python developer"
        user_message = """
        please write a program to generate a fibonacci sequence. The output should be in a json format as follows: 
        {"code": the generated code, "explanation": explain the generated code}
        """
        response = model.get_response(system_message, user_message, response_format=Response)
        print(response.code)
        print(response.explanation)

    def test_list_undefined_env_vars(self):
        os.environ["DEEPSEEK_API_KEY"] = ""
        model = DeepSeekModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["DEEPSEEK_API_KEY"])

        context = Context(env={"DEEPSEEK_API_KEY": "xxx"})
        model = DeepSeekModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
