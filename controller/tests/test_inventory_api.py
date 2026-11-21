"""Validation, uniqueness and deletion rules of the inventory API."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_helpers import API, World


@pytest.fixture
def client(world: World) -> TestClient:
    return world.as_("manager")


def create(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{API}{path}", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def site_body(**overrides: Any) -> dict[str, Any]:
    return {"name": "Paris", "nickname": "pari", "asn": 4200000001} | overrides


# --- creation and reading ----------------------------------------------------


def test_full_inventory(world: World, client: TestClient) -> None:
    mesh = world.ids["mesh"]
    site = create(client, f"/meshes/{mesh}/sites", site_body(location="Paris 11e"))
    assert site | {"id": None, "created_at": None} == {
        "id": None,
        "mesh_id": mesh,
        "name": "Paris",
        "nickname": "pari",
        "location": "Paris 11e",
        "asn": 4200000001,
        "created_at": None,
    }
    router = create(client, f"/sites/{site['id']}/routers", {"number": 1, "name": "home-r1"})
    assert router["site_id"] == site["id"]
    assert router["enrolled"] is False
    assert router["signing_key_revoked"] is False
    assert router["last_seen_at"] is None

    connection = create(
        client,
        f"/routers/{router['id']}/connections",
        {"number": 3, "name": "fiber", "role": "active", "priority": 10, "direct": "ipv6"},
    )
    assert connection["router_id"] == router["id"]
    assert connection["direct"] == "ipv6"
    assert connection["priority"] == 10
    assert connection["isp"] is None
    assert connection["public_ipv4"] is None
    assert connection["public_ipv6"] is None

    sites = client.get(f"{API}/meshes/{mesh}/sites").json()
    assert [s["nickname"] for s in sites] == ["pari", "root"]
    assert client.get(f"{API}/sites/{site['id']}/routers").json() == [router]
    assert client.get(f"{API}/routers/{router['id']}/connections").json() == [connection]


def test_connection_defaults(world: World, client: TestClient) -> None:
    connection = create(
        client,
        f"/routers/{world.ids['router']}/connections",
        {"number": 1, "name": "4g", "role": "backup"},
    )
    assert connection["direct"] == "none"
    assert connection["priority"] is None
    assert connection["description"] is None


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"nickname": "Pari"},
        {"nickname": "par"},
        {"nickname": "paris"},
        {"nickname": "pa-i"},
        {"asn": 4199999999},
        {"asn": 4294967295},
        {"asn": 65000},
        {"name": ""},
        {"name": "x" * 65},
        {"location": "x" * 65},
        {"kind": "home"},  # unknown field
    ],
)
def test_site_validation(world: World, client: TestClient, overrides: dict[str, Any]) -> None:
    response = client.post(f"{API}/meshes/{world.ids['mesh']}/sites", json=site_body(**overrides))
    assert response.status_code == 422, overrides


@pytest.mark.parametrize("asn", [4200000000 + 2, 4294967294])
def test_site_asn_bounds_accepted(world: World, client: TestClient, asn: int) -> None:
    create(client, f"/meshes/{world.ids['mesh']}/sites", site_body(asn=asn))


@pytest.mark.parametrize("number", [-1, 2])
def test_router_number_validation(world: World, client: TestClient, number: int) -> None:
    response = client.post(
        f"{API}/sites/{world.ids['site']}/routers", json={"number": number, "name": "x"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"number": 10},
        {"number": -1},
        {"direct": "yes"},
        {"role": "primary"},
        {"priority": -1},
        {"metered": True},  # unknown field
        {"public_ipv4": "203.0.113.7"},  # never entered by hand
    ],
)
def test_connection_validation(world: World, client: TestClient, overrides: dict[str, Any]) -> None:
    body = {"number": 1, "name": "4g", "role": "backup"} | overrides
    response = client.post(f"{API}/routers/{world.ids['router']}/connections", json=body)
    assert response.status_code == 422, overrides


@pytest.mark.parametrize("direct", ["none", "ipv4", "ipv6", "both"])
def test_connection_direct_values(world: World, client: TestClient, direct: str) -> None:
    response = client.patch(f"{API}/connections/{world.ids['connection']}", json={"direct": direct})
    assert response.json()["direct"] == direct


# --- partial updates ---------------------------------------------------------


def test_patch_changes_only_sent_fields(world: World, client: TestClient) -> None:
    site_url = f"{API}/sites/{world.ids['site']}"
    client.patch(site_url, json={"location": "DC 1"})
    site = client.patch(site_url, json={"asn": 4200000050}).json()
    assert (site["location"], site["asn"], site["nickname"]) == ("DC 1", 4200000050, "root")
    assert client.patch(site_url, json={"location": None}).json()["location"] is None


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/sites/{site}", {"nickname": None}),
        ("/sites/{site}", {"asn": None}),
        ("/routers/{router}", {"name": None}),
        ("/connections/{connection}", {"role": None}),
        ("/connections/{connection}", {"direct": None}),
        ("/meshes/{mesh}", {"name": None}),
    ],
)
def test_patch_refuses_null_for_required_fields(
    world: World, client: TestClient, path: str, body: dict[str, Any]
) -> None:
    response = client.patch(API + path.format(**world.ids), json=body)
    assert response.status_code == 422


def test_numbers_cannot_be_changed(world: World, client: TestClient) -> None:
    response = client.patch(f"{API}/routers/{world.ids['router']}", json={"number": 1})
    assert response.status_code == 422
    response = client.patch(f"{API}/connections/{world.ids['connection']}", json={"number": 1})
    assert response.status_code == 422


def test_connection_update(world: World, client: TestClient) -> None:
    url = f"{API}/connections/{world.ids['connection']}"
    body = {"role": "backup", "priority": 5, "description": "Starlink"}
    connection = client.patch(url, json=body).json()
    assert {k: connection[k] for k in body} == body
    assert client.patch(url, json={"priority": None}).json()["priority"] is None


# --- uniqueness --------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"name": "Hub Home42"}, "site_name_taken"),
        ({"nickname": "root"}, "nickname_taken"),
        ({"asn": 4200000000}, "asn_taken"),
    ],
)
def test_site_unique_within_mesh(
    world: World, client: TestClient, overrides: dict[str, Any], code: str
) -> None:
    response = client.post(f"{API}/meshes/{world.ids['mesh']}/sites", json=site_body(**overrides))
    assert (response.status_code, response.json()["code"]) == (409, code)

    # The same values in another mesh are accepted.
    other = create(world.as_("creator"), "/meshes", {"name": "other"})
    create(
        world.as_("creator"),
        f"/meshes/{other['id']}/sites",
        {"name": "Hub Home42", "nickname": "root", "asn": 4200000000},
    )


def test_site_update_uniqueness(world: World, client: TestClient) -> None:
    site = create(client, f"/meshes/{world.ids['mesh']}/sites", site_body())
    for body, code in [
        ({"nickname": "root"}, "nickname_taken"),
        ({"asn": 4200000000}, "asn_taken"),
        ({"name": "Hub Home42"}, "site_name_taken"),
    ]:
        response = client.patch(f"{API}/sites/{site['id']}", json=body)
        assert (response.status_code, response.json()["code"]) == (409, code)
    # Keeping its own values is not a conflict.
    response = client.patch(f"{API}/sites/{site['id']}", json=site_body())
    assert response.status_code == 200


def test_mesh_name_unique(world: World) -> None:
    response = world.as_("creator").post(f"{API}/meshes", json={"name": "home42"})
    assert (response.status_code, response.json()["code"]) == (409, "mesh_name_taken")
    other = create(world.as_("creator"), "/meshes", {"name": "other"})
    response = world.as_("creator").patch(f"{API}/meshes/{other['id']}", json={"name": "home42"})
    assert (response.status_code, response.json()["code"]) == (409, "mesh_name_taken")


def test_router_and_connection_numbers_unique(world: World, client: TestClient) -> None:
    response = client.post(
        f"{API}/sites/{world.ids['site']}/routers", json={"number": 0, "name": "again"}
    )
    assert (response.status_code, response.json()["code"]) == (409, "router_number_taken")
    response = client.post(
        f"{API}/routers/{world.ids['router']}/connections",
        json={"number": 0, "name": "again", "role": "active"},
    )
    assert (response.status_code, response.json()["code"]) == (409, "connection_number_taken")
    # Same numbers elsewhere: allowed.
    other_router = create(
        client, f"/sites/{world.ids['site']}/routers", {"number": 1, "name": "vps2"}
    )
    create(
        client,
        f"/routers/{other_router['id']}/connections",
        {"number": 0, "name": "uplink", "role": "active"},
    )


# --- deletion rules ----------------------------------------------------------


def test_mesh_and_site_deletion_refused_while_not_empty(world: World, client: TestClient) -> None:
    ids = world.ids
    response = client.delete(f"{API}/meshes/{ids['mesh']}")
    assert (response.status_code, response.json()["code"]) == (409, "mesh_not_empty")
    response = client.delete(f"{API}/sites/{ids['site']}")
    assert (response.status_code, response.json()["code"]) == (409, "site_not_empty")

    assert client.delete(f"{API}/routers/{ids['router']}").status_code == 204
    assert client.delete(f"{API}/sites/{ids['site']}").status_code == 204
    assert client.delete(f"{API}/meshes/{ids['mesh']}").status_code == 204
    assert client.get(f"{API}/meshes/{ids['mesh']}").status_code == 404
    # The accesses went with the mesh.
    assert world.as_("reader").get(f"{API}/meshes").json() == []


def test_router_deletion_cascades(world: World, client: TestClient) -> None:
    ids = world.ids
    assert client.delete(f"{API}/routers/{ids['router']}").status_code == 204
    assert client.get(f"{API}/connections/{ids['connection']}").status_code == 404
    assert client.get(f"{API}/sites/{ids['site']}/routers").json() == []


def test_connection_deletion(world: World, client: TestClient) -> None:
    ids = world.ids
    assert client.delete(f"{API}/connections/{ids['connection']}").status_code == 204
    assert client.get(f"{API}/routers/{ids['router']}/connections").json() == []
    assert client.get(f"{API}/routers/{ids['router']}").status_code == 200
