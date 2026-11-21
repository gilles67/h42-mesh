"""Agent calls: configuration, public addresses, tunnel keys, states, BGP table."""

import os
from dataclasses import dataclass
from typing import Any

import maxminddb
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from agent_helpers import Agent, create_token, enroll
from api_helpers import API, World, use_token
from h42mesh.controller import geoip
from h42mesh.controller.agent_config import matches_if_none_match


@dataclass
class Mesh:
    """Hub (root, lower AS, accepts inbound), home (pari) and lyon, all enrolled."""

    world: World
    hub: Agent
    home: Agent
    lyon: Agent
    hub_conn: str
    home_conn: str
    lyon_conn: str

    @property
    def client(self) -> TestClient:
        return self.world.client

    def request(
        self, agent: Agent, method: str, path: str, json: Any = None, **headers: str
    ) -> Response:
        use_token(self.client, None)
        headers["Authorization"] = f"Bearer {agent.token()}"
        return self.client.request(method, f"{API}/agent{path}", json=json, headers=headers)

    def config(self, agent: Agent, **headers: str) -> Response:
        return self.request(agent, "GET", "/config", **headers)

    def tunnel(self, agent: Agent, peer_conn: str) -> dict[str, Any]:
        tunnels = self.config(agent).json()["tunnels"]
        (tunnel,) = [t for t in tunnels if t["peer"]["connection_id"] == peer_conn]
        result: dict[str, Any] = tunnel
        return result


