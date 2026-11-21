"""Rights on meshes and their inventory, for every role."""

from dataclasses import dataclass
from typing import Any

import pytest

from api_helpers import API, World, login, use_token

ROLES = ("admin", "manager", "reader", "outsider")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str  # {mesh}, {site}, {router}, {connection}, {outsider_id}, {reader_id}
    body: dict[str, Any] | None
    allowed: int  # status for roles that hold the right
    manage: bool  # True: manage required; False: read is enough

    def url(self, world: World) -> str:
        return API + self.path.format(
            outsider_id=world.user_ids["outsider"],
            reader_id=world.user_ids["reader"],
            **world.ids,
        )


OPERATIONS = [
    # Read operations.
    Operation("GET", "/meshes/{mesh}", None, 200, manage=False),
    Operation("GET", "/meshes/{mesh}/sites", None, 200, manage=False),
    Operation("GET", "/sites/{site}", None, 200, manage=False),
    Operation("GET", "/sites/{site}/routers", None, 200, manage=False),
    Operation("GET", "/routers/{router}", None, 200, manage=False),
    Operation("GET", "/routers/{router}/connections", None, 200, manage=False),
    Operation("GET", "/connections/{connection}", None, 200, manage=False),
    # Accesses: manage only, even to list them.
    Operation("GET", "/meshes/{mesh}/accesses", None, 200, manage=True),
    Operation("PUT", "/meshes/{mesh}/accesses/{outsider_id}", {"level": "read"}, 200, True),
    Operation("DELETE", "/meshes/{mesh}/accesses/{reader_id}", None, 204, manage=True),
    # Modifications.
    Operation("PATCH", "/meshes/{mesh}", {"name": "renamed"}, 200, manage=True),
    Operation("DELETE", "/meshes/{mesh}", None, 409, manage=True),  # not empty
    Operation(
        "POST",
        "/meshes/{mesh}/sites",
        {"name": "Paris", "nickname": "pari", "asn": 4200000001},
        201,
        manage=True,
    ),
    Operation("PATCH", "/sites/{site}", {"location": "DC 1"}, 200, manage=True),
    Operation("DELETE", "/sites/{site}", None, 409, manage=True),  # has a router
    Operation("POST", "/sites/{site}/routers", {"number": 1, "name": "vps2"}, 201, True),
    Operation("PATCH", "/routers/{router}", {"name": "renamed"}, 200, manage=True),
    Operation("DELETE", "/routers/{router}", None, 204, manage=True),
    Operation(
        "POST",
        "/routers/{router}/connections",
        {"number": 1, "name": "4g", "role": "backup"},
        201,
        manage=True,
    ),
    Operation("PATCH", "/connections/{connection}", {"direct": "both"}, 200, manage=True),
    # Enrollment.
    Operation("POST", "/routers/{router}/enrollment-tokens", None, 201, manage=True),
    Operation("POST", "/routers/{router}/revoke", None, 200, manage=True),
    Operation("DELETE", "/connections/{connection}", None, 204, manage=True),
]


def expected(operation: Operation, role: str) -> tuple[int, str | None]:
    if role == "outsider":
        return 404, None  # existence not revealed
    if role == "reader" and operation.manage:
        return 403, "manage_required"
    return operation.allowed, None


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda op: f"{op.method} {op.path}")
def test_rights(world: World, operation: Operation, role: str) -> None:
    client = world.as_(role)
    response = client.request(operation.method, operation.url(world), json=operation.body)
    status, error_code = expected(operation, role)
    assert response.status_code == status, response.text
    if error_code is not None:
        assert response.json()["code"] == error_code
    if status == 404:
        assert response.json()["code"].endswith("_not_found")


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda op: f"{op.method} {op.path}")
def test_no_session(world: World, operation: Operation) -> None:
    response = world.as_(None).request(operation.method, operation.url(world), json=operation.body)
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_unfinished_first_login_is_refused(world: World) -> None:
    created = world.as_("admin").post(f"{API}/users", json={"username": "newbie"}).json()
    use_token(world.client, None)
    login(world.client, "newbie", created["initial_password"])
    response = world.client.get(f"{API}/meshes")
    assert response.status_code == 403
    assert response.json()["code"] == "setup_required"


def test_unknown_objects(world: World) -> None:
    client = world.as_("admin")
    missing = "00000000-0000-0000-0000-000000000000"
    for path, code in [
        (f"/meshes/{missing}", "mesh_not_found"),
        (f"/sites/{missing}", "site_not_found"),
        (f"/routers/{missing}", "router_not_found"),
        (f"/connections/{missing}", "connection_not_found"),
    ]:
        response = client.get(API + path)
        assert (response.status_code, response.json()["code"]) == (404, code)


# --- mesh list and creation --------------------------------------------------


@pytest.mark.parametrize(
    ("role", "names"),
    [
        ("admin", {"home42": "manage"}),
        ("manager", {"home42": "manage"}),
        ("reader", {"home42": "read"}),
        ("outsider", {}),
        ("creator", {}),
    ],
)
def test_mesh_list_depends_on_role(world: World, role: str, names: dict[str, str]) -> None:
    meshes = world.as_(role).get(f"{API}/meshes").json()
    assert {m["name"]: m["access_level"] for m in meshes} == names


def test_admin_sees_every_mesh(world: World) -> None:
    world.as_("creator").post(f"{API}/meshes", json={"name": "other"})
    names = [m["name"] for m in world.as_("admin").get(f"{API}/meshes").json()]
    assert names == ["home42", "other"]


