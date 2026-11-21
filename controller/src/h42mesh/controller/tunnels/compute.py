"""Pure computation of the tunnels a mesh needs (no database access).

Rules (docs/architecture.md, "Tunnels"):
- one candidate per pair of connections of routers of different sites;
- never backup <-> backup;
- at least one side accepts inbound connections (``direct`` is not ``none``);
- ``a`` listens: the side that accepts inbound connections; if both do, the
  connection of the site with the lower AS.
"""

from dataclasses import dataclass
from itertools import combinations
from uuid import UUID

from h42mesh.controller.models.enums import AddressFamily, ConnectionRole, DirectMode

_FAMILIES = {
    DirectMode.NONE: (),
    DirectMode.IPV4: (AddressFamily.IPV4,),
    DirectMode.IPV6: (AddressFamily.IPV6,),
    DirectMode.BOTH: (AddressFamily.IPV6, AddressFamily.IPV4),  # IPv6 first
}


@dataclass(frozen=True)
class ConnectionInfo:
    """What the computation needs to know about a connection."""

    id: UUID
    site_id: UUID
    site_asn: int
    role: ConnectionRole
    direct: DirectMode

    @property
    def accepts_inbound(self) -> bool:
        return self.direct is not DirectMode.NONE


@dataclass(frozen=True, order=True)
class DesiredTunnel:
    a_id: UUID  # listens
    b_id: UUID  # initiates

    @property
    def pair(self) -> frozenset[UUID]:
        return frozenset((self.a_id, self.b_id))


def choose_ends(
    first: ConnectionInfo, second: ConnectionInfo
) -> tuple[ConnectionInfo, ConnectionInfo] | None:
    """(a, b) for a tunnel between two connections, or None if there is none."""
    if first.site_id == second.site_id:
        return None
    if first.role is ConnectionRole.BACKUP and second.role is ConnectionRole.BACKUP:
        return None
    if first.accepts_inbound and second.accepts_inbound:
        # Sites of a mesh have distinct AS numbers (unique constraint).
        return (first, second) if first.site_asn < second.site_asn else (second, first)
    if first.accepts_inbound:
        return first, second
    if second.accepts_inbound:
        return second, first
    return None


def desired_tunnels(connections: list[ConnectionInfo]) -> list[DesiredTunnel]:
    """Tunnels a mesh needs, sorted; independent of the input order."""
    result: list[DesiredTunnel] = []
    for first, second in combinations(connections, 2):
        ends = choose_ends(first, second)
        if ends is not None:
            result.append(DesiredTunnel(a_id=ends[0].id, b_id=ends[1].id))
    return sorted(result)


def tunnel_role(a: ConnectionInfo, b: ConnectionInfo) -> ConnectionRole:
    """The weaker role of both ends: a backup connection makes a backup tunnel."""
    if ConnectionRole.BACKUP in (a.role, b.role):
        return ConnectionRole.BACKUP
    return ConnectionRole.ACTIVE


def tunnel_families(a_direct: DirectMode) -> tuple[AddressFamily, ...]:
    """Families a tunnel may use: those in which ``a`` accepts inbound, IPv6 first."""
    return _FAMILIES[a_direct]
