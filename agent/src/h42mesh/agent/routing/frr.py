"""Configuration of FRR (bgpd, bfdd), generated from the wanted state: pure functions.

- one eBGP session per tunnel, on its link-local IPv6 pair, carrying IPv4 and
  IPv6 routes (``capability extended-nexthop``, RFC 8950);
- active tunnels: fast BFD; backup tunnels: slow BGP timers, no BFD;
- routes received on a backup tunnel get the large community
  ``<AS of the site>:1:2``; any route carrying ``*:1:2`` (anywhere in its list) gets a low local
  preference, whatever the AS that set it;
- ``redistribute connected`` of the default VRF, without tunnel, loopback and
  container interfaces;
- iBGP session on the internal link of a two-router site, ``next-hop-self``.

The router-id is not set: FRR chooses it.
"""

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from jinja2 import Environment, PackageLoader, StrictUndefined

from h42mesh.agent.config import AgentConfig
from h42mesh.agent.config.names import TUNNEL_NAME_PATTERN
from h42mesh.agent.messages import ConnectionRole, RouterConfig
from h42mesh.agent.tunnels.plan import TunnelPlan

BACKUP_LOCAL_PREF = 50  # below the default of 100
BACKUP_COMMUNITY_REGEX = "_[0-9]+:1:2_"  # "_": start, end or space (FRR)
BFD_INTERVAL_MS = 300  # x 3: failure detected in less than a second
BFD_MULTIPLIER = 3
BACKUP_TIMERS = (60, 180)  # keepalive, hold time (seconds)

TUNNEL_NAME = re.compile(TUNNEL_NAME_PATTERN)
# Interfaces whose networks are never announced.

EXCLUDED_INTERFACE_PATTERNS = (
    TUNNEL_NAME,
    re.compile(r"^lo$"),
    re.compile(r"^docker\d+$"),
    re.compile(r"^podman\d+$"),
    re.compile(r"^cni-"),
    re.compile(r"^br-[0-9a-f]{12}$"),  # Docker user networks (not br-lan)
    re.compile(r"^virbr\d+$"),
    re.compile(r"^veth"),
)

ACTIVE, BACKUP, INTERNAL = "H42-ACTIVE", "H42-BACKUP", "H42-INTERNAL"


@dataclass(frozen=True)
class Neighbor:
    address: ipaddress.IPv6Address  # link-local
    interface: str
    group: str
    remote_as: int | None  # None: internal (same AS)
    description: str


@dataclass(frozen=True)
class FrrModel:
    asn: int
    neighbors: list[Neighbor] = field(default_factory=list)
    excluded_interfaces: list[str] = field(default_factory=list)

    def uses(self, group: str) -> bool:
        return any(n.group == group for n in self.neighbors)


def excluded_interfaces(links: Iterable[str], tunnels: Iterable[str]) -> list[str]:
    """Tunnels (wanted or present), loopback and container interfaces."""
    found = {"lo", *tunnels}
    found |= {n for n in links if any(p.match(n) for p in EXCLUDED_INTERFACE_PATTERNS)}
    return sorted(found)


def build_model(
    config: RouterConfig, agent: AgentConfig, plan: TunnelPlan, links: Iterable[str]
) -> FrrModel:
    """Sessions of the tunnels that have a spec (the others have no interface yet)."""
    names = {s.tunnel_id: s.name for specs in plan.specs.values() for s in specs}
    neighbors = []
    for tunnel in config.tunnels:
        name = names.get(tunnel.id)
        if name is None:
            continue
        peer = tunnel.peer
        backup = tunnel.role is ConnectionRole.BACKUP
        neighbors.append(
            Neighbor(
                address=tunnel.peer_ipv6,
                interface=name,
                group=BACKUP if backup else ACTIVE,
                remote_as=peer.site_asn,
                description=f"{peer.site_nickname} r{peer.router_number} "
                f"c{peer.connection_number} {tunnel.role}",
            )
        )
    link = agent.internal_link
    if link is not None:
        neighbors.append(
            Neighbor(
                address=link.peer_link_local,
                interface=link.interface,
                group=INTERNAL,
                remote_as=None,
                description="internal link",
            )
        )
    neighbors.sort(key=lambda n: (n.group == INTERNAL, n.interface))
    return FrrModel(
        asn=config.site.asn,
        neighbors=neighbors,
        excluded_interfaces=excluded_interfaces(links, names.values()),
    )


_environment = Environment(
    loader=PackageLoader("h42mesh.agent.routing"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 (FRR configuration, not HTML)
)


def render(model: FrrModel) -> str:
    return _environment.get_template("frr.conf.j2").render(
        model=model,
        groups={"active": ACTIVE, "backup": BACKUP, "internal": INTERNAL},
        backup_local_pref=BACKUP_LOCAL_PREF,
        backup_regex=BACKUP_COMMUNITY_REGEX,
        bfd_interval=BFD_INTERVAL_MS,
        bfd_multiplier=BFD_MULTIPLIER,
        backup_timers=BACKUP_TIMERS,
    )
