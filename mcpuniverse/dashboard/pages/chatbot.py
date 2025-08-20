"""
The Page for interacting with agents.
"""
# pylint: disable=unused-variable
import asyncio
import json

import gradio as gr
from mcpuniverse.llm.utils import extract_json_output
from .utils import CSS
from ..manager import dashboard_manager


def get_agent_names():
    """Return all agent names."""
    agent_configs = dashboard_manager.get_agent_configs()
    return sorted(list(agent_configs.keys()))


def build_app():
    """Build page."""

    def on_load():
        agent_names = get_agent_names()
        value = agent_names[0] if agent_names else ""
        return gr.update(choices=agent_names, value=value)

    def chat(agent_name, user_msg, chat_history):
        async def _chat():
            return await dashboard_manager.chat(agent_name, user_msg)

        response = asyncio.run(_chat())
        chat_history.extend([
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": response}
        ])
        responses = dashboard_manager.get_chat_responses()
        components = sorted(list(responses.keys()))
        value = "" if not components else components[0]
        content = "" if not components else responses[components[0]]
        return (chat_history, gr.update(choices=components, value=value),
                content, dashboard_manager.get_traces())

    def on_component_dropdown(name):
        responses = dashboard_manager.get_chat_responses()
        if name not in responses:
            return ""
        output = responses[name]
        if isinstance(output, dict):
            return json.dumps(output, indent=2).replace("\\n", "\n")
        jsons = extract_json_output(output)
        if not jsons:
            return output
        return "\n\n".join(json.dumps(d, indent=2) for d in jsons)

    with gr.Blocks(title="Chatbot", css=CSS, theme=gr.themes.Soft()) as app:
        with gr.Row(equal_height=True):
            with gr.Column():
                agent_dropdown = gr.Dropdown(label="Agent")
                chatbot = gr.Chatbot(type="messages", height=500, label="Chat")
                with gr.Row(equal_height=True):
                    user_message = gr.Textbox(lines=3, max_lines=3, label="Input Message")
                with gr.Row(equal_height=True):
                    submit_btn = gr.Button("Submit")

            with gr.Column():
                component_dropdown = gr.Dropdown(label="Component", choices=[], value="", interactive=True)
                component_response = gr.Textbox(lines=10, max_lines=10, label="Component Response", interactive=False)
                with gr.Row(equal_height=True):
                    trace = gr.JSON(label="Trace", height=450)

        submit_btn.click(
            chat,
            inputs=[agent_dropdown, user_message, chatbot],
            outputs=[chatbot, component_dropdown, component_response, trace]
        )
        component_dropdown.change(
            on_component_dropdown,
            inputs=[component_dropdown],
            outputs=[component_response]
        )
        app.load(on_load, outputs=[agent_dropdown])
        return app
