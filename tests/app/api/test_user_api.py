from pydantic_core import from_json
from mcpuniverse.app.api.user import CreateUserResponse


class TestUserAPI:

    def test_create_user(self, client):
        username = "abc"
        email = "test@example.com"
        password = "123"

        response = client.post(
            "/user/create",
            json={"username": username, "email": email, "password": password},
        )
        assert response.status_code == 200
        r = CreateUserResponse.model_validate(from_json(response.text))
        assert r.email == email

        response = client.post(
            "/user/create",
            json={"username": username, "email": "", "password": password},
        )
        assert response.status_code == 400

        response = client.post(
            "/user/create",
            json={"username": username, "email": email, "password": ""},
        )
        assert response.status_code == 400

        response = client.post(
            "/user/create",
            json={"username": username, "email": "test", "password": password},
        )
        assert response.status_code == 400

        response = client.post(
            "/user/create",
            json={"username": username, "email": email},
        )
        assert response.status_code == 400

    def test_login_user(self, client):
        username = "abc"
        email = "test@example.com"
        password = "123"

        response = client.post(
            "/user/create",
            json={"username": username, "email": email, "password": password},
        )
        assert response.status_code == 200
        r = CreateUserResponse.model_validate(from_json(response.text))
        assert r.email == email

        response = client.post(
            "/user/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200

        response = client.post(
            "/user/login",
            json={"email": email + "a", "password": password},
        )
        assert response.status_code == 401

        response = client.post(
            "/user/login",
            json={"email": email, "password": password + "a"},
        )
        assert response.status_code == 401
