import unittest

from mcpuniverse.llm.azure import AzureOpenAIModel
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.workflows.builder import WorkflowBuilder


class TestWorkflowBuilderAzure(unittest.TestCase):

    def test_builds_azure_llm_from_config(self):
        configs = [{
            "kind": "llm",
            "spec": {
                "name": "llm-1",
                "type": "azure",
                "config": {"model_name": "gpt-5.4-mini"},
            },
        }]
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=configs)
        workflow.build(project_id="test")

        llm = workflow.get_component("llm-1")
        self.assertIsInstance(llm, AzureOpenAIModel)
        self.assertEqual(llm.config.model_name, "gpt-5.4-mini")
        self.assertEqual(llm.id, "test:llm:llm-1")


if __name__ == "__main__":
    unittest.main()
