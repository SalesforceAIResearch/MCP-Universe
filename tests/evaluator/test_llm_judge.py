import unittest
from unittest.mock import MagicMock, patch

from mcpuniverse.common.context import Context
from mcpuniverse.evaluator.llm_judge import (
    DEFAULT_OPENAI_JUDGE_MODEL,
    build_judge_model,
    call_judge_text,
    resolve_judge_config,
)
from mcpuniverse.llm.azure import AzureOpenAIModel
from mcpuniverse.llm.openai import OpenAIModel


def _judge_context(**overrides) -> Context:
    """Build a Context isolated from the host .env for judge config tests."""
    env = {
        "EVAL_LLM_PROVIDER": "",
        "EVAL_LLM_MODEL_NAME": "",
        "AZURE_JUDGE_DEPLOYMENT": "",
        "AZURE_API_KEY": "",
        "AZURE_API_BASE": "",
        "OPENAI_API_KEY": "",
    }
    env.update(overrides)
    return Context(env=env)


class TestResolveJudgeConfig(unittest.TestCase):

    def test_defaults_to_openai_when_no_azure_credentials(self):
        context = _judge_context(OPENAI_API_KEY="sk-test")
        config = resolve_judge_config(context)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model_name, "gpt-4.1")

    def test_defaults_to_azure_when_azure_credentials_present(self):
        context = _judge_context(
            AZURE_API_KEY="azure-key",
            AZURE_API_BASE="https://example.openai.azure.com",
            EVAL_LLM_MODEL_NAME="gpt-5.4-mini",
        )
        config = resolve_judge_config(context)
        self.assertEqual(config.provider, "azure")
        self.assertEqual(config.model_name, "gpt-5.4-mini")

    def test_explicit_provider_overrides_inference(self):
        context = _judge_context(
            AZURE_API_KEY="azure-key",
            AZURE_API_BASE="https://example.openai.azure.com",
            EVAL_LLM_PROVIDER="openai",
            EVAL_LLM_MODEL_NAME="gpt-4o-mini",
            OPENAI_API_KEY="sk-test",
        )
        config = resolve_judge_config(context)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model_name, "gpt-4o-mini")

    def test_azure_judge_deployment_fallback(self):
        context = _judge_context(
            AZURE_API_KEY="azure-key",
            AZURE_API_BASE="https://example.openai.azure.com",
            AZURE_JUDGE_DEPLOYMENT="judge-dep",
        )
        config = resolve_judge_config(context)
        self.assertEqual(config.provider, "azure")
        self.assertEqual(config.model_name, "judge-dep")


class TestBuildJudgeModel(unittest.TestCase):

    def test_builds_azure_model(self):
        context = _judge_context(
            AZURE_API_KEY="azure-key",
            AZURE_API_BASE="https://example.openai.azure.com",
            EVAL_LLM_MODEL_NAME="gpt-5.4-mini",
        )
        model = build_judge_model(context)
        self.assertIsInstance(model, AzureOpenAIModel)
        self.assertEqual(model.config.model_name, "gpt-5.4-mini")

    def test_builds_openai_model(self):
        context = _judge_context(
            EVAL_LLM_PROVIDER="openai",
            OPENAI_API_KEY="sk-test",
        )
        model = build_judge_model(context)
        self.assertIsInstance(model, OpenAIModel)


class TestCallJudgeText(unittest.TestCase):

    @patch("mcpuniverse.evaluator.llm_judge.build_judge_model")
    def test_uses_model_manager_path_not_raw_openai_client(self, mock_build):
        mock_model = MagicMock()
        mock_model.generate.return_value = "correct: yes"
        mock_build.return_value = mock_model

        context = _judge_context(
            AZURE_API_KEY="k",
            AZURE_API_BASE="https://example.openai.azure.com",
            EVAL_LLM_MODEL_NAME="dep",
        )
        result = call_judge_text("judge this", context=context)

        self.assertEqual(result, "correct: yes")
        mock_build.assert_called_once_with(context, DEFAULT_OPENAI_JUDGE_MODEL)
        mock_model.generate.assert_called_once()
        call_args = mock_model.generate.call_args
        messages = call_args.kwargs.get("messages", call_args.args[0])
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "judge this")


if __name__ == "__main__":
    unittest.main()
