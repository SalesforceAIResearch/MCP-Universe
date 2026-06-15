import os
import unittest
from unittest.mock import MagicMock, patch

from mcpuniverse.common.context import Context
from mcpuniverse.llm.azure import AzureOpenAIModel, AzureOpenAIConfig, DEFAULT_AZURE_API_VERSION
from mcpuniverse.llm.manager import ModelManager


class TestAzureOpenAI(unittest.TestCase):

    def test_build_model_via_manager(self):
        manager = ModelManager()
        model = manager.build_model("azure", config={"model_name": "gpt-5.4-mini"})
        self.assertIsInstance(model, AzureOpenAIModel)
        self.assertEqual(model.config.model_name, "gpt-5.4-mini")

    def test_list_undefined_env_vars(self):
        os.environ["AZURE_API_KEY"] = ""
        os.environ["AZURE_API_BASE"] = ""
        model = AzureOpenAIModel()
        self.assertListEqual(model.list_undefined_env_vars(), ["AZURE_API_KEY", "AZURE_API_BASE"])

        context = Context(env={
            "AZURE_API_KEY": "test-key",
            "AZURE_API_BASE": "https://example.openai.azure.com/",
        })
        model = AzureOpenAIModel()
        model.set_context(context)
        self.assertListEqual(model.list_undefined_env_vars(), [])

    def test_api_version_defaults_when_unset(self):
        env_backup = os.environ.get("AZURE_API_VERSION")
        if "AZURE_API_VERSION" in os.environ:
            del os.environ["AZURE_API_VERSION"]
        try:
            config = AzureOpenAIConfig()
            self.assertEqual(config.api_version, DEFAULT_AZURE_API_VERSION)
        finally:
            if env_backup is not None:
                os.environ["AZURE_API_VERSION"] = env_backup

    def test_normalizes_trailing_slash_on_endpoint(self):
        model = AzureOpenAIModel(config={
            "azure_endpoint": "https://example.openai.azure.com/",
        })
        self.assertEqual(model.config.azure_endpoint, "https://example.openai.azure.com")

        context = Context(env={"AZURE_API_BASE": "https://other.openai.azure.com/"})
        model.set_context(context)
        self.assertEqual(model.config.azure_endpoint, "https://other.openai.azure.com")

    @patch("mcpuniverse.llm.azure.AzureOpenAI")
    def test_generate_uses_deployment_name_unchanged(self, mock_azure_openai):
        """Deployment names must not be rewritten (e.g. gpt-5-high stays as-is)."""
        deployment = "gpt-5-high"
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))]
        )

        model = AzureOpenAIModel(config={
            "model_name": deployment,
            "api_key": "key",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_version": "2024-12-01-preview",
        })
        result = model._generate([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        self.assertEqual(model.config.model_name, deployment)
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], deployment)

    @patch("mcpuniverse.llm.azure.AzureOpenAI")
    def test_generate_does_not_pass_retry_options_to_api(self, mock_azure_openai):
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))]
        )

        model = AzureOpenAIModel(config={
            "model_name": "dep",
            "api_key": "key",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_version": "2024-12-01-preview",
        })
        model._generate(
            [{"role": "user", "content": "hi"}],
            max_retries=2,
            base_delay=1.0,
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("max_retries", call_kwargs)
        self.assertNotIn("base_delay", call_kwargs)

    @patch("mcpuniverse.llm.azure.time.sleep")
    @patch("mcpuniverse.llm.azure.AzureOpenAI")
    def test_generate_does_not_retry_on_not_found(self, mock_azure_openai, mock_sleep):
        from openai import NotFoundError

        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = NotFoundError(
            "404",
            response=MagicMock(status_code=404),
            body={"error": {"message": "Resource not found"}},
        )

        model = AzureOpenAIModel(config={
            "model_name": "wrong-deployment",
            "api_key": "key",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_version": "2024-12-01-preview",
        })
        result = model._generate([{"role": "user", "content": "hi"}], max_retries=5)

        self.assertIsNone(result)
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
