"""
The Page for configuring benchmarks.
"""
# pylint: disable=unused-variable
import gradio as gr
from .utils import CSS
from ..manager import dashboard_manager


def get_agent_names():
    """Return all agent names."""
    agent_configs = dashboard_manager.get_agent_configs()
    return sorted(list(agent_configs.keys()))


def get_benchmark_names():
    """Return all benchmark names."""
    configs = dashboard_manager.get_benchmark_configs()
    return sorted(list(configs.keys()))


def get_init_benchmark_values(benchmark_name):
    """Return initial values for gradio components."""
    configs = dashboard_manager.get_benchmark_configs()
    config = configs[benchmark_name]
    tasks = ["all"] + config["tasks"]
    return config, tasks, "all", {}


def build_app():
    """Build page."""
    benchmark_names = get_benchmark_names()
    agent_names = get_agent_names()

    def on_load():
        config, tasks, first_task, first_task_config = get_init_benchmark_values(benchmark_names[0])
        return config, gr.update(choices=tasks, value=first_task), first_task_config

    def on_benchmark_dropdown(name):
        config, tasks, first_task, first_task_config = get_init_benchmark_values(name)
        return config, gr.update(choices=tasks, value=first_task), first_task_config

    def on_task_dropdown(name):
        if name.lower() == "all":
            return {}
        return dashboard_manager.get_benchmark_task_config(name)

    def click_run_btn(benchmark_name, task_name, agent_name):
        gr.Info("Benchmark started successfully. Please check the running status.", duration=3)
        dashboard_manager.run_benchmark(
            benchmark_name=benchmark_name,
            task_name=task_name,
            agent_name=agent_name
        )

    def click_refresh_btn(benchmark_name, task_name, agent_name):
        state = dashboard_manager.get_benchmark_state(
            benchmark_name=benchmark_name,
            task_name=task_name,
            agent_name=agent_name
        )
        return state.benchmark_status, state.benchmark_results, "\n\n".join(state.benchmark_logs)


    with gr.Blocks(title="Benchmark", css=CSS, theme=gr.themes.Soft()) as app:
        with gr.Row(equal_height=True):
            with gr.Column():
                benchmark_dropdown = gr.Dropdown(
                    label="Benchmark",
                    choices=benchmark_names,
                    value=benchmark_names[0],
                    interactive=True
                )
                benchmark_config = gr.JSON(label="Config", height=200)
                with gr.Row(equal_height=False):
                    with gr.Column():
                        task_dropdown = gr.Dropdown(label="Task", interactive=True)
                        task_config = gr.JSON(label="Config", height=400)

            with gr.Column():
                agent_dropdown = gr.Dropdown(
                    label="Agent",
                    choices=agent_names,
                    value=None if not agent_names else agent_names[0],
                    interactive=True
                )
                benchmark_status = gr.Textbox(lines=1, max_lines=1, label="Status")
                benchmark_logs = gr.Textbox(lines=10, max_lines=10, label="Log", interactive=False)
                benchmark_output = gr.JSON(label="Benchmark Output", height=300)
                with gr.Row(equal_height=True):
                    run_btn = gr.Button("Run")

        benchmark_dropdown.change(
            on_benchmark_dropdown,
            inputs=[benchmark_dropdown],
            outputs=[benchmark_config, task_dropdown, task_config]
        )
        task_dropdown.change(
            on_task_dropdown,
            inputs=[task_dropdown],
            outputs=[task_config]
        )
        run_btn.click(
            click_run_btn,
            inputs=[benchmark_dropdown, task_dropdown, agent_dropdown],
            concurrency_limit=1
        )
        gr.Timer(value=2.0).tick(
            click_refresh_btn,
            inputs=[benchmark_dropdown, task_dropdown, agent_dropdown],
            outputs=[benchmark_status, benchmark_output, benchmark_logs]
        )
        app.load(on_load, outputs=[benchmark_config, task_dropdown, task_config])
        return app