@pytest.mark.parametrize(
    ("role", "status"),
    [("admin", 201), ("creator", 201), ("manager", 403), ("reader", 403), ("outsider", 403)],
)
def test_mesh_creation_right(world: World, role: str, status: int) -> None:
    response = world.as_(role).post(f"{API}/meshes", json={"name": f"by-{role}"})
    assert response.status_code == status, response.text
    if status == 403:
        assert response.json()["code"] == "mesh_creation_forbidden"
    else:
        assert response.json()["access_level"] == "manage"


def test_creator_manages_the_new_mesh(world: World) -> None:
    client = world.as_("creator")
    mesh = client.post(f"{API}/meshes", json={"name": "dave-mesh"}).json()
    accesses = client.get(f"{API}/meshes/{mesh['id']}/accesses").json()
    assert accesses == [
        {"user_id": world.user_ids["creator"], "username": "creator", "level": "manage"}
    ]
    response = client.post(
        f"{API}/meshes/{mesh['id']}/sites",
        json={"name": "Home", "nickname": "home", "asn": 4200000010},
    )
    assert response.status_code == 201
    # Nobody else sees it, except the administrator.
    assert world.as_("manager").get(f"{API}/meshes/{mesh['id']}").status_code == 404
    assert world.as_("admin").get(f"{API}/meshes/{mesh['id']}").status_code == 200


def test_admin_created_mesh_has_no_access_row(world: World) -> None:
    accesses = world.as_("admin").get(f"{API}/meshes/{world.ids['mesh']}/accesses").json()
    assert {a["username"]: a["level"] for a in accesses} == {
        "manager": "manage",
        "reader": "read",
    }


# --- granting and revoking ---------------------------------------------------


def test_manager_grants_changes_and_revokes(world: World) -> None:
    mesh = world.ids["mesh"]
    manager = world.as_("manager")
    outsider_id = world.user_ids["outsider"]

    response = manager.put(f"{API}/meshes/{mesh}/accesses/{outsider_id}", json={"level": "read"})
    assert response.json() == {"user_id": outsider_id, "username": "outsider", "level": "read"}
    assert world.as_("outsider").get(f"{API}/meshes/{mesh}").json()["access_level"] == "read"
    response = world.as_("outsider").patch(f"{API}/meshes/{mesh}", json={"name": "x"})
    assert response.status_code == 403

    world.as_("manager").put(
        f"{API}/meshes/{mesh}/accesses/{outsider_id}", json={"level": "manage"}
    )
    response = world.as_("outsider").patch(f"{API}/meshes/{mesh}", json={"name": "renamed"})
    assert response.status_code == 200

    response = world.as_("manager").delete(f"{API}/meshes/{mesh}/accesses/{outsider_id}")
    assert response.status_code == 204
    assert world.as_("outsider").get(f"{API}/meshes/{mesh}").status_code == 404


def test_access_errors(world: World) -> None:
    mesh = world.ids["mesh"]
    client = world.as_("manager")
    missing = "00000000-0000-0000-0000-000000000000"

    response = client.put(f"{API}/meshes/{mesh}/accesses/{missing}", json={"level": "read"})
    assert (response.status_code, response.json()["code"]) == (404, "user_not_found")
    response = client.put(
        f"{API}/meshes/{mesh}/accesses/{world.user_ids['admin']}", json={"level": "read"}
    )
    assert (response.status_code, response.json()["code"]) == (409, "user_is_admin")
    response = client.delete(f"{API}/meshes/{mesh}/accesses/{world.user_ids['outsider']}")
    assert (response.status_code, response.json()["code"]) == (404, "access_not_found")
    response = client.put(
        f"{API}/meshes/{mesh}/accesses/{world.user_ids['outsider']}", json={"level": "owner"}
    )
    assert response.status_code == 422


def test_manager_may_drop_its_own_access(world: World) -> None:
    mesh = world.ids["mesh"]
    response = world.as_("manager").delete(
        f"{API}/meshes/{mesh}/accesses/{world.user_ids['manager']}"
    )
    assert response.status_code == 204
    assert world.as_("manager").get(f"{API}/meshes/{mesh}").status_code == 404
    assert world.as_("admin").get(f"{API}/meshes/{mesh}").status_code == 200


# --- user lookup -------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "status"),
    [("admin", 200), ("manager", 200), ("reader", 403), ("outsider", 403), ("creator", 403)],
)
def test_user_lookup_rights(world: World, role: str, status: int) -> None:
    response = world.as_(role).get(f"{API}/users/lookup", params={"username": "outsider"})
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json() == {"id": world.user_ids["outsider"], "username": "outsider"}
    else:
        assert response.json()["code"] == "manage_required"


def test_user_lookup_then_grant(world: World) -> None:
    client = world.as_("manager")
    found = client.get(f"{API}/users/lookup", params={"username": "outsider"}).json()
    response = client.put(
        f"{API}/meshes/{world.ids['mesh']}/accesses/{found['id']}", json={"level": "read"}
    )
    assert response.status_code == 200


def test_user_lookup_errors(world: World) -> None:
    client = world.as_("manager")
    response = client.get(f"{API}/users/lookup", params={"username": "nobody"})
    assert (response.status_code, response.json()["code"]) == (404, "user_not_found")
    assert client.get(f"{API}/users/lookup").status_code == 422
    assert world.as_(None).get(f"{API}/users/lookup", params={"username": "x"}).status_code == 401


def test_creator_may_look_up_once_managing_a_mesh(world: World) -> None:
    client = world.as_("creator")
    client.post(f"{API}/meshes", json={"name": "own"})
    response = client.get(f"{API}/users/lookup", params={"username": "reader"})
    assert response.status_code == 200
