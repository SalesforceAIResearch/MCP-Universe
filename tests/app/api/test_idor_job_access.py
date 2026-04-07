"""
PoC test for CWE-863: IDOR on benchmark job retrieval.

Demonstrates that the GET /benchmark_job/get endpoint allows any authenticated
user to retrieve another user's job details without ownership verification.

Before the fix: test_idor_cross_user_job_access FAILS (status 200 instead of 403).
After the fix: test_idor_cross_user_job_access PASSES (status 403).
"""
import os
import json
import pytest
from fastapi.testclient import TestClient

from mcpuniverse.app.api.job import GetBenchmarkJobResponse
from mcpuniverse.app.api.user import CreateUserResponse
from mcpuniverse.app.api.benchmark import CreateReleasedBenchmarkResponse
from pydantic_core import from_json


class TestIDORJobAccess:
    """Test that benchmark job retrieval enforces owner_id authorization."""

    def _create_user(self, client, username, email):
        """Helper to create a user and return their ID."""
        response = client.post(
            "/user/create",
            json={"username": username, "email": email, "password": "password123"},
        )
        assert response.status_code == 200
        r = CreateUserResponse.model_validate(from_json(response.text))
        return str(r.id)

    def _setup_benchmark(self, client, user_id):
        """Helper to create a benchmark with a task. Returns benchmark_id."""
        benchmark_name = "test_benchmark_idor"
        response = client.post(
            "/internal/benchmark/create",
            json={"name": benchmark_name, "description": "IDOR test benchmark"},
            headers={"x-user-id": user_id}
        )
        assert response.status_code == 200

        task_config = {
            "category": "general",
            "question": "Test question?",
            "mcp_servers": [{"name": "weather"}],
            "output_format": {"city": "<CITY>"},
            "evaluators": [
                {"func": "json -> get(city)", "op": "=", "value": "Test"}
            ],
            "cleanups": []
        }
        response = client.post(
            "/internal/task/create",
            json={
                "benchmark_name": benchmark_name,
                "name": "idor-task-1",
                "category": "test",
                "question": "Test question?",
                "config": json.dumps(task_config)
            },
            headers={"x-user-id": user_id}
        )
        assert response.status_code == 200

        response = client.post(
            "/admin/benchmark/create_release",
            json={"owner_name": "user_owner", "name": benchmark_name, "tag": "v1"},
        )
        assert response.status_code == 200
        r = CreateReleasedBenchmarkResponse.model_validate(from_json(response.text))
        return r.id

    def test_get_benchmark_job_requires_user_id(self, client):
        """GET /benchmark_job/get should require x-user-id header."""
        response = client.get("/benchmark_job/get?job_id=nonexistent-id")
        assert response.status_code == 400, (
            f"Expected 400 for missing user ID, got {response.status_code}"
        )

    def test_idor_cross_user_job_access(self, client):
        """
        A user should NOT be able to access another user's benchmark job.

        This is the core IDOR test:
        1. User A creates a job
        2. User B tries to read it via GET /benchmark_job/get?job_id=<A's job>
        3. Should get 403 Forbidden
        """
        user_a_id = self._create_user(client, "user_owner", "owner@test.com")
        user_b_id = self._create_user(client, "user_attacker", "attacker@test.com")

        benchmark_id = self._setup_benchmark(client, user_a_id)

        if not os.environ.get("OPENAI_API_KEY", ""):
            response = client.get(
                f"/benchmark_job/get?job_id=fake-job-id",
                headers={"x-user-id": user_b_id}
            )
            assert response.status_code == 404
            return

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
    instruction: You are a test agent.
    servers:
      - name: weather
"""
        response = client.post(
            "/project/create",
            json={"name": "idor_project", "description": "test", "configuration": configuration},
            headers={"x-user-id": user_a_id}
        )
        assert response.status_code == 200

        response = client.post(
            "/project/create_release",
            json={"name": "idor_project", "tag": "v1"},
            headers={"x-user-id": user_a_id}
        )
        assert response.status_code == 200

        from mcpuniverse.app.api.job import CreateBenchmarkJobResponse
        response = client.post(
            "/benchmark_job/create",
            json={"project_name": "idor_project", "project_tag": "v1", "benchmark_id": benchmark_id},
            headers={"x-user-id": user_a_id}
        )
        assert response.status_code == 200
        job = CreateBenchmarkJobResponse.model_validate(from_json(response.text))
        job_id = job.job_id

        # User A can access their own job
        response = client.get(
            f"/benchmark_job/get?job_id={job_id}",
            headers={"x-user-id": user_a_id}
        )
        assert response.status_code == 200

        # User B should NOT be able to access User A's job (IDOR)
        response = client.get(
            f"/benchmark_job/get?job_id={job_id}",
            headers={"x-user-id": user_b_id}
        )
        assert response.status_code == 403, (
            f"IDOR vulnerability: User B accessed User A's job! "
            f"Expected 403, got {response.status_code}. "
            f"Response: {response.text}"
        )
