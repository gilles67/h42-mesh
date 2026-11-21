"""Sites, routers and internet connections of a mesh.

Listing and creation are nested under the parent; one object is addressed
directly by its UUID. Rights come from the mesh (see ``rights.py``).
Every change that may alter the tunnels recomputes them (``refresh_tunnels``).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from tortoise.exceptions import IntegrityError
from tortoise.queryset import QuerySet

from h42mesh.controller.api.rights import (
    ManagedConnection,
    ManagedMesh,
    ManagedRouter,
    ManagedSite,
    ReadableConnection,
    ReadableMesh,
    ReadableRouter,
    ReadableSite,
)
from h42mesh.controller.api.tunnels import refresh_tunnels
from h42mesh.controller.errors import conflict, error_responses
from h42mesh.controller.models import Connection, Router, Site
from h42mesh.controller.schemas.inventory import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionUpdate,
    RouterCreate,
    RouterRead,
    RouterUpdate,
    SiteCreate,
    SiteRead,
    SiteUpdate,
)

router = APIRouter(tags=["inventory"])
READ_ERRORS = error_responses(401, 403, 404)
WRITE_ERRORS = error_responses(401, 403, 404, 409, 503)


async def _ensure_unique(queryset: QuerySet[Any], exclude_id: UUID | None, code: str) -> None:
    """Precise 409 before saving; the database constraint still guards races."""
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    if await queryset.exists():
        raise conflict(code, f"Already used ({code})")


def _race() -> Exception:
    return conflict("conflict", "The data changed meanwhile, try again")


# --- sites -------------------------------------------------------------------


def to_site_read(site: Site) -> SiteRead:
    return SiteRead(
        id=site.id,
        mesh_id=site.mesh_id,
        name=site.name,
        nickname=site.nickname,
        location=site.location,
        asn=site.asn,
        created_at=site.created_at,
    )


async def _check_site_unique(
    mesh_id: UUID, values: dict[str, Any], site_id: UUID | None = None
) -> None:
    for field, code in (("name", "site_name_taken"), ("nickname", "nickname_taken")):
        if field in values:
            await _ensure_unique(
                Site.filter(mesh_id=mesh_id, **{field: values[field]}), site_id, code
            )
    if "asn" in values:
        await _ensure_unique(Site.filter(mesh_id=mesh_id, asn=values["asn"]), site_id, "asn_taken")


@router.get(
    "/meshes/{mesh_id}/sites",
    response_model=list[SiteRead],
    responses=READ_ERRORS,
    summary="List the sites of a mesh",
)
async def list_sites(mesh: ReadableMesh) -> list[SiteRead]:
    return [to_site_read(s) for s in await Site.filter(mesh_id=mesh.id).order_by("nickname")]


@router.post(
    "/meshes/{mesh_id}/sites",
    response_model=SiteRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
    summary="Create a site",
)
async def create_site(body: SiteCreate, mesh: ManagedMesh) -> SiteRead:
    values = body.model_dump()
    await _check_site_unique(mesh.id, values)
    try:
        site = await Site.create(mesh=mesh, **values)
    except IntegrityError as exc:
        raise _race() from exc
    return to_site_read(site)


@router.get(
    "/sites/{site_id}", response_model=SiteRead, responses=READ_ERRORS, summary="Read a site"
)
async def get_site(site: ReadableSite) -> SiteRead:
    return to_site_read(site)


@router.patch(
    "/sites/{site_id}", response_model=SiteRead, responses=WRITE_ERRORS, summary="Modify a site"
)
async def update_site(body: SiteUpdate, site: ManagedSite) -> SiteRead:
    changes = body.changes()
    await _check_site_unique(site.mesh_id, changes, site.id)
    site.update_from_dict(changes)
    try:
        await site.save()
    except IntegrityError as exc:
        raise _race() from exc
    await refresh_tunnels(site.mesh_id)  # the AS may decide which end is a
    return to_site_read(site)


@router.delete(
    "/sites/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
    summary="Delete a site without routers",
)
async def delete_site(site: ManagedSite) -> None:
    """Refused while the site contains routers."""
    if await Router.filter(site_id=site.id).exists():
        raise conflict("site_not_empty", "Delete the routers of the site first")
    try:
        await site.delete()
    except IntegrityError as exc:
        raise conflict("site_not_empty", "Delete the routers of the site first") from exc


# --- routers -----------------------------------------------------------------


def to_router_read(router_: Router) -> RouterRead:
    return RouterRead(
        id=router_.id,
        site_id=router_.site_id,
        number=router_.number,
        name=router_.name,
        enrolled=router_.signing_public_key is not None,
        signing_key_revoked=router_.signing_key_revoked,
        enrolled_at=router_.enrolled_at,
        last_seen_at=router_.last_seen_at,
        routes_reported_at=router_.routes_reported_at,
        created_at=router_.created_at,
    )


@router.get(
    "/sites/{site_id}/routers",
    response_model=list[RouterRead],
    responses=READ_ERRORS,
    summary="List the routers of a site",
)
async def list_routers(site: ReadableSite) -> list[RouterRead]:
    return [to_router_read(r) for r in await Router.filter(site_id=site.id).order_by("number")]


@router.post(
    "/sites/{site_id}/routers",
    response_model=RouterRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
    summary="Declare a router",
)
async def create_router(body: RouterCreate, site: ManagedSite) -> RouterRead:
    await _ensure_unique(
        Router.filter(site_id=site.id, number=body.number), None, "router_number_taken"
    )
    try:
        router_ = await Router.create(site=site, number=body.number, name=body.name)
    except IntegrityError as exc:
        raise _race() from exc
    return to_router_read(router_)


@router.get(
    "/routers/{router_id}",
    response_model=RouterRead,
    responses=READ_ERRORS,
    summary="Read a router",
)
async def get_router(router_: ReadableRouter) -> RouterRead:
    return to_router_read(router_)


@router.patch(
    "/routers/{router_id}",
    response_model=RouterRead,
    responses=WRITE_ERRORS,
    summary="Rename a router",
)
async def update_router(body: RouterUpdate, router_: ManagedRouter) -> RouterRead:
    router_.update_from_dict(body.changes())
    await router_.save()
    return to_router_read(router_)


@router.delete(
    "/routers/{router_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
    summary="Delete a router",
)
async def delete_router(router_: ManagedRouter) -> None:
    """Also deletes its connections, tunnels, enrollment tokens, states and BGP routes."""
    await router_.delete()
    await refresh_tunnels(router_.site.mesh_id)


# --- connections -------------------------------------------------------------


def to_connection_read(connection: Connection) -> ConnectionRead:
    return ConnectionRead(
        id=connection.id,
        router_id=connection.router_id,
        number=connection.number,
        name=connection.name,
        role=connection.role,
        priority=connection.priority,
        direct=connection.direct,
        description=connection.description,
        isp=connection.isp,
        public_ipv4=connection.public_ipv4,
        public_ipv4_updated_at=connection.public_ipv4_updated_at,
        public_ipv6=connection.public_ipv6,
        public_ipv6_updated_at=connection.public_ipv6_updated_at,
        created_at=connection.created_at,
    )


@router.get(
    "/routers/{router_id}/connections",
    response_model=list[ConnectionRead],
    responses=READ_ERRORS,
    summary="List the internet connections of a router",
)
async def list_connections(router_: ReadableRouter) -> list[ConnectionRead]:
    connections = await Connection.filter(router_id=router_.id).order_by("number")
    return [to_connection_read(c) for c in connections]


@router.post(
    "/routers/{router_id}/connections",
    response_model=ConnectionRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
    summary="Declare an internet connection",
)
async def create_connection(body: ConnectionCreate, router_: ManagedRouter) -> ConnectionRead:
    await _ensure_unique(
        Connection.filter(router_id=router_.id, number=body.number),
        None,
        "connection_number_taken",
    )
    try:
        connection = await Connection.create(router=router_, **body.model_dump())
    except IntegrityError as exc:
        raise _race() from exc
    await refresh_tunnels(router_.site.mesh_id)
    return to_connection_read(connection)


@router.get(
    "/connections/{connection_id}",
    response_model=ConnectionRead,
    responses=READ_ERRORS,
    summary="Read an internet connection",
)
async def get_connection(connection: ReadableConnection) -> ConnectionRead:
    return to_connection_read(connection)


@router.patch(
    "/connections/{connection_id}",
    response_model=ConnectionRead,
    responses=WRITE_ERRORS,
    summary="Modify an internet connection",
)
async def update_connection(
    body: ConnectionUpdate, connection: ManagedConnection
) -> ConnectionRead:
    connection.update_from_dict(body.changes())
    await connection.save()
    await refresh_tunnels(connection.router.site.mesh_id)  # role or direct may change
    return to_connection_read(connection)


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
    summary="Delete an internet connection",
)
async def delete_connection(connection: ManagedConnection) -> None:
    """Also deletes its tunnels."""
    await connection.delete()
    await refresh_tunnels(connection.router.site.mesh_id)