def _post(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{API}{path}", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _enrolled(world: World, router_id: str) -> Agent:
    agent = Agent(router_id)
    assert enroll(world.client, create_token(world, router_id), agent.public_key).is_success
    return agent


@pytest.fixture
def mesh(world: World) -> Mesh:
    manager = world.as_("manager")
    manager.patch(f"{API}/connections/{world.ids['connection']}", json={"direct": "both"})
    conns = {}
    routers = {}
    for nickname, asn in (("pari", 4200000001), ("lyon", 4200000002)):
        site = _post(
            manager,
            f"/meshes/{world.ids['mesh']}/sites",
            {"name": nickname, "nickname": nickname, "asn": asn},
        )
        router = _post(manager, f"/sites/{site['id']}/routers", {"number": 0, "name": "r0"})
        conns[nickname] = _post(
            manager,
            f"/routers/{router['id']}/connections",
            {"number": 0, "name": "fiber", "role": "active"},
        )["id"]
        routers[nickname] = router["id"]
        manager = world.as_("manager")
    return Mesh(
        world=world,
        hub=_enrolled(world, world.ids["router"]),
        home=_enrolled(world, routers["pari"]),
        lyon=_enrolled(world, routers["lyon"]),
        hub_conn=world.ids["connection"],
        home_conn=conns["pari"],
        lyon_conn=conns["lyon"],
    )


def set_public_addresses(mesh: Mesh, agent: Agent, conn: str, v4: str, v6: str) -> None:
    for family, address in (("ipv4", v4), ("ipv6", v6)):
        response = mesh.request(
            agent,
            "POST",
            "/public-address",
            {"connection_id": conn, "family": family, "forced_address": address},
        )
        assert response.status_code == 200, response.text


def report_keys(mesh: Mesh, agent: Agent, tunnel_id: str, key: str, port: int) -> Response:
    return mesh.request(
        agent,
        "POST",
        "/tunnels",
        {"tunnels": [{"tunnel_id": tunnel_id, "public_key": key, "port": port}]},
    )


# --- configuration -----------------------------------------------------------


def test_config_of_listening_side(mesh: Mesh) -> None:
    response = mesh.config(mesh.hub)
    assert response.status_code == 200
    config = response.json()
    assert config["format"] == 1
    assert config["site"] == {"id": mesh.world.ids["site"], "nickname": "root", "asn": 4200000000}
    assert config["router"]["number"] == 0
    assert [c["id"] for c in config["connections"]] == [mesh.hub_conn]
    assert len(config["tunnels"]) == 2  # to pari and to lyon

    tunnel = mesh.tunnel(mesh.hub, mesh.home_conn)
    assert tunnel["side"] == "a"
    assert tunnel["role"] == "active"
    assert tunnel["families"] == ["ipv6", "ipv4"]
    assert tunnel["local_connection_id"] == mesh.hub_conn
    first = tunnel["ipv4_network"].split("/")[0]
    assert tunnel["local_ipv4"] == first
    assert tunnel["local_ipv6"] == tunnel["ipv6_network"].split("/")[0]
    assert len(tunnel["preshared_key"]) == 44
    peer = tunnel["peer"]
    assert (peer["site_nickname"], peer["site_asn"]) == ("pari", 4200000001)
    assert (peer["router_number"], peer["connection_number"]) == (0, 0)
    assert peer["port"] is None  # a does not contact b
    assert peer["endpoints"] == []


def test_config_of_initiating_side(mesh: Mesh) -> None:
    set_public_addresses(mesh, mesh.hub, mesh.hub_conn, "198.51.100.1", "2001:db8::1")
    hub_side = mesh.tunnel(mesh.hub, mesh.home_conn)
    report_keys(mesh, mesh.hub, hub_side["id"], Agent("").public_key, 42000)

    tunnel = mesh.tunnel(mesh.home, mesh.hub_conn)
    assert tunnel["id"] == hub_side["id"]
    assert tunnel["side"] == "b"
    assert tunnel["preshared_key"] == hub_side["preshared_key"]
    assert (tunnel["local_ipv4"], tunnel["peer_ipv4"]) == (
        hub_side["peer_ipv4"],
        hub_side["local_ipv4"],
    )
    assert (tunnel["local_ipv6"], tunnel["peer_ipv6"]) == (
        hub_side["peer_ipv6"],
        hub_side["local_ipv6"],
    )
    assert tunnel["peer"]["port"] == 42000
    assert tunnel["peer"]["public_key"] is not None
    assert tunnel["peer"]["endpoints"] == [
        {"family": "ipv6", "address": "2001:db8::1"},
        {"family": "ipv4", "address": "198.51.100.1"},
    ]


def test_endpoints_follow_the_families_of_a(mesh: Mesh) -> None:
    set_public_addresses(mesh, mesh.hub, mesh.hub_conn, "198.51.100.1", "2001:db8::1")
    mesh.world.as_("manager").patch(f"{API}/connections/{mesh.hub_conn}", json={"direct": "ipv4"})
    tunnel = mesh.tunnel(mesh.home, mesh.hub_conn)
    assert tunnel["families"] == ["ipv4"]
    assert tunnel["peer"]["endpoints"] == [{"family": "ipv4", "address": "198.51.100.1"}]


def test_incomplete_tunnel(mesh: Mesh) -> None:
    tunnel = mesh.tunnel(mesh.home, mesh.hub_conn)
    assert tunnel["peer"]["public_key"] is None
    assert tunnel["peer"]["port"] is None
    assert tunnel["local_public_key"] is None
    assert tunnel["local_port"] is None


def test_psk_only_for_both_ends(mesh: Mesh) -> None:
    """Lyon sees its own tunnel to the hub, never the hub <-> pari tunnel."""
    home_tunnel = mesh.tunnel(mesh.home, mesh.hub_conn)
    lyon = mesh.config(mesh.lyon).json()
    assert [t["peer"]["connection_id"] for t in lyon["tunnels"]] == [mesh.hub_conn]
    assert home_tunnel["id"] not in str(lyon)
    assert home_tunnel["preshared_key"] not in str(lyon)
    assert mesh.home_conn not in str(lyon)


def test_etag_and_304(mesh: Mesh) -> None:
    first = mesh.config(mesh.home)
    fingerprint = first.json()["fingerprint"]
    assert first.headers["etag"] == f'"{fingerprint}"'
    assert mesh.config(mesh.home).json()["fingerprint"] == fingerprint  # stable

    for header in (
        f'"{fingerprint}"',
        fingerprint,
        f'W/"{fingerprint}"',
        f'"old", "{fingerprint}"',
    ):
        response = mesh.config(mesh.home, **{"If-None-Match": header})
        assert response.status_code == 304, header
        assert response.content == b""
        assert response.headers["etag"] == f'"{fingerprint}"'
    assert mesh.config(mesh.home, **{"If-None-Match": '"old"'}).status_code == 200


@pytest.mark.parametrize("change", ["peer_key", "peer_address", "role", "new_tunnel", "asn"])
def test_fingerprint_changes(mesh: Mesh, change: str) -> None:
    before = mesh.config(mesh.home).json()["fingerprint"]
    manager = mesh.world.as_("manager")
    if change == "peer_key":
        tunnel = mesh.tunnel(mesh.hub, mesh.home_conn)
        report_keys(mesh, mesh.hub, tunnel["id"], Agent("").public_key, 42000)
    elif change == "peer_address":
        set_public_addresses(mesh, mesh.hub, mesh.hub_conn, "198.51.100.1", "2001:db8::1")
    elif change == "role":
        manager.patch(f"{API}/connections/{mesh.home_conn}", json={"role": "backup"})
    elif change == "new_tunnel":
        router_id = mesh.home.router_id
        _post(
            manager,
            f"/routers/{router_id}/connections",
            {"number": 1, "name": "4g", "role": "backup"},
        )
    elif change == "asn":
        manager.patch(f"{API}/sites/{mesh.world.ids['site']}", json={"asn": 4200000009})
    assert mesh.config(mesh.home).json()["fingerprint"] != before


def test_config_requires_agent_auth(mesh: Mesh) -> None:
    use_token(mesh.client, None)
    assert mesh.client.get(f"{API}/agent/config").status_code == 401


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, False), ("", False), ("*", True), ('"x"', False), ('W/"abc"', True), ("abc", True)],
)
def test_if_none_match_parsing(header: str | None, expected: bool) -> None:
    assert matches_if_none_match(header, "abc") is expected


