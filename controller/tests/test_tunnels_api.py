"""Tunnels recomputed by inventory changes, and read through the API."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_helpers import API, World


@pytest.fixture
def client(world: World) -> TestClient:
    return world.as_("manager")


def post(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{API}{path}", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def tunnels(client: TestClient, world: World) -> list[dict[str, Any]]:
    response = client.get(f"{API}/meshes/{world.ids['mesh']}/tunnels")
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


@pytest.fixture
def home(world: World, client: TestClient) -> dict[str, Any]:
    """A home site (higher AS than the hub) with one router, no connection yet."""
    site = post(
        client,
        f"/meshes/{world.ids['mesh']}/sites",
        {"name": "Paris", "nickname": "pari", "asn": 4200000001},
    )
    router = post(client, f"/sites/{site['id']}/routers", {"number": 0, "name": "home"})
    return {"site": site, "router": router}


def hub_accepts_inbound(world: World, client: TestClient) -> None:
    response = client.patch(f"{API}/connections/{world.ids['connection']}", json={"direct": "both"})
    assert response.status_code == 200


def test_connection_creation_creates_tunnel(
    world: World, client: TestClient, home: dict[str, Any]
) -> None:
    hub_accepts_inbound(world, client)
    assert tunnels(client, world) == []  # the home router has no connection yet
    home_c0 = post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 0, "name": "fiber", "role": "active"},
    )

    (tunnel,) = tunnels(client, world)
    assert tunnel["a"]["connection_id"] == world.ids["connection"]
    assert tunnel["a"]["site_nickname"] == "root"
    assert tunnel["b"]["connection_id"] == home_c0["id"]
    assert (tunnel["b"]["router_number"], tunnel["b"]["connection_number"]) == (0, 0)
    assert tunnel["role"] == "active"
    assert tunnel["families"] == ["ipv6", "ipv4"]
    assert tunnel["ipv4_network"].startswith("169.254.")
    assert tunnel["ipv6_network"].startswith("fe80::a9fe:")
    assert tunnel["a"]["public_key"] is None
    assert tunnel["a"]["port"] is None
    assert "preshared_key" not in str(tunnel).lower()
    assert "psk" not in tunnel

    assert client.get(f"{API}/tunnels/{tunnel['id']}").json() == tunnel


def test_role_and_direct_changes(world: World, client: TestClient, home: dict[str, Any]) -> None:
    hub_accepts_inbound(world, client)
    home_c0 = post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 0, "name": "4g", "role": "backup"},
    )
    (tunnel,) = tunnels(client, world)
    assert tunnel["role"] == "backup"

    # backup <-> backup: no tunnel.
    client.patch(f"{API}/connections/{world.ids['connection']}", json={"role": "backup"})
    assert tunnels(client, world) == []

    # active again, but nobody accepts inbound: still none.
    client.patch(
        f"{API}/connections/{world.ids['connection']}", json={"role": "active", "direct": "none"}
    )
    assert tunnels(client, world) == []

    # The home connection accepts IPv6: it becomes a.
    client.patch(f"{API}/connections/{home_c0['id']}", json={"direct": "ipv6"})
    (tunnel,) = tunnels(client, world)
    assert tunnel["a"]["connection_id"] == home_c0["id"]
    assert tunnel["families"] == ["ipv6"]


def test_asn_change_swaps_ends(world: World, client: TestClient, home: dict[str, Any]) -> None:
    hub_accepts_inbound(world, client)
    home_c0 = post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 0, "name": "fiber", "role": "active", "direct": "both"},
    )
    (before,) = tunnels(client, world)
    assert before["a"]["connection_id"] == world.ids["connection"]  # hub: lower AS

    client.patch(f"{API}/sites/{world.ids['site']}", json={"asn": 4200000009})
    (after,) = tunnels(client, world)
    assert after["id"] == before["id"]
    assert after["a"]["connection_id"] == home_c0["id"]
    assert after["ipv4_network"] == before["ipv4_network"]


def test_deletions_remove_tunnels(world: World, client: TestClient, home: dict[str, Any]) -> None:
    hub_accepts_inbound(world, client)
    c0 = post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 0, "name": "fiber", "role": "active"},
    )
    post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 1, "name": "4g", "role": "backup"},
    )
    assert len(tunnels(client, world)) == 2

    client.delete(f"{API}/connections/{c0['id']}")
    assert len(tunnels(client, world)) == 1
    client.delete(f"{API}/routers/{home['router']['id']}")
    assert tunnels(client, world) == []


def test_second_router_of_a_site_gets_no_internal_tunnel(world: World, client: TestClient) -> None:
    hub_accepts_inbound(world, client)
    r1 = post(client, f"/sites/{world.ids['site']}/routers", {"number": 1, "name": "vps2"})
    post(
        client,
        f"/routers/{r1['id']}/connections",
        {"number": 0, "name": "uplink", "role": "active", "direct": "both"},
    )
    assert tunnels(client, world) == []


@pytest.mark.parametrize(
    ("role", "status"), [("admin", 200), ("manager", 200), ("reader", 200), ("outsider", 404)]
)
def test_tunnel_read_rights(
    world: World, client: TestClient, home: dict[str, Any], role: str, status: int
) -> None:
    hub_accepts_inbound(world, client)
    post(
        client,
        f"/routers/{home['router']['id']}/connections",
        {"number": 0, "name": "fiber", "role": "active"},
    )
    (tunnel,) = tunnels(client, world)
    viewer = world.as_(role)
    assert viewer.get(f"{API}/meshes/{world.ids['mesh']}/tunnels").status_code == status
    response = viewer.get(f"{API}/tunnels/{tunnel['id']}")
    assert response.status_code == status
    if status == 404:
        assert response.json()["code"] == "tunnel_not_found"
    assert world.as_(None).get(f"{API}/tunnels/{tunnel['id']}").status_code == 401


def test_tunnels_cannot_be_created_by_hand(world: World, client: TestClient) -> None:
    response = client.post(f"{API}/meshes/{world.ids['mesh']}/tunnels", json={})
    assert response.status_code == 405
