"""Mesh rights: the administrator manages everything, others need a MeshAccess.

Each dependency loads an object from its path parameter, walks up to its
mesh and checks the user's access level:
- no access: 404 (the object's existence is not revealed);
- ``read`` access where ``manage`` is needed: 403 ``manage_required``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status

from h42mesh.controller.api.deps import CurrentUser
from h42mesh.controller.errors import ApiError
from h42mesh.controller.models import (
    Connection,
    Mesh,
    MeshAccess,
    MeshAccessLevel,
    Router,
    Site,
    Tunnel,
    User,
)


def not_found(resource: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, f"{resource}_not_found", f"No such {resource}")


async def access_level(user: User, mesh_id: UUID) -> MeshAccessLevel | None:
    if user.is_admin:
        return MeshAccessLevel.MANAGE
    access = await MeshAccess.get_or_none(user_id=user.id, mesh_id=mesh_id)
    return access.level if access is not None else None


async def authorize(user: User, mesh_id: UUID, needed: MeshAccessLevel, resource: str) -> None:
    level = await access_level(user, mesh_id)
    if level is None:
        raise not_found(resource)
    if needed is MeshAccessLevel.MANAGE and level is not MeshAccessLevel.MANAGE:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "manage_required", "Manage access to the mesh required"
        )


# --- mesh --------------------------------------------------------------------


async def _mesh(mesh_id: UUID, user: User, needed: MeshAccessLevel) -> Mesh:
    mesh = await Mesh.get_or_none(id=mesh_id)
    if mesh is None:
        raise not_found("mesh")
    await authorize(user, mesh.id, needed, "mesh")
    return mesh


async def readable_mesh(mesh_id: UUID, user: CurrentUser) -> Mesh:
    return await _mesh(mesh_id, user, MeshAccessLevel.READ)


async def managed_mesh(mesh_id: UUID, user: CurrentUser) -> Mesh:
    return await _mesh(mesh_id, user, MeshAccessLevel.MANAGE)


ReadableMesh = Annotated[Mesh, Depends(readable_mesh)]
ManagedMesh = Annotated[Mesh, Depends(managed_mesh)]


# --- site --------------------------------------------------------------------


async def _site(site_id: UUID, user: User, needed: MeshAccessLevel) -> Site:
    site = await Site.get_or_none(id=site_id)
    if site is None:
        raise not_found("site")
    await authorize(user, site.mesh_id, needed, "site")
    return site


async def readable_site(site_id: UUID, user: CurrentUser) -> Site:
    return await _site(site_id, user, MeshAccessLevel.READ)


async def managed_site(site_id: UUID, user: CurrentUser) -> Site:
    return await _site(site_id, user, MeshAccessLevel.MANAGE)


ReadableSite = Annotated[Site, Depends(readable_site)]
ManagedSite = Annotated[Site, Depends(managed_site)]


# --- router ------------------------------------------------------------------


async def _router(router_id: UUID, user: User, needed: MeshAccessLevel) -> Router:
    router = await Router.get_or_none(id=router_id).select_related("site")
    if router is None:
        raise not_found("router")
    await authorize(user, router.site.mesh_id, needed, "router")
    return router


async def readable_router(router_id: UUID, user: CurrentUser) -> Router:
    return await _router(router_id, user, MeshAccessLevel.READ)


async def managed_router(router_id: UUID, user: CurrentUser) -> Router:
    return await _router(router_id, user, MeshAccessLevel.MANAGE)


ReadableRouter = Annotated[Router, Depends(readable_router)]
ManagedRouter = Annotated[Router, Depends(managed_router)]


# --- connection --------------------------------------------------------------


async def _connection(connection_id: UUID, user: User, needed: MeshAccessLevel) -> Connection:
    connection = await Connection.get_or_none(id=connection_id).select_related("router__site")
    if connection is None:
        raise not_found("connection")
    await authorize(user, connection.router.site.mesh_id, needed, "connection")
    return connection


async def readable_connection(connection_id: UUID, user: CurrentUser) -> Connection:
    return await _connection(connection_id, user, MeshAccessLevel.READ)


async def managed_connection(connection_id: UUID, user: CurrentUser) -> Connection:
    return await _connection(connection_id, user, MeshAccessLevel.MANAGE)


ReadableConnection = Annotated[Connection, Depends(readable_connection)]
ManagedConnection = Annotated[Connection, Depends(managed_connection)]


# --- tunnel ------------------------------------------------------------------


async def readable_tunnel(tunnel_id: UUID, user: CurrentUser) -> Tunnel:
    tunnel = await Tunnel.get_or_none(id=tunnel_id)
    if tunnel is None:
        raise not_found("tunnel")
    await authorize(user, tunnel.mesh_id, MeshAccessLevel.READ, "tunnel")
    return tunnel


ReadableTunnel = Annotated[Tunnel, Depends(readable_tunnel)]
