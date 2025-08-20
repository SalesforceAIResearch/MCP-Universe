import os
import unittest
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.workflows.builder import WorkflowBuilder
from mcpuniverse.common.context import Context


class TestWorkflowBuilder(unittest.TestCase):

    def test_get_constructor_signature(self):
        builder = WorkflowBuilder(mcp_manager=MCPManager(), config={})
        params = builder._get_constructor_signature(builder._workflow_classes["router"])
        self.assertTrue(params["llm"]["is_llm_or_executor"])
        self.assertTrue(params["agents"]["is_llm_or_executor"])
        self.assertFalse(params["top_k"]["is_llm_or_executor"])

    def test_build_dependency_graph(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/yaml_config.yaml")
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=config_file)
        graph = workflow._build_dependency_graph()
        self.assertListEqual(graph["agent-1"], ["llm-1"])
        self.assertListEqual(graph["agent-2"], ["llm-1"])
        self.assertListEqual(graph["agent-3"], ["llm-1"])
        self.assertListEqual(sorted(graph["workflow-1"]), ["agent-1", "agent-2", "agent-3"])

    def test_build_workflow(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/yaml_config.yaml")
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=config_file)
        workflow.build()
        description = workflow.get_component("main").get_description()
        self.assertTrue("Main agent" in description)

    def test_dump_config(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/yaml_config.yaml")
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=config_file)
        workflow.build(project_id="test")
        configs = workflow.dump_config()
        name2id = {}
        for c in configs:
            if c["kind"] == "agent":
                name2id[c["spec"]["name"]] = f'test:agent:{c["spec"]["name"]}'
            elif c["kind"] == "llm":
                name2id[c["spec"]["name"]] = f'test:llm:{c["spec"]["name"]}'
            elif c["kind"] == "workflow":
                name2id[c["spec"]["name"]] = f'test:workflow:{c["spec"]["name"]}'

        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=configs)
        workflow.build(project_id="test")
        for name in name2id.keys():
            self.assertEqual(workflow.get_component(name).id, name2id[name])

    def test_list_undefined_env_vars(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/yaml_config.yaml")
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=config_file)
        workflow.build(project_id="test")

        os.environ["OPENAI_API_KEY"] = ""
        r = workflow.list_undefined_env_vars()
        self.assertListEqual(r, ["OPENAI_API_KEY"])
        context = Context(env={"OPENAI_API_KEY": "xxx"})
        workflow.set_context(context)
        r = workflow.list_undefined_env_vars()
        self.assertListEqual(r, [])

    def test_claude_code_config(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(folder, "../data/config/claude_code.yaml")
        workflow = WorkflowBuilder(mcp_manager=MCPManager(), config=config_file)
        workflow.build(project_id="test")
        agent = workflow.get_component(name="agent-1")
        self.assertEqual(type(agent).__name__, "ClaudeCodeAgent")


if __name__ == "__main__":
    unittest.main()
