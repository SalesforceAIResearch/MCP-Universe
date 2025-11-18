import os
import unittest
import pytest
from pydantic import BaseModel
from mcpuniverse.llm.vllm_gptoss import VLLMLocalModel
from mcpuniverse.common.context import Context


class Response(BaseModel):
    code: str
    explanation: str


class TestVLLMLocal(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = VLLMLocalModel()
        system_message = "As a professional python developer"
        user_message = "please write a program to generate a fibonacci sequence"
        response = model.get_response(system_message, user_message)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["VLLM_API_KEY"] = ""
        os.environ["VLLM_BASE_URL"] = ""
        model = VLLMLocalModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["VLLM_API_KEY", "VLLM_BASE_URL"])

        context = Context(env={"VLLM_API_KEY": "xxx", "VLLM_BASE_URL": "http://localhost:2024"})
        model = VLLMLocalModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])

    def test_config_defaults(self):
        model = VLLMLocalModel()
        self.assertEqual(model.config.model_name, "gpt-oss-120b")
        self.assertEqual(model.config.temperature, 1.0)
        self.assertEqual(model.config.max_completion_tokens, 20000)
        self.assertEqual(model.config.seed, 12345)


if __name__ == "__main__":
    unittest.main()

