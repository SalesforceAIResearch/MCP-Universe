"""One-off Azure OpenAI smoke test. Loads .env via dotenv; does not print secrets."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

deployment = (
    os.getenv("AZURE_SMOKE_MODEL") or os.getenv("AZURE_DEPLOYMENT_NAME") or "gpt-5"
)

missing = [k for k in ("AZURE_API_KEY", "AZURE_API_BASE") if not os.getenv(k)]
if missing:
    print("FAIL: missing env vars:", ", ".join(missing))
    sys.exit(1)

print("Env OK (key and base present)", flush=True)
print("Deployment:", deployment, flush=True)
print(
    "API version:",
    os.getenv("AZURE_API_VERSION", "2024-12-01-preview (default)"),
    flush=True,
)

from mcpuniverse.llm.manager import ModelManager

model = ModelManager().build_model("azure", config={"model_name": deployment})
undefined = model.list_undefined_env_vars()
if undefined:
    print("FAIL: provider reports undefined:", undefined)
    sys.exit(1)

print("Calling Azure OpenAI...", flush=True)
response = model.get_response(
    "You are a helpful assistant.",
    "Reply with exactly one word: hello",
)
if not response:
    print("FAIL: empty response from provider")
    sys.exit(1)

print("SUCCESS", flush=True)
print("Response:", str(response)[:500], flush=True)
