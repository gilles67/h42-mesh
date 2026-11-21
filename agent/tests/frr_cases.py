"""Typical routers whose FRR configuration is compared with tests/data/frr/."""

import ipaddress
import uuid
from typing import Any

from fake_tunnel_backend import key
from h42mesh.agent.config import AgentConfig, ConnectionSettings, InternalLink
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.state import TunnelState
from h42mesh.agent.tunnels.keys import public_key
from h42mesh.agent.tunnels.plan import TunnelPlan, plan_tunnels
from test_messages import config_document, tunnel_document

FIBER, LTE = uuid.UUID(int=1), uuid.UUID(int=2)
LINKS = ["lo", "eth0", "eth1", "wwan0", "br-lan", "docker0", "br-0123456789ab", "veth1a2b"]


def _connection(uid: uuid.UUID, number: int, role: str) -> dict[str, Any]:
    return {
        "id": str(uid),
        "number": number,
        "name": f"c{number}",
        "role": role,
        "priority": None,
        "direct": "none",
        "public_ipv4": None,
        "public_ipv6": None,
    }


def _six(v4: ipaddress.IPv4Address) -> str:
    """Link-local pair of a tunnel: fe80::a9fe: and the last two bytes."""
    return f"fe80::a9fe:{int(v4) & 0xFFFF:x}"


def _tunnel(number: int, via: uuid.UUID, role: str, nickname: str, asn: int) -> dict[str, Any]:
    network = ipaddress.IPv4Network(f"169.254.{10 + number}.0/31")
    a, b = network[0], network[1]
    base = tunnel_document()
    return tunnel_document(
        id=str(uuid.UUID(int=100 + number)),
        side="b",
        role=role,
        local_connection_id=str(via),
        ipv4_network=str(network),
        ipv6_network=f"{_six(a)}/127",
        local_ipv4=str(b),
        local_ipv6=_six(b),
        peer_ipv4=str(a),
        peer_ipv6=_six(a),
        local_public_key=None,
        local_port=None,
        peer={
            **base["peer"],
            "connection_id": str(uuid.UUID(int=200 + number)),
            "site_nickname": nickname,
            "site_asn": asn,
        },
    )


def _case(
    tunnels: list[dict[str, Any]], internal: bool = False, router: int = 0
) -> tuple[RouterConfig, AgentConfig, TunnelPlan]:
    document = config_document(
        connections=[_connection(FIBER, 0, "active"), _connection(LTE, 1, "backup")],
        tunnels=tunnels,
    )
    document["site"]["asn"] = 4200000001
    document["router"]["number"] = router
    config = RouterConfig.model_validate(document)
    agent = AgentConfig(
        controllers=["https://vps1.test"],
        internal_link=InternalLink(
            interface="br-lan", peer_link_local=ipaddress.IPv6Address("fe80::1a2b:3cff:fe4d:5e6f")
        )
        if internal
        else None,
        connections=[
            ConnectionSettings(uid=FIBER, interface="eth1", vrf="wan0"),
            ConnectionSettings(uid=LTE, interface="wwan0", vrf="wan1"),
        ],
    )
    states = {
        uuid.UUID(t["id"]): TunnelState(
            tunnel_id=uuid.UUID(t["id"]), private_key=key(50 + i), port=42000 + i
        )
        for i, t in enumerate(tunnels)
    }
    assert public_key(key(50))  # the keys are valid
    return config, agent, plan_tunnels(config, agent, states)


def active_tunnel() -> tuple[RouterConfig, AgentConfig, TunnelPlan]:
    """One active tunnel to the hub."""
    return _case([_tunnel(0, FIBER, "active", "root", 4200000000)])


def backup_tunnel() -> tuple[RouterConfig, AgentConfig, TunnelPlan]:
    """One active and one backup tunnel to the hub."""
    return _case(
        [
            _tunnel(0, FIBER, "active", "root", 4200000000),
            _tunnel(1, LTE, "backup", "root", 4200000000),
        ]
    )


def two_routers() -> tuple[RouterConfig, AgentConfig, TunnelPlan]:
    """Router r1 of a two-router site: one active tunnel and the internal link."""
    return _case([_tunnel(0, FIBER, "active", "pari", 4200000002)], internal=True, router=1)


CASES = {"active_tunnel": active_tunnel, "backup_tunnel": backup_tunnel, "two_routers": two_routers}
