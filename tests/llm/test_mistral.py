import os
import unittest
import pytest
from pydantic import BaseModel
from mcpuniverse.llm.mistral import MistralModel


class Response(BaseModel):
    code: str
    explanation: str


class TestMistral(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = MistralModel(config={"model_name": "open-mistral-nemo"})
        system_message = "As a professional python developer"
        user_message = """
        please write a program to generate a fibonacci sequence. The output should be in a json format as follows: 
        {"code": the generated code, "explanation": explain the generated code}
        """
        response = model.get_response(system_message, user_message, response_format=Response)
        print(response.code)
        print(response.explanation)

    def test_list_undefined_env_vars(self):
        os.environ["MISTRAL_API_KEY"] = ""
        model = MistralModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["MISTRAL_API_KEY"])

        os.environ["MISTRAL_API_KEY"] = "xxx"
        model = MistralModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