# --- public addresses --------------------------------------------------------


@pytest.fixture
def source(mesh: Mesh, monkeypatch: pytest.MonkeyPatch) -> Any:
    def set_source(host: str) -> None:
        monkeypatch.setattr(mesh.client._transport, "client", (host, 50000))

    return set_source


def address(
    mesh: Mesh,
    agent: Agent,
    conn: str,
    family: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> Response:
    body = {"connection_id": conn, "family": family, **extra}
    return mesh.request(agent, "POST", "/public-address", body, **(headers or {}))


def test_seen_address(mesh: Mesh, source: Any) -> None:
    source("93.184.216.34")
    response = address(mesh, mesh.home, mesh.home_conn, "ipv4")
    assert response.json() == {"family": "ipv4", "address": "93.184.216.34", "isp": None}
    connection = mesh.world.as_("manager").get(f"{API}/connections/{mesh.home_conn}").json()
    assert connection["public_ipv4"] == "93.184.216.34"
    assert connection["public_ipv4_updated_at"] is not None


def test_seen_ipv6_and_mapped_ipv4(mesh: Mesh, source: Any) -> None:
    source("2a00:1450:4007:80c::200e")
    assert address(mesh, mesh.home, mesh.home_conn, "ipv6").json()["address"] == (
        "2a00:1450:4007:80c::200e"
    )
    source("::ffff:93.184.216.34")
    assert address(mesh, mesh.home, mesh.home_conn, "ipv4").json()["address"] == "93.184.216.34"


def test_forced_address(mesh: Mesh, source: Any) -> None:
    source("10.0.0.5")  # e.g. the controller itself, reached locally
    response = address(mesh, mesh.hub, mesh.hub_conn, "ipv4", forced_address="198.51.100.1")
    assert response.json()["address"] == "198.51.100.1"


@pytest.mark.parametrize(
    ("family", "forced", "code"),
    [
        ("ipv4", "2001:db8::1", "family_mismatch"),
        ("ipv6", "198.51.100.1", "family_mismatch"),
        ("ipv4", "not-an-ip", "invalid_address"),
        ("ipv6", "2001:DB8::1", "invalid_address"),
    ],
)
def test_forced_address_errors(mesh: Mesh, family: str, forced: str, code: str) -> None:
    response = address(mesh, mesh.hub, mesh.hub_conn, family, forced_address=forced)
    assert (response.status_code, response.json()["code"]) == (422, code)


def test_seen_family_mismatch(mesh: Mesh, source: Any) -> None:
    source("93.184.216.34")
    response = address(mesh, mesh.home, mesh.home_conn, "ipv6")
    assert (response.status_code, response.json()["code"]) == (422, "family_mismatch")


@pytest.mark.parametrize("host", ["192.168.1.10", "10.1.2.3", "127.0.0.1", "fe80::1", "fd00::1"])
def test_seen_address_must_be_public(mesh: Mesh, source: Any, host: str) -> None:
    source(host)
    family = "ipv6" if ":" in host else "ipv4"
    response = address(mesh, mesh.home, mesh.home_conn, family)
    assert (response.status_code, response.json()["code"]) == (422, "address_not_public")


def test_connection_of_another_router(mesh: Mesh) -> None:
    response = address(mesh, mesh.lyon, mesh.home_conn, "ipv4", forced_address="198.51.100.7")
    assert (response.status_code, response.json()["code"]) == (404, "connection_not_found")
    connection = mesh.world.as_("manager").get(f"{API}/connections/{mesh.home_conn}").json()
    assert connection["public_ipv4"] is None


def test_forwarded_header_ignored_from_untrusted_peer(mesh: Mesh, source: Any) -> None:
    source("93.184.216.34")
    response = address(
        mesh, mesh.home, mesh.home_conn, "ipv4", headers={"X-Forwarded-For": "198.51.100.66"}
    )
    assert response.json()["address"] == "93.184.216.34"


def test_forwarded_header_from_trusted_proxy(mesh: Mesh, source: Any) -> None:
    mesh.world.env.settings.trusted_proxies = ["10.89.0.0/24"]
    source("10.89.0.2")  # Traefik
    response = address(
        mesh,
        mesh.home,
        mesh.home_conn,
        "ipv4",
        headers={"X-Forwarded-For": "6.6.6.6, 93.184.216.34, 10.89.0.3"},
    )
    # Rightmost untrusted hop; the forged leftmost value is ignored.
    assert response.json()["address"] == "93.184.216.34"


def test_trusted_proxy_without_header_means_proxy_address(mesh: Mesh, source: Any) -> None:
    mesh.world.env.settings.trusted_proxies = ["10.89.0.0/24"]
    source("10.89.0.2")
    response = address(mesh, mesh.home, mesh.home_conn, "ipv4")
    assert response.json()["code"] == "address_not_public"


class FakeReader:
    def get(self, ip_address: str) -> object:
        return {
            "93.184.216.34": {"autonomous_system_organization": "Edgecast"},
            "2a00:1450:4007:80c::200e": {"autonomous_system_organization": "Google"},
        }.get(ip_address)


def test_isp_from_geolite2(mesh: Mesh, source: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    mesh.world.env.settings.geolite2_asn_file = mesh.world.env.settings.passphrase_file
    monkeypatch.setattr(geoip, "open_reader", lambda path, mtime_ns: FakeReader())
    source("2a00:1450:4007:80c::200e")
    assert address(mesh, mesh.home, mesh.home_conn, "ipv6").json()["isp"] == "Google"
    source("93.184.216.34")  # IPv4 known: it wins
    assert address(mesh, mesh.home, mesh.home_conn, "ipv4").json()["isp"] == "Edgecast"
    connection = mesh.world.as_("manager").get(f"{API}/connections/{mesh.home_conn}").json()
    assert connection["isp"] == "Edgecast"


def test_isp_unchanged_without_database(mesh: Mesh, source: Any) -> None:
    source("93.184.216.34")
    assert address(mesh, mesh.home, mesh.home_conn, "ipv4").json()["isp"] is None


def test_unreadable_geolite2_file(tmp_path: Any) -> None:
    geoip.open_reader.cache_clear()
    assert geoip.isp_for("93.184.216.34", tmp_path / "missing.mmdb") is None
    assert geoip.isp_for("93.184.216.34", None) is None


# --- tunnel keys and ports ---------------------------------------------------


def test_report_keys_fills_the_right_side(mesh: Mesh) -> None:
    tunnel_id = mesh.tunnel(mesh.home, mesh.hub_conn)["id"]
    hub_key, home_key = Agent("").public_key, Agent("").public_key
    assert report_keys(mesh, mesh.hub, tunnel_id, hub_key, 42000).status_code == 204
    assert report_keys(mesh, mesh.home, tunnel_id, home_key, 42005).status_code == 204

    hub_view = mesh.tunnel(mesh.hub, mesh.home_conn)
    assert (hub_view["local_public_key"], hub_view["local_port"]) == (hub_key, 42000)
    assert hub_view["peer"]["public_key"] == home_key
    home_view = mesh.tunnel(mesh.home, mesh.hub_conn)
    assert (home_view["local_public_key"], home_view["local_port"]) == (home_key, 42005)
    assert (home_view["peer"]["public_key"], home_view["peer"]["port"]) == (hub_key, 42000)

    gui = mesh.world.as_("reader").get(f"{API}/tunnels/{tunnel_id}").json()
    assert (gui["a"]["port"], gui["b"]["port"]) == (42000, 42005)


def test_report_keys_of_another_router_refused(mesh: Mesh) -> None:
    tunnel_id = mesh.tunnel(mesh.home, mesh.hub_conn)["id"]
    response = report_keys(mesh, mesh.lyon, tunnel_id, Agent("").public_key, 42000)
    assert (response.status_code, response.json()["code"]) == (404, "tunnel_not_found")
    assert mesh.tunnel(mesh.hub, mesh.home_conn)["peer"]["public_key"] is None


def test_port_used_once_per_router(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    to_lyon = mesh.tunnel(mesh.hub, mesh.lyon_conn)["id"]
    assert report_keys(mesh, mesh.hub, to_home, Agent("").public_key, 42000).status_code == 204
    response = report_keys(mesh, mesh.hub, to_lyon, Agent("").public_key, 42000)
    assert (response.status_code, response.json()["code"]) == (409, "port_in_use")
    # Same port on another router: allowed.
    assert report_keys(mesh, mesh.home, to_home, Agent("").public_key, 42000).status_code == 204


def test_report_keys_is_all_or_nothing(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    to_lyon = mesh.tunnel(mesh.hub, mesh.lyon_conn)["id"]
    response = mesh.request(
        mesh.hub,
        "POST",
        "/tunnels",
        {
            "tunnels": [
                {"tunnel_id": to_home, "public_key": Agent("").public_key, "port": 42001},
                {"tunnel_id": to_lyon, "public_key": Agent("").public_key, "port": 42001},
            ]
        },
    )
    assert response.status_code == 409
    assert mesh.tunnel(mesh.hub, mesh.home_conn)["local_port"] is None


@pytest.mark.parametrize(
    "item", [{"public_key": "short", "port": 42000}, {"port": 0}, {"port": 65536}]
)
def test_report_keys_validation(mesh: Mesh, item: dict[str, Any]) -> None:
    tunnel_id = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    body = {"tunnel_id": tunnel_id, "public_key": Agent("").public_key, "port": 42000} | item
    response = mesh.request(mesh.hub, "POST", "/tunnels", {"tunnels": [body]})
    assert response.status_code == 422


# --- tunnel states -----------------------------------------------------------


def statuses(mesh: Mesh, agent: Agent, items: list[dict[str, Any]]) -> Response:
    return mesh.request(agent, "PUT", "/tunnel-status", {"tunnels": items})


def test_tunnel_status_snapshot(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    to_lyon = mesh.tunnel(mesh.hub, mesh.lyon_conn)["id"]
    items = [
        {
            "tunnel_id": to_home,
            "family_in_use": "ipv6",
            "last_handshake_at": "2026-11-21T10:00:00Z",
            "bgp_established": True,
        },
        {"tunnel_id": to_lyon},
    ]
    assert statuses(mesh, mesh.hub, items).status_code == 204
    assert statuses(mesh, mesh.home, [{"tunnel_id": to_home, "family_in_use": "ipv4"}]).is_success
    counts = mesh.client.portal.call(_count_statuses)  # type: ignore[union-attr]
    assert counts == {mesh.hub.router_id: 2, mesh.home.router_id: 1}

    # A new snapshot replaces the previous one of the same router only.
    assert statuses(mesh, mesh.hub, [{"tunnel_id": to_lyon}]).status_code == 204
    counts = mesh.client.portal.call(_count_statuses)  # type: ignore[union-attr]
    assert counts == {mesh.hub.router_id: 1, mesh.home.router_id: 1}
    assert statuses(mesh, mesh.hub, []).status_code == 204
    counts = mesh.client.portal.call(_count_statuses)  # type: ignore[union-attr]
    assert counts == {mesh.home.router_id: 1}


async def _count_statuses() -> dict[str, int]:
    from h42mesh.controller.models import TunnelStatus

    rows = await TunnelStatus.all().prefetch_related("router")
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.router.id)] = counts.get(str(row.router.id), 0) + 1
    return counts


async def _count_routes() -> dict[str, int]:
    from h42mesh.controller.models import BgpRoute

    counts: dict[str, int] = {}
    for row in await BgpRoute.all().prefetch_related("router"):
        counts[str(row.router.id)] = counts.get(str(row.router.id), 0) + 1
    return counts


def test_tunnel_status_of_another_router_refused(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    response = statuses(mesh, mesh.lyon, [{"tunnel_id": to_home}])
    assert (response.status_code, response.json()["code"]) == (404, "tunnel_not_found")


def test_tunnel_status_duplicates_refused(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    response = statuses(mesh, mesh.hub, [{"tunnel_id": to_home}, {"tunnel_id": to_home}])
    assert (response.status_code, response.json()["code"]) == (422, "duplicate_tunnel")


# --- BGP table ---------------------------------------------------------------


def routes(mesh: Mesh, agent: Agent, items: list[dict[str, Any]]) -> Response:
    return mesh.request(agent, "PUT", "/bgp-routes", {"routes": items})


def route(**overrides: Any) -> dict[str, Any]:
    return {
        "prefix": "192.168.1.0/24",
        "source": "local",
        "as_path": [],
        "is_best": True,
        "is_backup": False,
    } | overrides


def test_bgp_table_replaced(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    table = [
        route(),
        route(
            prefix="192.168.2.0/24",
            source="tunnel",
            tunnel_id=to_home,
            as_path=[4200000001],
            origin_asn=4200000001,
            local_pref=100,
        ),
        route(prefix="2001:db8:2::/48", source="internal", as_path=[4200000001], is_best=False),
    ]
    assert routes(mesh, mesh.hub, table).status_code == 204
    hub_router = mesh.world.as_("reader").get(f"{API}/routers/{mesh.hub.router_id}").json()
    first_report = hub_router["routes_reported_at"]
    assert first_report is not None

    assert mesh.client.portal.call(_count_routes) == {mesh.hub.router_id: 3}  # type: ignore[union-attr]

    mesh.world.env.clock.advance(seconds=30)
    assert routes(mesh, mesh.hub, [route()]).status_code == 204
    assert mesh.client.portal.call(_count_routes) == {mesh.hub.router_id: 1}  # type: ignore[union-attr]
    hub_router = mesh.world.as_("reader").get(f"{API}/routers/{mesh.hub.router_id}").json()
    assert hub_router["routes_reported_at"] > first_report


def test_bgp_tunnel_of_another_router_refused(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    assert routes(mesh, mesh.lyon, [route()]).status_code == 204
    response = routes(mesh, mesh.lyon, [route(source="tunnel", tunnel_id=to_home)])
    assert (response.status_code, response.json()["code"]) == (404, "tunnel_not_found")
    # The refused report changed nothing.
    assert mesh.client.portal.call(_count_routes) == {mesh.lyon.router_id: 1}  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "overrides",
    [
        {"prefix": "192.168.1.1/24"},
        {"prefix": "2001:DB8::/32"},
        {"prefix": "nonsense"},
        {"source": "tunnel"},  # without tunnel_id
        {"as_path": [-1]},
        {"origin_asn": 4294967296},
        {"source": "static"},
        {"community": "1:2:3"},  # unknown field
    ],
)
def test_bgp_validation(mesh: Mesh, overrides: dict[str, Any]) -> None:
    assert routes(mesh, mesh.hub, [route(**overrides)]).status_code == 422


def test_bgp_tunnel_id_only_for_tunnel_routes(mesh: Mesh) -> None:
    to_home = mesh.tunnel(mesh.hub, mesh.home_conn)["id"]
    assert routes(mesh, mesh.hub, [route(tunnel_id=to_home)]).status_code == 422


def test_bgp_table_size_limit(mesh: Mesh) -> None:
    table = [route(prefix=f"10.{i // 256 % 256}.{i % 256}.0/24") for i in range(10_001)]
    assert routes(mesh, mesh.hub, table).status_code == 422


def test_empty_bgp_table(mesh: Mesh) -> None:
    assert routes(mesh, mesh.hub, []).status_code == 204


def test_geolite2_reopened_when_the_file_changes(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing file is retried, and a new version of the file is reopened."""
    opened: list[int] = []

    def fake_open(path: Any) -> FakeReader:
        opened.append(path.stat().st_mtime_ns)
        return FakeReader()

    monkeypatch.setattr(maxminddb, "open_database", lambda p: fake_open(tmp_path / "asn.mmdb"))
    geoip.open_reader.cache_clear()
    database = tmp_path / "asn.mmdb"
    assert geoip.isp_for("93.184.216.34", database) is None  # not downloaded yet
    database.write_bytes(b"v1")
    assert geoip.isp_for("93.184.216.34", database) == "Edgecast"
    assert geoip.isp_for("93.184.216.34", database) == "Edgecast"
    assert len(opened) == 1  # cached while the file is unchanged
    os.utime(database, ns=(0, database.stat().st_mtime_ns + 1_000_000_000))
    assert geoip.isp_for("93.184.216.34", database) == "Edgecast"
    assert len(opened) == 2
    geoip.open_reader.cache_clear()
