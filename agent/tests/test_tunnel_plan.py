"""Main process: keys, ports and wanted tunnels of each connection (pure)."""

import itertools
import uuid
from typing import Any

from fake_tunnel_backend import key
from h42mesh.agent.config import AgentConfig, ConnectionSettings, PortRange
from h42mesh.agent.messages import AddressFamily, RouterConfig, TunnelSide
from h42mesh.agent.state import TunnelState
from h42mesh.agent.tunnels.keys import public_key
from h42mesh.agent.tunnels.plan import connection_ports, plan_tunnels, router_ports
from test_messages import config_document, tunnel_document

FIBER, LTE = uuid.UUID(int=1), uuid.UUID(int=2)
T1, T2 = uuid.UUID(int=11), uuid.UUID(int=12)


def agent(**fiber: Any) -> AgentConfig:
    return AgentConfig(
        controllers=["https://vps1.test"],
        connections=[
            ConnectionSettings(uid=FIBER, interface="eth1", vrf="wan0", **fiber),
            ConnectionSettings(uid=LTE, interface="wwan0", vrf="wan1"),
        ],
    )


def connection(uid: uuid.UUID, number: int) -> dict[str, Any]:
    return {
        "id": str(uid),
        "number": number,
        "name": f"c{number}",
        "role": "active",
        "priority": None,
        "direct": "none",
        "public_ipv4": None,
        "public_ipv6": None,
    }


def config(*tunnels: dict[str, Any], router_number: int = 1) -> RouterConfig:
    document = config_document(
        connections=[connection(FIBER, 0), connection(LTE, 1)], tunnels=list(tunnels)
    )
    document["router"]["number"] = router_number
    return RouterConfig.model_validate(document)


def tunnel(tunnel_id: uuid.UUID = T1, via: uuid.UUID = FIBER, **overrides: Any) -> dict[str, Any]:
    return tunnel_document(id=str(tunnel_id), local_connection_id=str(via), **overrides)


def keys() -> Any:
    counter = itertools.count(100)
    return lambda: key(next(counter))


# --- ports -------------------------------------------------------------------


def test_router_ports() -> None:
    assert router_ports(0, 0) == range(42000, 43000)
    assert router_ports(0, 1) == range(43000, 44000)
    assert router_ports(2, 1) == range(47000, 48000)


def test_connection_ports() -> None:
    settings = ConnectionSettings(
        uid=FIBER, interface="eth1", vrf="wan0", ports=PortRange(min=43500, max=50000)
    )
    assert connection_ports(0, 1, settings) == range(43500, 44000)
    assert len(connection_ports(0, 0, settings)) == 0


# --- plan --------------------------------------------------------------------


def test_new_tunnel_gets_a_key_and_a_port() -> None:
    plan = plan_tunnels(config(tunnel()), agent(), {}, new_key=keys())
    state = plan.states[T1]
    assert (state.private_key, state.port) == (key(100), 43000)
    assert plan.changed == [T1]
    (report,) = plan.to_report
    assert (report.public_key, report.port) == (public_key(key(100)), 43000)
    (spec,) = plan.specs[FIBER]
    assert plan.specs[LTE] == []  # its instance removes what it has
    assert (spec.name, spec.side, spec.listen_port) == ("wd0c0rootr0c0", TunnelSide.B, 43000)
    assert str(spec.local_ipv4) == "169.254.12.35/31"
    assert str(spec.local_ipv6) == "fe80::a9fe:c23/127"
    assert [e.family for e in spec.peer_endpoints] == [AddressFamily.IPV6, AddressFamily.IPV4]
    assert {e.port for e in spec.peer_endpoints} == {42000}
    assert (spec.keepalive, spec.fallback_delay, spec.ipv6_retry) == (25, 30, 600)
    assert plan.numbers == {FIBER: 0, LTE: 1}


def test_ports_are_unique_on_the_router() -> None:
    plan = plan_tunnels(
        config(tunnel(T1), tunnel(T2, via=LTE)),
        agent(),
        {T1: TunnelState(tunnel_id=T1, private_key=key(1), port=43000)},
        new_key=keys(),
    )
    assert plan.states[T2].port == 43001


def test_stored_key_and_port_are_kept() -> None:
    state = TunnelState(tunnel_id=T1, private_key=key(1), port=43123)
    registered = tunnel(local_public_key=public_key(key(1)), local_port=43123)
    plan = plan_tunnels(config(registered), agent(), {T1: state})
    assert plan.to_report == []
    assert plan.states[T1].private_key == key(1)
    assert plan.states[T1].port == 43123
    assert plan.states[T1].public_key_registered and plan.states[T1].port_registered


def test_twice_the_same_changes_nothing() -> None:
    first = plan_tunnels(config(tunnel()), agent(), {}, new_key=keys())
    second = plan_tunnels(config(tunnel()), agent(), first.states)
    assert second.changed == [] and second.specs == first.specs


def test_port_range_of_the_connection() -> None:
    plan = plan_tunnels(
        config(tunnel()), agent(ports=PortRange(min=43900, max=43900)), {}, new_key=keys()
    )
    assert plan.states[T1].port == 43900
    full = plan_tunnels(
        config(tunnel(T1), tunnel(T2)),
        agent(ports=PortRange(min=43900, max=43900)),
        {},
        new_key=keys(),
    )
    assert "no free port" in full.pending[T2]


def test_obsolete_tunnels() -> None:
    old = uuid.UUID(int=99)
    plan = plan_tunnels(
        config(tunnel()),
        agent(),
        {old: TunnelState(tunnel_id=old, private_key=key(1), port=43000)},
        new_key=keys(),
    )
    assert plan.obsolete == [old]
    assert plan.states[T1].port == 43000  # the port of a removed tunnel is free again


def test_side_a() -> None:
    plan = plan_tunnels(config(tunnel(side="a")), agent(), {}, new_key=keys())
    (spec,) = plan.specs[FIBER]
    assert (spec.peer_endpoints, spec.keepalive) == ((), None)


def test_only_the_families_of_the_tunnel() -> None:
    plan = plan_tunnels(config(tunnel(families=["ipv4"])), agent(), {}, new_key=keys())
    (spec,) = plan.specs[FIBER]
    assert [e.family for e in spec.peer_endpoints] == [AddressFamily.IPV4]


def test_pending_tunnels() -> None:
    base = tunnel()
    no_key = tunnel(T1, peer={**base["peer"], "public_key": None})
    no_port = tunnel(T2, peer={**base["peer"], "port": None})
    plan = plan_tunnels(config(no_key, no_port), agent(), {}, new_key=keys())
    assert "public key" in plan.pending[T1]
    assert "address or port" in plan.pending[T2]
    assert plan.specs[FIBER] == []
    assert len(plan.to_report) == 2  # our keys are reported anyway


def test_connection_not_in_the_local_configuration() -> None:
    other = uuid.UUID(int=3)
    plan = plan_tunnels(config(tunnel(via=other)), agent(), {}, new_key=keys())
    assert "agent.toml" in plan.pending[T1]
    assert plan.states == {}
