"""Tunnels of a mesh, read only: they are computed, never created by hand."""

from uuid import UUID

from fastapi import APIRouter, status

from h42mesh.controller.api.rights import ReadableMesh, ReadableTunnel
from h42mesh.controller.errors import ApiError, error_responses
from h42mesh.controller.models import Connection, Tunnel
from h42mesh.controller.schemas.tunnels import TunnelEnd, TunnelRead
from h42mesh.controller.tunnels.compute import tunnel_families, tunnel_role
from h42mesh.controller.tunnels.reconcile import (
    TunnelAllocationError,
    connection_info,
    reconcile_mesh,
)

router = APIRouter(tags=["tunnels"])
READ_ERRORS = error_responses(401, 403, 404)
ENDS = ("connection_a__router__site", "connection_b__router__site")


async def refresh_tunnels(mesh_id: UUID) -> None:
    """Recompute the tunnels of a mesh after an inventory change."""
    try:
        await reconcile_mesh(mesh_id)
    except TunnelAllocationError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "tunnel_allocation_failed",
            "No tunnel address pair could be allocated",
        ) from exc


def _end(connection: Connection, public_key: str | None, port: int | None) -> TunnelEnd:
    router_ = connection.router
    return TunnelEnd(
        connection_id=connection.id,
        site_id=router_.site.id,
        site_nickname=router_.site.nickname,
        router_id=router_.id,
        router_number=router_.number,
        connection_number=connection.number,
        public_key=public_key,
        port=port,
    )


def to_tunnel_read(tunnel: Tunnel) -> TunnelRead:
    """Requires both ends fetched with their router and site (``ENDS``)."""
    a, b = tunnel.connection_a, tunnel.connection_b
    return TunnelRead(
        id=tunnel.id,
        mesh_id=tunnel.mesh_id,
        a=_end(a, tunnel.public_key_a, tunnel.port_a),
        b=_end(b, tunnel.public_key_b, tunnel.port_b),
        ipv4_network=tunnel.ipv4_network,
        ipv6_network=tunnel.ipv6_network,
        role=tunnel_role(connection_info(a), connection_info(b)),
        families=list(tunnel_families(a.direct)),
        created_at=tunnel.created_at,
    )


def _sort_key(tunnel: TunnelRead) -> tuple[str, int, int, str, int, int]:
    return (
        tunnel.a.site_nickname,
        tunnel.a.router_number,
        tunnel.a.connection_number,
        tunnel.b.site_nickname,
        tunnel.b.router_number,
        tunnel.b.connection_number,
    )


@router.get(
    "/meshes/{mesh_id}/tunnels",
    response_model=list[TunnelRead],
    responses=READ_ERRORS,
    summary="List the tunnels of a mesh",
)
async def list_tunnels(mesh: ReadableMesh) -> list[TunnelRead]:
    tunnels = await Tunnel.filter(mesh_id=mesh.id).select_related(*ENDS)
    return sorted((to_tunnel_read(t) for t in tunnels), key=_sort_key)


@router.get(
    "/tunnels/{tunnel_id}",
    response_model=TunnelRead,
    responses=READ_ERRORS,
    summary="Read a tunnel",
)
async def get_tunnel(tunnel: ReadableTunnel) -> TunnelRead:
    loaded = await Tunnel.get(id=tunnel.id).select_related(*ENDS)
    return to_tunnel_read(loaded)
