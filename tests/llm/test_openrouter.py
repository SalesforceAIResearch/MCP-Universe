import os
import unittest
import pytest
from mcpuniverse.llm.openrouter import OpenRouterModel


class TestOpenRouter(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_names = [
            "Qwen3Coder_OR",
            "GrokCoderFast1_OR",
            "GPTOSS120B_OR",
            "DeepSeekV3_1_OR",
            "GLM4_5_OR",
            "GLM4_5_AIR_OR",
            "KimiK2_OR"
        ]

    @pytest.mark.skip
    def test(self):
        model = OpenRouterModel()
        model.config.model_name = self.model_names[1]
        system_message = "As a professional python developer"
        user_message = "please write a very short program to generate a fibonacci sequence"
        response = model.get_response(system_message, user_message)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["OPENROUTER_API_KEY"] = ""
        model = OpenRouterModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["OPENROUTER_API_KEY"])

        os.environ["OPENROUTER_API_KEY"] = "xxx"
        model = OpenRouterModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])


if __name__ == "__main__":
    unittest.main()
