"""Static validation of the local configuration (Pydantic models)."""

import ipaddress
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from h42mesh.agent.config import AgentConfig, ConnectionSettings, InternalLink, PortRange
from h42mesh.agent.config.names import check_device_name

DATA = Path(__file__).parent / "data"
UID_0 = "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"
UID_1 = "0b9e8d7c-6a5f-4e3d-2c1b-0a9f8e7d6c5b"


def connection(**overrides: Any) -> dict[str, Any]:
    return {"uid": UID_0, "interface": "eth1", "vrf": "wan0"} | overrides


def config(**overrides: Any) -> dict[str, Any]:
    return {"controllers": ["https://vps1.example.org"]} | overrides


def invalid(model: type[Any], data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        model.model_validate(data)
    return str(info.value)


# --- valid files -------------------------------------------------------------


def test_example_of_the_specification() -> None:
    import tomllib

    parsed = AgentConfig.model_validate(tomllib.loads((DATA / "agent.toml").read_text("utf-8")))
    assert parsed.controllers == ["https://vps1.example.org", "https://vps2.example.org"]
    assert parsed.internal_link == InternalLink(
        interface="eth2", peer_link_local=ipaddress.IPv6Address("fe80::1a2b:3cff:fe4d:5e6f")
    )
    assert [c.uid for c in parsed.connections] == [UUID(UID_0), UUID(UID_1)]
    assert parsed.connections[1].interface == "wwan0"


def test_minimal_file_and_defaults() -> None:
    parsed = AgentConfig.model_validate(config())
    assert parsed.mesh_number == 0
    assert [str(a) for a in parsed.dns_servers] == [
        "1.1.1.1",
        "2606:4700:4700::1111",
        "8.8.8.8",
        "2001:4860:4860::8888",
    ]
    assert parsed.state_dir == PurePosixPath("/var/lib/h42-mesh")
    assert parsed.internal_link is None
    assert parsed.connections == []


def test_connection_defaults() -> None:
    settings = ConnectionSettings.model_validate(connection())
    assert (settings.fallback_delay, settings.ipv6_retry) == (30, 600)
    assert (settings.ports, settings.force_ipv4, settings.force_ipv6) == (None, None, None)


def test_full_file() -> None:
    parsed = AgentConfig.model_validate(
        config(
            controllers=["https://vps1.example.org", "https://vps2.example.org:8443"],
            mesh_number=9,
            dns_servers=["9.9.9.9", "2620:fe::fe"],
            state_dir="/srv/h42",
            connections=[
                connection(
                    ports={"min": 42000, "max": 42999},
                    force_ipv4="93.184.216.34",
                    force_ipv6="2a00:1450:4007:80c::200e",
                    fallback_delay=5,
                    ipv6_retry=86400,
                )
            ],
        )
    )
    (c,) = parsed.connections
    assert c.ports == PortRange(min=42000, max=42999)
    assert str(c.force_ipv4) == "93.184.216.34"
    assert parsed.controllers[1] == "https://vps2.example.org:8443"


def test_controller_urls_are_normalised() -> None:
    parsed = AgentConfig.model_validate(config(controllers=["HTTPS://VPS1.Example.org:443/"]))
    assert parsed.controllers == ["https://vps1.example.org"]


# --- unknown fields ----------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        config(mesh=0),
        config(internal_link={"interface": "eth2", "peer_link_local": "fe80::1", "vrf": "x"}),
        config(connections=[connection(fallback_delays=30)]),
        config(connections=[connection(ports={"min": 1, "max": 2, "step": 1})]),
    ],
    ids=["root", "internal_link", "connection", "ports"],
)
def test_unknown_field(data: dict[str, Any]) -> None:
    assert "Extra inputs are not permitted" in invalid(AgentConfig, data)


# --- duplicates --------------------------------------------------------------


@pytest.mark.parametrize(
    ("second", "field"),
    [
        (connection(interface="eth2", vrf="wan1"), "uid"),
        (connection(uid=UID_1, vrf="wan1"), "interface"),
        (connection(uid=UID_1, interface="eth2"), "vrf"),
    ],
)
def test_duplicate_connection_values(second: dict[str, Any], field: str) -> None:
    message = invalid(AgentConfig, config(connections=[connection(), second]))
    assert f"connections: {field}: duplicate" in message


def test_distinct_connections_accepted() -> None:
    AgentConfig.model_validate(
        config(connections=[connection(), connection(uid=UID_1, interface="eth2", vrf="wan1")])
    )


@pytest.mark.parametrize(
    "controllers",
    [
        ["https://vps1.example.org", "https://vps1.example.org"],
        ["https://vps1.example.org", "https://VPS1.example.org/"],
    ],
)
def test_duplicate_controllers(controllers: list[str]) -> None:
    assert "controllers: duplicate" in invalid(AgentConfig, config(controllers=controllers))


def test_duplicate_dns_servers() -> None:
    message = invalid(AgentConfig, config(dns_servers=["1.1.1.1", "1.1.1.1"]))
    assert "dns_servers: duplicate" in message


def test_connection_on_the_internal_link_interface() -> None:
    data = config(
        internal_link={"interface": "eth1", "peer_link_local": "fe80::1"},
        connections=[connection(interface="eth1")],
    )
    assert "is the internal link" in invalid(AgentConfig, data)


