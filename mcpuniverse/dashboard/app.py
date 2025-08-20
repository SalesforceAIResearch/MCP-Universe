"""
The dashboard APP.
"""
import os
import gradio as gr
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from mcpuniverse.dashboard.pages.agent import build_app as build_agent_config
from mcpuniverse.dashboard.pages.chatbot import build_app as build_chatbot
from mcpuniverse.dashboard.pages.benchmark import build_app as build_benchmark

app = FastAPI()

gradio_apps = [
    {
        "title": "Setup Agent and MCP",
        "app": build_agent_config(),
        "path": "agent"
    },
    {
        "title": "Chat with Agent",
        "app": build_chatbot(),
        "path": "chatbot"
    },
    {
        "title": "Run Benchmark",
        "app": build_benchmark(),
        "path": "benchmark"
    },
]
for gradio_app in gradio_apps:
    app = gr.mount_gradio_app(app, gradio_app["app"], path="/gradio/" + gradio_app["path"])

folder = os.path.dirname(os.path.realpath(__file__))
templates = Jinja2Templates(directory=os.path.join(folder, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(folder, "static")), name="static")


@app.get("/")
@app.get("/app/{path_name:path}")
def index(request: Request, path_name: str = ""):
    """Index page."""
    if not path_name:
        return RedirectResponse(url="/app/" + gradio_apps[0]["path"])

    return templates.TemplateResponse("index.html", {
        "request": request,
        "gradio_apps": gradio_apps,
        "current_path": path_name,
    })
