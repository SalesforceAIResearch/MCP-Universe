from pydantic_core import from_json
from mcpuniverse.app.api.project import (
    CreateProjectResponse,
    GetProjectResponse,
    CreateReleasedProjectResponse,
    ListProjectResponse
)


class TestProjectAPI:

    def test_create_project(self, client):
        name = "test_project"
        description = "A test project"
        configuration = "{}"

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration}
        )
        assert response.status_code == 400

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateProjectResponse.model_validate(from_json(response.text))
        assert r.name == name

        response = client.post(
            "/project/create",
            json={"name": "", "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 400

        response = client.post(
            "/project/create",
            json={"description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 400

    def test_get_project(self, client):
        name = "test_project"
        description = "A test project"
        configuration = "{}"

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateProjectResponse.model_validate(from_json(response.text))
        assert r.name == name

        response = client.get(
            f"/project/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/project/get?name=xxx",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

    def test_delete_project(self, client):
        name = "test_project"
        description = "A test project"
        configuration = "{}"

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            f"/project/delete?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            f"/project/delete?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

    def test_update_project(self, client):
        name = "test_project"
        description = "A test project"
        configuration = "{}"

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            "/project/update",
            json={"name": name, "description": "test test", "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/project/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = GetProjectResponse.model_validate(from_json(response.text))
        assert r.description == "test test"

        response = client.post(
            "/project/update",
            json={"name": name, "configuration": "test"},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/project/get?name={name}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = GetProjectResponse.model_validate(from_json(response.text))
        assert r.description == "test test" and r.configuration == "test"

        response = client.post(
            "/project/update",
            json={"name": "xxx", "configuration": "test"},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

        response = client.post(
            "/project/list",
            json={"limit": 1, "offset": 0},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = ListProjectResponse.model_validate(from_json(response.text))
        assert r.projects[0] == name

    def test_release_project(self, client):
        name = "test_project"
        tag = "v1"
        description = "A test project"
        configuration = "{}"

        response = client.post(
            "/project/create",
            json={"name": name, "description": description, "configuration": configuration},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.post(
            "/project/create_release",
            json={"name": name, "tag": tag},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = CreateReleasedProjectResponse.model_validate(from_json(response.text))
        assert r.name == name and r.tag == tag

        response = client.get(
            f"/project/get_release?name={name}&tag={tag}",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200

        response = client.get(
            f"/project/get_release?name={name}&tag=xxx",
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 404

        response = client.post(
            "/project/list_release",
            json={"limit": 1, "offset": 0},
            headers={"x-user-id": "12345"}
        )
        assert response.status_code == 200
        r = ListProjectResponse.model_validate(from_json(response.text))
        assert r.projects[0] == name
