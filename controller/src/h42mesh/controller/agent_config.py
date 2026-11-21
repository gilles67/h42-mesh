"""Configuration of a router, as sent to its agent, with its fingerprint.

Only the tunnels with an end on the router are included, so a PSK is only
ever sent to the two agents of its tunnel. Lists are sorted so that the
fingerprint changes only when the configuration does.
"""

import hashlib
import ipaddress
import json

from tortoise.expressions import Q

from h42mesh.controller.encryption import decrypt_secret
from h42mesh.controller.models import AddressFamily, Connection, Mesh, Router, Tunnel
from h42mesh.controller.schemas.agent import (
    ConfigConnection,
    ConfigMesh,
    ConfigPeer,
    ConfigRouter,
    ConfigSite,
    ConfigTunnel,
    Endpoint,
    RouterConfig,
    TunnelSide,
)
from h42mesh.controller.tunnels.compute import tunnel_families, tunnel_role
from h42mesh.controller.tunnels.reconcile import connection_info

FORMAT = 1


def fingerprint(config: RouterConfig) -> str:
    """SHA-256 of the canonical JSON of the configuration, without the fingerprint."""
    payload = config.model_dump(mode="json", exclude={"fingerprint"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _pair(network: str) -> tuple[str, str]:
    """(address of a, address of b) of a /31 or /127."""
    first, second = ipaddress.ip_network(network)
    return str(first), str(second)


def _endpoints(listener: Connection) -> list[Endpoint]:
    """Public addresses of ``a`` in the families it accepts, IPv6 first."""
    addresses = {AddressFamily.IPV6: listener.public_ipv6, AddressFamily.IPV4: listener.public_ipv4}
    return [
        Endpoint(family=family, address=address)
        for family in tunnel_families(listener.direct)
        if (address := addresses[family]) is not None
    ]


def _tunnel(tunnel: Tunnel, router: Router) -> ConfigTunnel:
    a, b = tunnel.connection_a, tunnel.connection_b
    is_a = a.router.id == router.id
    local, peer = (a, b) if is_a else (b, a)
    ipv4_a, ipv4_b = _pair(tunnel.ipv4_network)
    ipv6_a, ipv6_b = _pair(tunnel.ipv6_network)
    peer_router = peer.router
    return ConfigTunnel(
        id=tunnel.id,
        side=TunnelSide.A if is_a else TunnelSide.B,
        role=tunnel_role(connection_info(a), connection_info(b)),
        families=list(tunnel_families(a.direct)),
        local_connection_id=local.id,
        ipv4_network=tunnel.ipv4_network,
        ipv6_network=tunnel.ipv6_network,
        local_ipv4=ipv4_a if is_a else ipv4_b,
        local_ipv6=ipv6_a if is_a else ipv6_b,
        peer_ipv4=ipv4_b if is_a else ipv4_a,
        peer_ipv6=ipv6_b if is_a else ipv6_a,
        local_public_key=tunnel.public_key_a if is_a else tunnel.public_key_b,
        local_port=tunnel.port_a if is_a else tunnel.port_b,
        preshared_key=decrypt_secret(tunnel.preshared_key),
        peer=ConfigPeer(
            connection_id=peer.id,
            site_nickname=peer_router.site.nickname,
            site_asn=peer_router.site.asn,
            router_number=peer_router.number,
            connection_number=peer.number,
            public_key=tunnel.public_key_b if is_a else tunnel.public_key_a,
            # b contacts a: only b needs the port and addresses of a.
            port=None if is_a else tunnel.port_a,
            endpoints=[] if is_a else _endpoints(a),
        ),
    )


async def build_router_config(router: Router) -> RouterConfig:
    """Requires ``router.site`` to be fetched."""
    site = router.site
    mesh = await Mesh.get(id=site.mesh_id)
    connections = await Connection.filter(router_id=router.id).order_by("number")
    connection_ids = [c.id for c in connections]
    tunnels = (
        await Tunnel.filter(
            Q(connection_a_id__in=connection_ids) | Q(connection_b_id__in=connection_ids)
        )
        .select_related("connection_a__router__site", "connection_b__router__site")
        .order_by("id")
        if connection_ids
        else []
    )
    config = RouterConfig(
        format=FORMAT,
        fingerprint="",
        mesh=ConfigMesh(id=mesh.id, name=mesh.name),
        site=ConfigSite(id=site.id, nickname=site.nickname, asn=site.asn),
        router=ConfigRouter(id=router.id, number=router.number, name=router.name),
        connections=[
            ConfigConnection(
                id=c.id,
                number=c.number,
                name=c.name,
                role=c.role,
                priority=c.priority,
                direct=c.direct,
                public_ipv4=c.public_ipv4,
                public_ipv6=c.public_ipv6,
            )
            for c in connections
        ],
        tunnels=[_tunnel(t, router) for t in tunnels],
    )
    return config.model_copy(update={"fingerprint": fingerprint(config)})


def etag(fingerprint_value: str) -> str:
    return f'"{fingerprint_value}"'


def matches_if_none_match(header: str | None, fingerprint_value: str) -> bool:
    """True if ``If-None-Match`` names this fingerprint (strong or weak, or ``*``)."""
    if not header:
        return False
    for candidate in header.split(","):
        value = candidate.strip()
        if value == "*":
            return True
        value = value.removeprefix("W/").strip('"')
        if value == fingerprint_value:
            return True
    return False
