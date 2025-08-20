import json
import os
from pydantic_core import from_json
from mcpuniverse.app.api.benchmark import CreateReleasedBenchmarkResponse
from mcpuniverse.app.api.user import CreateUserResponse
from mcpuniverse.app.api.job import CreateBenchmarkJobResponse, GetBenchmarkJobResponse


class TestBenchmarkJobAPI:

    def test_create_benchmark_job(self, client):
        benchmark_name = "test_benchmark"
        description = "A test benchmark"

        response = client.post(
            "/user/create",
            json={"username": "abc", "email": "abc@gmail.com", "password": "123"},
        )
        assert response.status_code == 200
        r = CreateUserResponse.model_validate(from_json(response.text))
        user_id = r.id

        response = client.post(
            "/internal/benchmark/create",
            json={"name": benchmark_name, "description": description},
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200

        task_question = "What's the weather in San Francisco now?"
        task_config = {
            "category": "general",
            "question": "What's the weather in San Francisco now?",
            "mcp_servers": [
                {
                    "name": "weather"
                }
            ],
            "output_format": {
                "city": "<CITY>",
                "weather": "<Weather forecast results>"
            },
            "evaluators": [
                {
                    "func": "json -> get(city)",
                    "op": "=",
                    "value": "San Francisco"
                }
            ],
            "cleanups": [
                {
                    "server": "weather",
                    "tool": "get_forecast",
                    "cleanup_func": "get_forecast",
                    "cleanup_args": {"latitude": "$latitude", "longitude": "$longitude"}
                }
            ]
        }
        response = client.post(
            "/internal/task/create",
            json={
                "benchmark_name": benchmark_name,
                "name": "task-1",
                "category": "test",
                "question": task_question,
                "config": json.dumps(task_config)
            },
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200

        response = client.post(
            "/admin/benchmark/create_release",
            json={"owner_name": "abc", "name": benchmark_name, "tag": "v1"},
        )
        assert response.status_code == 200
        r = CreateReleasedBenchmarkResponse.model_validate(from_json(response.text))
        assert r.name == benchmark_name and r.tag == "v1"
        benchmark_id = r.id

        name = "test_project"
        tag = "v1"
        description = "A test project"
        configuration = """
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  is_main: true
  config:
    llm: llm-1
    instruction: You are an agent for weather forecasting.
    servers:
      - name: weather
        """
        if not os.environ.get("OPENAI_API_KEY", ""):
            return

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200

        response = client.post(
            "/project/create_release",
            json={"name": name, "tag": tag},
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200

        response = client.post(
            "/benchmark_job/create",
            json={"project_name": "test_project", "project_tag": "v1", "benchmark_id": benchmark_id},
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200
        r = CreateBenchmarkJobResponse.model_validate(from_json(response.text))
        job_id = r.job_id

        response = client.get(
            f"/benchmark_job/get?job_id={job_id}",
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200
        r = GetBenchmarkJobResponse.model_validate(from_json(response.text))
        assert r.job_id == job_id
        assert r.project_name == "test_project" and r.project_tag == "v1"
        assert r.benchmark_id == benchmark_id
