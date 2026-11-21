"""Apply the tunnel computation of a mesh to the database.

Idempotent: running it again changes nothing. There is no global transaction
(on PostgreSQL a unique violation aborts the whole transaction, which would
prevent drawing another address pair); an interrupted run is completed by the
next one. Two runs on the same mesh are serialised within a process; between
controller instances, unique constraints protect the data.
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from uuid import UUID

from tortoise.exceptions import IntegrityError

from h42mesh.controller.encryption import encrypt_secret
from h42mesh.controller.models import Connection, Tunnel
from h42mesh.controller.tunnels.addresses import (
    NoFreePairError,
    draw_ipv4_pair,
    generate_psk,
    tunnel_networks,
)
from h42mesh.controller.tunnels.compute import ConnectionInfo, DesiredTunnel, desired_tunnels

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
_locks: dict[UUID, asyncio.Lock] = {}


class TunnelAllocationError(Exception):
    """No address pair could be allocated to a new tunnel."""


@dataclass
class ReconcileResult:
    created: list[UUID] = field(default_factory=list)
    deleted: list[UUID] = field(default_factory=list)
    swapped: list[UUID] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.deleted or self.swapped)


def connection_info(connection: Connection) -> ConnectionInfo:
    """Requires ``router__site`` to be fetched."""
    site = connection.router.site
    return ConnectionInfo(
        id=connection.id,
        site_id=site.id,
        site_asn=site.asn,
        role=connection.role,
        direct=connection.direct,
    )


async def mesh_connections(mesh_id: UUID) -> list[ConnectionInfo]:
    connections = await Connection.filter(router__site__mesh_id=mesh_id).select_related(
        "router__site"
    )
    return [connection_info(c) for c in connections]


async def reconcile_mesh(mesh_id: UUID, rng: random.Random | None = None) -> ReconcileResult:
    """Create, delete and re-orient the tunnels of a mesh to match the inventory."""
    lock = _locks.setdefault(mesh_id, asyncio.Lock())
    async with lock:
        return await _reconcile(mesh_id, rng)


async def _reconcile(mesh_id: UUID, rng: random.Random | None) -> ReconcileResult:
    result = ReconcileResult()
    wanted = {d.pair: d for d in desired_tunnels(await mesh_connections(mesh_id))}
    existing = await Tunnel.filter(mesh_id=mesh_id)
    taken: set[str] = set()

    for tunnel in existing:
        desired = wanted.pop(frozenset((tunnel.connection_a_id, tunnel.connection_b_id)), None)
        if desired is None:
            await tunnel.delete()
            result.deleted.append(tunnel.id)
            continue
        taken.add(tunnel.ipv4_network)
        if desired.a_id != tunnel.connection_a_id:
            await _swap_ends(tunnel)
            result.swapped.append(tunnel.id)

    for desired in sorted(wanted.values()):
        created = await _create(mesh_id, desired, taken, rng)
        if created is not None:
            result.created.append(created.id)

    if result.changed:
        logger.info(
            "mesh %s tunnels: %d created, %d deleted, %d swapped",
            mesh_id,
            len(result.created),
            len(result.deleted),
            len(result.swapped),
        )
    return result


async def _swap_ends(tunnel: Tunnel) -> None:
    """``a`` and ``b`` exchanged: each connection keeps its own key and port.

    The address pair and the PSK stay; the new ``a`` takes the first address.
    """
    tunnel.connection_a_id, tunnel.connection_b_id = tunnel.connection_b_id, tunnel.connection_a_id
    tunnel.public_key_a, tunnel.public_key_b = tunnel.public_key_b, tunnel.public_key_a
    tunnel.port_a, tunnel.port_b = tunnel.port_b, tunnel.port_a
    await tunnel.save()


async def _pair_exists(desired: DesiredTunnel) -> bool:
    a, b = desired.a_id, desired.b_id
    return await Tunnel.filter(connection_a_id=a, connection_b_id=b).exists() or (
        await Tunnel.filter(connection_a_id=b, connection_b_id=a).exists()
    )


async def _create(
    mesh_id: UUID, desired: DesiredTunnel, taken: set[str], rng: random.Random | None
) -> Tunnel | None:
    """New tunnel with a random free address pair; None if created meanwhile."""
    preshared_key = encrypt_secret(generate_psk())
    for _ in range(MAX_ATTEMPTS):
        try:
            ipv4_network, ipv6_network = tunnel_networks(draw_ipv4_pair(taken, rng))
        except NoFreePairError as exc:
            raise TunnelAllocationError(str(exc)) from exc
        try:
            tunnel = await Tunnel.create(
                mesh_id=mesh_id,
                connection_a_id=desired.a_id,
                connection_b_id=desired.b_id,
                ipv4_network=ipv4_network,
                ipv6_network=ipv6_network,
                preshared_key=preshared_key,
            )
        except IntegrityError:
            if await _pair_exists(desired):
                return None  # another run created this tunnel
            taken.add(ipv4_network)  # address pair taken meanwhile: draw again
            continue
        taken.add(ipv4_network)
        return tunnel
    raise TunnelAllocationError(f"no free address pair after {MAX_ATTEMPTS} attempts")
