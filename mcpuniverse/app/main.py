"""
The entrypoint of the server.
"""
import uvicorn
from mcpuniverse.app.server import init_app

app = init_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=1)
