"""User management by the administrator."""

from typing import Any

from api_helpers import API, Env, first_login, login, use_token

FORBIDDEN_KEYS = {"password_hash", "totp_secret", "totp_last_step", "failed_login_count"}


def create(env: Env, username: str, **extra: Any) -> dict[str, Any]:
    response = env.client.post(f"{API}/users", json={"username": username, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_user(admin: Env) -> None:
    created = create(admin, "alice", can_create_meshes=True)
    user = created["user"]
    assert user["username"] == "alice"
    assert user["can_create_meshes"] is True
    assert user["is_admin"] is False
    assert user["must_change_password"] is True
    assert user["totp_enabled"] is False
    assert len(created["initial_password"]) >= 20
    assert not FORBIDDEN_KEYS & set(user)


def test_list_and_read_users(admin: Env) -> None:
    alice = create(admin, "alice")["user"]
    create(admin, "bob")
    users = admin.client.get(f"{API}/users").json()
    assert [u["username"] for u in users] == ["admin", "alice", "bob"]
    for user in users:
        assert not FORBIDDEN_KEYS & set(user)
    assert admin.client.get(f"{API}/users/{alice['id']}").json() == alice


def test_update_user(admin: Env) -> None:
    alice = create(admin, "alice")["user"]
    response = admin.client.patch(
        f"{API}/users/{alice['id']}", json={"username": "alice2", "can_create_meshes": True}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alice2"
    assert response.json()["can_create_meshes"] is True
    response = admin.client.patch(f"{API}/users/{alice['id']}", json={"can_create_meshes": False})
    assert response.json()["can_create_meshes"] is False
    assert response.json()["username"] == "alice2"


def test_username_conflicts(admin: Env) -> None:
    alice = create(admin, "alice")["user"]
    create(admin, "bob")
    response = admin.client.post(f"{API}/users", json={"username": "alice"})
    assert (response.status_code, response.json()["code"]) == (409, "username_taken")
    response = admin.client.patch(f"{API}/users/{alice['id']}", json={"username": "bob"})
    assert (response.status_code, response.json()["code"]) == (409, "username_taken")


def test_invalid_usernames(admin: Env) -> None:
    for username in ["Al", "UPPER", "-dash", "a b c", "x" * 65]:
        response = admin.client.post(f"{API}/users", json={"username": username})
        assert response.status_code == 422, username


def test_delete_user(admin: Env) -> None:
    alice = create(admin, "alice")["user"]
    assert admin.client.delete(f"{API}/users/{alice['id']}").status_code == 204
    response = admin.client.get(f"{API}/users/{alice['id']}")
    assert (response.status_code, response.json()["code"]) == (404, "user_not_found")
    assert admin.client.delete(f"{API}/users/{alice['id']}").status_code == 404


def test_administrator_protected(admin: Env) -> None:
    me = admin.client.get(f"{API}/auth/me").json()
    response = admin.client.delete(f"{API}/users/{me['id']}")
    assert (response.status_code, response.json()["code"]) == (409, "admin_cannot_be_deleted")
    response = admin.client.patch(f"{API}/users/{me['id']}", json={"can_create_meshes": False})
    assert (response.status_code, response.json()["code"]) == (409, "admin_rights_fixed")
    assert admin.client.get(f"{API}/users/{me['id']}").status_code == 200


def test_new_user_first_login_then_no_admin_rights(admin: Env) -> None:
    created = create(admin, "alice")
    client = admin.client
    client.post(f"{API}/auth/logout")

    assert login(client, "alice", created["initial_password"]).json() == {
        "next_step": "change_password"
    }
    assert client.get(f"{API}/users").json()["code"] == "setup_required"

    client.post(f"{API}/auth/logout")
    first_login(client, admin.clock, "alice", created["initial_password"], "alice password 2026")
    response = client.get(f"{API}/users")
    assert (response.status_code, response.json()["code"]) == (403, "admin_required")


def test_deleting_a_user_closes_its_sessions(admin: Env) -> None:
    created = create(admin, "alice")
    admin_token = admin.client.cookies.get("h42_session")
    login(admin.client, "alice", created["initial_password"])
    alice_token = admin.client.cookies.get("h42_session")

    use_token(admin.client, admin_token)
    admin.client.delete(f"{API}/users/{created['user']['id']}")
    use_token(admin.client, alice_token)
    assert admin.client.get(f"{API}/auth/me").status_code == 401


def test_users_routes_require_a_session(env: Env) -> None:
    for method, path in [
        ("GET", "/users"),
        ("POST", "/users"),
        ("GET", "/users/00000000-0000-0000-0000-000000000000"),
        ("PATCH", "/users/00000000-0000-0000-0000-000000000000"),
        ("DELETE", "/users/00000000-0000-0000-0000-000000000000"),
    ]:
        response = env.client.request(method, f"{API}{path}", json={})
        assert response.status_code == 401, (method, path)
        assert response.json()["code"] == "not_authenticated"
