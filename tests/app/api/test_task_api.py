from pydantic_core import from_json
from mcpuniverse.app.api.task import CreateTaskResponse, GetTaskResponse


class TestTaskAPI:

    def test_task(self, client):
        benchmark_name = "test_benchmark"
        name = "test_task"
        category = "test"
        question = "How to test"
        config = "{}"

        response = client.post(
            "/internal/benchmark/create",
            json={"name": benchmark_name, "description": "A test benchmark"},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            "/internal/task/create",
            json={
                "benchmark_name": benchmark_name,
                "name": name,
                "category": category,
                "question": question,
                "config": config
            },
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateTaskResponse.model_validate(from_json(response.text))
        assert r.name == name and r.benchmark_name == benchmark_name

        response = client.get(
            f"/internal/task/get?benchmark_name={benchmark_name}&name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = GetTaskResponse.model_validate(from_json(response.text))
        assert r.name == name and r.benchmark_name == benchmark_name
        assert r.category == category and r.question == question

        response = client.get(
            f"/internal/task/get?benchmark_name=xxx&name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

        response = client.post(
            "/internal/task/update",
            json={
                "benchmark_name": benchmark_name,
                "name": name,
                "question": "A new question"
            },
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/internal/task/get?benchmark_name={benchmark_name}&name={name}",
            headers={"x-user-id": "12345"}
        )
        r = GetTaskResponse.model_validate(from_json(response.text))
        assert r.name == name and r.benchmark_name == benchmark_name
        assert r.category == category and r.question == "A new question"
        assert r.is_public == True

        response = client.post(
            "/internal/task/update",
            json={
                "benchmark_name": benchmark_name,
                "name": name,
                "is_public": "false"
            },
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/internal/task/get?benchmark_name={benchmark_name}&name={name}",
            headers={"x-user-id": "12345"}
        )
        r = GetTaskResponse.model_validate(from_json(response.text))
        assert r.is_public == False

        response = client.post(
            f"/internal/task/delete?benchmark_name={benchmark_name}&name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
