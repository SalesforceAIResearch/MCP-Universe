import os
import unittest
import pytest
from pydantic import BaseModel
from mcpuniverse.llm.ollama import OllamaModel


class Response(BaseModel):
    code: str
    explanation: str


class TestOllama(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = OllamaModel()
        system_message = "As a professional python developer"
        user_message = """
        please write a program to generate a fibonacci sequence.
        """
        response = model.get_response(system_message, user_message)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["OLLAMA_URL"] = ""
        model = OllamaModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["OLLAMA_URL"])

        os.environ["OLLAMA_URL"] = "xxx"
        model = OllamaModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
