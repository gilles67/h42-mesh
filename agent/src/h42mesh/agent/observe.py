"""What the main process observes: state for ``status``, reports for the controller.

Pure functions: the main loop gathers the data (instances, FRR, stored
configuration) and these functions shape it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from h42mesh.agent.config import AgentConfig
from h42mesh.agent.messages import RouterConfig, TunnelStatusReport
from h42mesh.agent.routing.bgp import ESTABLISHED, RouteContext
from h42mesh.agent.state import StoredConfig
from h42mesh.agent.status_file import (
    AgentStatus,
    ConfigStatus,
    ConnectionStatus,
    ControllerStatus,
    IdentityStatus,
    InternalLinkStatus,
    TunnelStatusEntry,
)
from h42mesh.agent.tunnels.backend import TunnelStatus
from h42mesh.agent.tunnels.plan import TunnelPlan


@dataclass
class ControllerContact:
    """Last exchanges with the controller (for status)."""

    last_success_at: datetime | None = None
    controller: str | None = None
    via_connection: UUID | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None

    def succeeded(self, now: datetime, controller: str, via: UUID) -> None:
        self.last_success_at, self.controller, self.via_connection = now, controller, via

    def failed(self, now: datetime, error: str) -> None:
        self.last_error, self.last_error_at = error, now


def _by_tunnel(statuses: Mapping[UUID, list[TunnelStatus]]) -> dict[UUID, TunnelStatus]:
    return {s.tunnel_id: s for found in statuses.values() for s in found if s.tunnel_id}


def bgp_state(states: Mapping[str, str], address: object, interface: str | None) -> str | None:
    return states.get(str(address)) or (states.get(interface) if interface else None)


def tunnel_reports(
    config: RouterConfig,
    plan: TunnelPlan | None,
    statuses: Mapping[UUID, list[TunnelStatus]],
    bgp_states: Mapping[str, str],
) -> list[TunnelStatusReport]:
    """Full snapshot: every tunnel of the router, down ones included."""
    observed = _by_tunnel(statuses)
    names = _names(plan)
    reports = []
    for tunnel in sorted(config.tunnels, key=lambda t: str(t.id)):
        status = observed.get(tunnel.id)
        state = bgp_state(bgp_states, tunnel.peer_ipv6, names.get(tunnel.id))
        reports.append(
            TunnelStatusReport(
                tunnel_id=tunnel.id,
                family_in_use=status.family_in_use if status else None,
                last_handshake_at=status.last_handshake_at if status else None,
                bgp_established=state == ESTABLISHED,
            )
        )
    return reports


def _names(plan: TunnelPlan | None) -> dict[UUID, str]:
    if plan is None:
        return {}
    return {s.tunnel_id: s.name for specs in plan.specs.values() for s in specs}


def route_context(
    config: RouterConfig, plan: TunnelPlan | None, agent: AgentConfig
) -> RouteContext:
    names = _names(plan)
    context = RouteContext(
        tunnel_by_peer={str(t.peer_ipv6): t.id for t in config.tunnels},
        tunnel_by_interface={name: tunnel_id for tunnel_id, name in names.items()},
    )
    if agent.internal_link is not None:
        context.internal_peers = {
            str(agent.internal_link.peer_link_local),
            agent.internal_link.interface,
        }
    return context


def build_status(
    *,
    now: datetime,
    started_at: datetime,
    pid: int,
    router_id: UUID | None,
    stored: StoredConfig | None,
    agent: AgentConfig,
    plan: TunnelPlan | None,
    connected: set[UUID],
    vrf_exists: Callable[[str], bool],
    statuses: Mapping[UUID, list[TunnelStatus]],
    bgp_states: Mapping[str, str],
    contact: ControllerContact,
    errors: list[str],
) -> AgentStatus:
    config = stored.config if stored is not None else None
    identity = None
    if router_id is not None:
        identity = IdentityStatus(router_id=router_id)
        if config is not None:
            identity = IdentityStatus(
                router_id=router_id,
                mesh_name=config.mesh.name,
                site_nickname=config.site.nickname,
                site_asn=config.site.asn,
                router_number=config.router.number,
            )
    known = {c.id: c for c in config.connections} if config else {}
    connections = []
    for settings in agent.connections:
        remote = known.get(settings.uid)
        connections.append(
            ConnectionStatus(
                uid=settings.uid,
                number=remote.number if remote else None,
                name=remote.name if remote else None,
                role=remote.role if remote else None,
                interface=settings.interface,
                vrf=settings.vrf,
                vrf_present=vrf_exists(settings.vrf),
                instance_connected=settings.uid in connected,
                public_ipv4=str(remote.public_ipv4) if remote and remote.public_ipv4 else None,
                public_ipv6=str(remote.public_ipv6) if remote and remote.public_ipv6 else None,
            )
        )
    observed = _by_tunnel(statuses)
    names = _names(plan)
    tunnels = []
    for tunnel in sorted(config.tunnels if config else [], key=lambda t: str(t.id)):
        status = observed.get(tunnel.id)
        name = names.get(tunnel.id)
        peer = tunnel.peer
        tunnels.append(
            TunnelStatusEntry(
                tunnel_id=tunnel.id,
                name=name,
                local_connection=tunnel.local_connection_id,
                remote=f"{peer.site_nickname} r{peer.router_number} c{peer.connection_number}",
                side=tunnel.side,
                role=tunnel.role,
                pending=plan.pending.get(tunnel.id) if plan is not None else None,
                running=status.running if status else False,
                family_in_use=status.family_in_use if status else None,
                endpoint=status.endpoint if status else None,
                last_handshake_at=status.last_handshake_at if status else None,
                bgp_state=bgp_state(bgp_states, tunnel.peer_ipv6, name),
            )
        )
    link = agent.internal_link
    first = agent.controllers[0]
    return AgentStatus(
        written_at=now,
        started_at=started_at,
        pid=pid,
        last_pass_errors=errors,
        identity=identity,
        config=ConfigStatus(
            fingerprint=stored.fingerprint,
            received_at=stored.received_at,
            controller=stored.controller,
        )
        if stored is not None
        else None,
        controller=ControllerStatus(
            last_success_at=contact.last_success_at,
            controller=contact.controller,
            first_controller=(contact.controller == first) if contact.controller else None,
            via_connection=contact.via_connection,
            last_error=contact.last_error,
            last_error_at=contact.last_error_at,
        ),
        connections=connections,
        tunnels=tunnels,
        internal_link=InternalLinkStatus(
            interface=link.interface,
            peer_link_local=str(link.peer_link_local),
            bgp_state=bgp_state(bgp_states, link.peer_link_local, link.interface),
        )
        if link is not None
        else None,
    )