# --- bounds ------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 3])
def test_number_of_controllers(count: int) -> None:
    urls = [f"https://vps{i}.example.org" for i in range(count)]
    invalid(AgentConfig, config(controllers=urls))


@pytest.mark.parametrize(("value", "valid"), [(-1, False), (0, True), (9, True), (10, False)])
def test_mesh_number_bounds(value: int, valid: bool) -> None:
    if valid:
        AgentConfig.model_validate(config(mesh_number=value))
    else:
        invalid(AgentConfig, config(mesh_number=value))


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("fallback_delay", 4, False),
        ("fallback_delay", 5, True),
        ("fallback_delay", 3600, True),
        ("fallback_delay", 3601, False),
        ("ipv6_retry", 59, False),
        ("ipv6_retry", 60, True),
        ("ipv6_retry", 86400, True),
        ("ipv6_retry", 86401, False),
    ],
)
def test_delay_bounds(field: str, value: int, valid: bool) -> None:
    data = connection(**{field: value})
    if valid:
        ConnectionSettings.model_validate(data)
    else:
        invalid(ConnectionSettings, data)


@pytest.mark.parametrize(
    ("ports", "valid"),
    [
        ({"min": 1, "max": 65535}, True),
        ({"min": 42000, "max": 42000}, True),
        ({"min": 0, "max": 100}, False),
        ({"min": 100, "max": 65536}, False),
        ({"min": 43000, "max": 42000}, False),
        ({"min": 42000}, False),
    ],
)
def test_port_range_bounds(ports: dict[str, int], valid: bool) -> None:
    if valid:
        PortRange.model_validate(ports)
    else:
        invalid(PortRange, ports)


def test_empty_dns_list() -> None:
    invalid(AgentConfig, config(dns_servers=[]))


@pytest.mark.parametrize(("name", "valid"), [("a" * 15, True), ("a" * 16, False)])
def test_interface_name_length(name: str, valid: bool) -> None:
    if valid:
        ConnectionSettings.model_validate(connection(interface=name, vrf=name))
    else:
        invalid(ConnectionSettings, connection(interface=name))
        invalid(ConnectionSettings, connection(vrf=name))


# --- formats -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://vps1.example.org",
        "vps1.example.org",
        "https://",
        "https://vps1.example.org/api/v1",
        "https://vps1.example.org?x=1",
        "https://vps1.example.org#top",
        "https://user:secret@vps1.example.org",
        "https://vps1.example.org:99999",
    ],
)
def test_controller_url_format(url: str) -> None:
    invalid(AgentConfig, config(controllers=[url]))


@pytest.mark.parametrize("name", ["", ".", "..", "eth/0", "eth 0", "eth:0", "eth\t0"])
def test_invalid_interface_names(name: str) -> None:
    with pytest.raises(ValueError, match=r"interface name|contains|longer"):
        check_device_name(name)
    invalid(ConnectionSettings, connection(interface=name))


@pytest.mark.parametrize("vrf", ["default", "main"])
def test_default_vrf_refused(vrf: str) -> None:
    assert "default VRF" in invalid(ConnectionSettings, connection(vrf=vrf))


@pytest.mark.parametrize("address", ["fe80::1", "febf::1"])
def test_link_local_peer_accepted(address: str) -> None:
    InternalLink.model_validate({"interface": "eth2", "peer_link_local": address})


@pytest.mark.parametrize(
    "address", ["fec0::1", "2001:db8::1", "fd00::1", "fe80::1%eth2", "10.0.0.1"]
)
def test_link_local_peer_refused(address: str) -> None:
    invalid(InternalLink, {"interface": "eth2", "peer_link_local": address})


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "100.64.0.1",
        "169.254.1.1",
        "127.0.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "2a00:1450:4007:80c::200e",
    ],
)
def test_forced_ipv4_must_be_public(address: str) -> None:
    invalid(ConnectionSettings, connection(force_ipv4=address))


@pytest.mark.parametrize(
    "address",
    ["fd00::1", "fe80::1", "::1", "ff02::1", "2001:db8::1", "::", "93.184.216.34"],
)
def test_forced_ipv6_must_be_global(address: str) -> None:
    invalid(ConnectionSettings, connection(force_ipv6=address))


def test_dns_servers_must_be_addresses() -> None:
    invalid(AgentConfig, config(dns_servers=["one.one.one.one"]))


@pytest.mark.parametrize("path", ["var/lib/h42-mesh", "./state", ""])
def test_state_dir_must_be_absolute(path: str) -> None:
    invalid(AgentConfig, config(state_dir=path))


@pytest.mark.parametrize(
    "data",
    [
        config(mesh_number="0"),
        config(connections=[connection(fallback_delay="30")]),
        config(connections=[connection(ports={"min": "1", "max": 2})]),
        config(mesh_number=1.0),
        config(mesh_number=True),
    ],
)
def test_numbers_are_strict(data: dict[str, Any]) -> None:
    invalid(AgentConfig, data)


def test_uid_format() -> None:
    invalid(ConnectionSettings, connection(uid="c0"))
