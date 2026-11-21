"""Main process: wanted tunnels of each connection, from the configuration (pure).

From the configuration received from the controller, the local configuration
and the stored tunnel states, compute:

- the local state of each tunnel: X25519 key generated if missing, port chosen
  in the range of the router (kept as long as the tunnel exists);
- the keys and ports the controller does not have yet;
- the TunnelSpec of each connection (every local connection gets a list, maybe
  empty, so that its instance removes what is no longer wanted);
- the tunnels that cannot be created yet, and why.
"""

import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import ValidationError

from h42mesh.agent.config import AgentConfig, ConnectionSettings
from h42mesh.agent.config.names import tunnel_interface_name
from h42mesh.agent.messages import (
    AddressFamily,
    ConfigConnection,
    ConfigTunnel,
    RouterConfig,
    TunnelKeyReport,
    TunnelSide,
)
from h42mesh.agent.state import TunnelState
from h42mesh.agent.tunnels.backend import KEEPALIVE, PeerEndpoint, TunnelSpec
from h42mesh.agent.tunnels.keys import generate_private_key, public_key

PORT_BASE = 42000  # constant of the agent
MESH_PORT_STEP = 2000
ROUTER_PORT_STEP = 1000
PORTS_PER_ROUTER = 1000


def router_ports(mesh_number: int, router_number: int) -> range:
    """``42000 + 2000 x mesh + 1000 x router``, 1000 ports."""
    start = PORT_BASE + MESH_PORT_STEP * mesh_number + ROUTER_PORT_STEP * router_number
    return range(start, start + PORTS_PER_ROUTER)


def connection_ports(mesh_number: int, router_number: int, settings: ConnectionSettings) -> range:
    """Range of the router, intersected with the one of the connection (maybe empty)."""
    ports = router_ports(mesh_number, router_number)
    if settings.ports is None:
        return ports
    return range(max(ports.start, settings.ports.min), min(ports.stop, settings.ports.max + 1))


def free_port(candidates: range, used: set[int]) -> int | None:
    return next((port for port in candidates if port not in used), None)


@dataclass
class TunnelPlan:
    states: dict[UUID, TunnelState] = field(default_factory=dict)
    changed: list[UUID] = field(default_factory=list)  # states to store
    obsolete: list[UUID] = field(default_factory=list)  # tunnels gone: states to delete
    to_report: list[TunnelKeyReport] = field(default_factory=list)
    specs: dict[UUID, list[TunnelSpec]] = field(default_factory=dict)  # by connection UID
    numbers: dict[UUID, int] = field(default_factory=dict)  # connection UID -> number
    pending: dict[UUID, str] = field(default_factory=dict)  # tunnel id -> reason


def _endpoints(tunnel: ConfigTunnel) -> tuple[PeerEndpoint, ...]:
    """Addresses of a the tunnel may use, IPv6 first."""
    if tunnel.peer.port is None:
        return ()
    found = [
        PeerEndpoint(family=e.family, address=e.address, port=tunnel.peer.port)
        for e in tunnel.peer.endpoints
        if e.family in tunnel.families
    ]
    return tuple(sorted(found, key=lambda e: e.family is not AddressFamily.IPV6))


def _spec(
    tunnel: ConfigTunnel,
    state: TunnelState,
    local: ConfigConnection,
    settings: ConnectionSettings,
    mesh_number: int,
) -> TunnelSpec | str:
    """The spec, or why the tunnel cannot be created yet."""
    peer = tunnel.peer
    if peer.public_key is None:
        return "public key of the other end not known yet"
    endpoints = _endpoints(tunnel) if tunnel.side is TunnelSide.B else ()
    if tunnel.side is TunnelSide.B and not endpoints:
        return "address or port of the other end not known yet"
    if state.port is None:
        return "no port"
    try:
        return TunnelSpec(
            tunnel_id=tunnel.id,
            name=tunnel_interface_name(
                mesh_number,
                local.number,
                peer.site_nickname,
                peer.router_number,
                peer.connection_number,
            ),
            side=tunnel.side,
            private_key=state.private_key,
            listen_port=state.port,
            peer_public_key=peer.public_key,
            preshared_key=tunnel.preshared_key,
            local_ipv4=ipaddress.IPv4Interface(
                f"{tunnel.local_ipv4}/{tunnel.ipv4_network.prefixlen}"
            ),
            local_ipv6=ipaddress.IPv6Interface(
                f"{tunnel.local_ipv6}/{tunnel.ipv6_network.prefixlen}"
            ),
            peer_endpoints=endpoints,
            keepalive=KEEPALIVE if tunnel.side is TunnelSide.B else None,
            fallback_delay=settings.fallback_delay,
            ipv6_retry=settings.ipv6_retry,
        )
    except (ValidationError, ValueError) as exc:
        return f"invalid tunnel: {exc}"


def plan_tunnels(
    config: RouterConfig,
    agent: AgentConfig,
    states: Mapping[UUID, TunnelState],
    new_key: Callable[[], str] = generate_private_key,
) -> TunnelPlan:
    plan = TunnelPlan()
    settings_by_uid = {c.uid: c for c in agent.connections}
    connections = {c.id: c for c in config.connections}
    plan.numbers = {uid: connections[uid].number for uid in settings_by_uid if uid in connections}
    plan.specs = {uid: [] for uid in settings_by_uid}
    wanted = {t.id for t in config.tunnels}
    plan.obsolete = sorted(uid for uid in states if uid not in wanted)
    # A port is used once per router, all connections included.
    used = {s.port for uid, s in states.items() if uid in wanted and s.port is not None}

    for tunnel in sorted(config.tunnels, key=lambda t: str(t.id)):
        settings = settings_by_uid.get(tunnel.local_connection_id)
        local = connections.get(tunnel.local_connection_id)
        if settings is None or local is None:
            plan.pending[tunnel.id] = "local connection not in agent.toml"
            continue
        state = states.get(tunnel.id)
        if state is None:
            state = TunnelState(tunnel_id=tunnel.id, private_key=new_key())
        if state.port is None:
            port = free_port(
                connection_ports(agent.mesh_number, config.router.number, settings), used
            )
            if port is not None:
                used.add(port)
                state = state.model_copy(update={"port": port})
        own_key = public_key(state.private_key)
        state = state.model_copy(
            update={
                "public_key_registered": tunnel.local_public_key == own_key,
                "port_registered": state.port is not None and tunnel.local_port == state.port,
            }
        )
        if state != states.get(tunnel.id):
            plan.changed.append(tunnel.id)
        plan.states[tunnel.id] = state
        if state.port is None:
            plan.pending[tunnel.id] = "no free port in the range of the connection"
            continue
        if not (state.public_key_registered and state.port_registered):
            plan.to_report.append(
                TunnelKeyReport(tunnel_id=tunnel.id, public_key=own_key, port=state.port)
            )
        spec = _spec(tunnel, state, local, settings, agent.mesh_number)
        if isinstance(spec, str):
            plan.pending[tunnel.id] = spec
        else:
            plan.specs[settings.uid].append(spec)
    return plan
