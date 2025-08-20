"""
The Page for configuring agents and MCP servers.
"""
import json
import yaml
import gradio as gr
from .utils import CSS
from ..manager import dashboard_manager


def get_agent_names():
    """Return all agent names."""
    agent_configs = dashboard_manager.get_agent_configs()
    return ["New"] + sorted(list(agent_configs.keys()))


def get_mcp_server_names():
    """Return all MCP server names."""
    mcp_configs = dashboard_manager.get_mcp_configs()
    return ["New"] + sorted(list(mcp_configs.keys()))


def build_app():
    """Build page."""

    def on_agent_dropdown(name):
        _agent_name = ""
        config = []
        if name != "New":
            _agent_name = name
            agent_configs = dashboard_manager.get_agent_configs()
            config = agent_configs[name]
        return _agent_name, yaml.dump_all(config, indent=4), gr.update(choices=get_agent_names())

    def click_agent_btn(name, config):
        try:
            dashboard_manager.upsert_agent(name, config)
            gr.Info("Successfully saved agent config", duration=3)
        except Exception as e:
            raise gr.Error(str(e), duration=3)

    def on_mcp_dropdown(name):
        _mcp_server_name = ""
        config = {}
        if name != "New":
            _mcp_server_name = name
            mcp_configs = dashboard_manager.get_mcp_configs()
            config = mcp_configs[name]
        return _mcp_server_name, json.dumps(config, indent=2), config, gr.update(choices=get_mcp_server_names())

    def click_mcp_btn(name, config):
        try:
            dashboard_manager.upsert_mcp_server(name, config)
            gr.Info("Successfully saved MCP config", duration=3)
        except Exception as e:
            raise gr.Error(str(e), duration=5)

    with gr.Blocks(title="Agent and MCP", css=CSS, theme=gr.themes.Soft()) as app:
        with gr.Row(equal_height=True):
            with gr.Column():
                agent_dropdown = gr.Dropdown(
                    label="Agent", choices=get_agent_names(), value="New", interactive=True)
                agent_name = gr.Textbox(lines=1, max_lines=1, label="Name", interactive=True)
                agent_config = gr.Textbox(lines=25, max_lines=25, label="Configuration", interactive=True)
                agent_btn = gr.Button("Create or Update")

            with gr.Column():
                mcp_dropdown = gr.Dropdown(
                    label="MCP Servers", choices=get_mcp_server_names(), value="New", interactive=True)
                mcp_name = gr.Textbox(lines=1, max_lines=1, label="Name", interactive=True)
                mcp_config_json = gr.JSON(height=262, label="Configuration")
                mcp_config = gr.Textbox(lines=10, max_lines=10, label="Edit", interactive=True)
                mcp_btn = gr.Button("Create or Update")

        agent_dropdown.change(
            on_agent_dropdown,
            inputs=[agent_dropdown],
            outputs=[agent_name, agent_config, agent_dropdown]
        )
        mcp_dropdown.change(
            on_mcp_dropdown,
            inputs=[mcp_dropdown],
            outputs=[mcp_name, mcp_config, mcp_config_json, mcp_dropdown]
        )
        agent_btn.click(click_agent_btn, [agent_name, agent_config])
        mcp_btn.click(click_mcp_btn, [mcp_name, mcp_config])
        return app
