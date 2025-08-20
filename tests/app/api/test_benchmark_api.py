from pydantic_core import from_json
from mcpuniverse.app.api.benchmark import (
    CreateBenchmarkResponse,
    GetBenchmarkResponse,
    CreateReleasedBenchmarkResponse,
    GetReleasedBenchmarkResponse,
    ListReleasedBenchmarkResponse
)
from mcpuniverse.app.api.task import GetReleasedTaskResponse
from mcpuniverse.app.api.user import CreateUserResponse


class TestBenchmarkAPI:

    def test_create_benchmark(self, client):
        name = "test_benchmark"
        description = "A test benchmark"

        response = client.post(
            "/internal/benchmark/create",
            json={"name": name, "description": description}
        )
        assert response.status_code == 400

        response = client.post(
            "/internal/benchmark/create",
            json={"name": name, "description": description},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateBenchmarkResponse.model_validate(from_json(response.text))
        assert r.name == name

        response = client.post(
            "/internal/benchmark/create",
            json={"name": "", "description": description},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 400

        response = client.post(
            "/internal/benchmark/create",
            json={"description": description},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 400

    def test_get_benchmark(self, client):
        name = "test_benchmark"
        description = "A test benchmark"

        response = client.post(
            "/internal/benchmark/create",
            json={"name": name, "description": description},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateBenchmarkResponse.model_validate(from_json(response.text))
        assert r.name == name

        response = client.get(
            f"/internal/benchmark/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/internal/benchmark/get?name=xxx",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

    def test_update_benchmark(self, client):
        name = "test_benchmark"
        description = "A test benchmark"

        response = client.post(
            "/internal/benchmark/create",
            json={"name": name, "description": description},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            "/internal/benchmark/update",
            json={"name": name, "description": "test test"},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/internal/benchmark/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = GetBenchmarkResponse.model_validate(from_json(response.text))
        assert r.description == "test test"

        response = client.post(
            "/internal/benchmark/update",
            json={"name": name},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/internal/benchmark/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = GetBenchmarkResponse.model_validate(from_json(response.text))
        assert r.description == "test test"

        response = client.post(
            "/internal/benchmark/update",
            json={"name": "xxx"},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

    def test_create_released_benchmark(self, client):
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

        response = client.post(
            "/internal/task/create",
            json={
                "benchmark_name": benchmark_name,
                "name": "task-1",
                "category": "test",
                "question": "the first task",
                "config": "{}"
            },
            headers={"x-user-id": str(user_id)}
        )
        assert response.status_code == 200

        response = client.post(
            "/internal/task/create",
            json={
                "benchmark_name": benchmark_name,
                "name": "task-2",
                "category": "test",
                "question": "the second task",
                "config": "{}"
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

        response = client.get(
            f"/task/get_release?benchmark_id={benchmark_id}&name=task-1&tag=v1"
        )
        assert response.status_code == 200
        r = GetReleasedTaskResponse.model_validate(from_json(response.text))
        assert r.name == "task-1" and r.question == "the first task"

        response = client.get(
            f"/task/get_release?benchmark_id={benchmark_id}&name=task-2&tag=v1"
        )
        assert response.status_code == 200
        r = GetReleasedTaskResponse.model_validate(from_json(response.text))
        assert r.name == "task-2" and r.question == "the second task"

        response = client.get(
            f"/benchmark/get_release?owner_name=abc&name={benchmark_name}&tag=v1"
        )
        assert response.status_code == 200
        r = GetReleasedBenchmarkResponse.model_validate(from_json(response.text))
        assert r.id == benchmark_id and r.name == benchmark_name
        assert len(r.tasks) == 2
        assert "task-1" in r.tasks and "task-2" in r.tasks

        response = client.post(
            "/benchmark/list_release",
            json={"limit": 1, "offset": 0},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = ListReleasedBenchmarkResponse.model_validate(from_json(response.text))
        assert r.benchmarks[0] == (user_id, benchmark_name)
