import unittest
import pytest
from mcpuniverse.llm.openai import OpenAIModel


class TestOpenAI(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test(self):
        model = OpenAIModel()
        system_message = "As a professional python developer"
        user_message = "please write a program to generate a fibonacci sequence"
        response = await model.get_response_async(system_message, user_message)
        print(response)


if __name__ == "__main__":
    unittest.main()
