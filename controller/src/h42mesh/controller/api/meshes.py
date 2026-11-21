"""Meshes and per-mesh access of users."""

from uuid import UUID

from fastapi import APIRouter, status
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from h42mesh.controller.api.deps import CurrentUser
from h42mesh.controller.api.rights import ManagedMesh, ReadableMesh, access_level
from h42mesh.controller.errors import ApiError, conflict, error_responses
from h42mesh.controller.models import Mesh, MeshAccess, MeshAccessLevel, Site, User
from h42mesh.controller.schemas.meshes import (
    MeshAccessGrant,
    MeshAccessRead,
    MeshCreate,
    MeshRead,
    MeshUpdate,
)

router = APIRouter(tags=["meshes"])
READ_ERRORS = error_responses(401, 403, 404)
WRITE_ERRORS = error_responses(401, 403, 404, 409)


def to_mesh_read(mesh: Mesh, level: MeshAccessLevel) -> MeshRead:
    return MeshRead(id=mesh.id, name=mesh.name, created_at=mesh.created_at, access_level=level)


async def _check_name_free(name: str, mesh_id: UUID | None = None) -> None:
    others = Mesh.filter(name=name)
    if mesh_id is not None:
        others = others.exclude(id=mesh_id)
    if await others.exists():
        raise conflict("mesh_name_taken", "A mesh with this name already exists")


@router.get(
    "/meshes",
    response_model=list[MeshRead],
    responses=error_responses(401, 403),
    summary="List the meshes the user can access",
)
async def list_meshes(user: CurrentUser) -> list[MeshRead]:
    if user.is_admin:
        meshes = await Mesh.all().order_by("name")
        return [to_mesh_read(mesh, MeshAccessLevel.MANAGE) for mesh in meshes]
    accesses = await MeshAccess.filter(user_id=user.id).select_related("mesh")
    return sorted(
        (to_mesh_read(access.mesh, access.level) for access in accesses),
        key=lambda mesh: mesh.name,
    )


@router.post(
    "/meshes",
    response_model=MeshRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409),
    summary="Create a mesh",
)
async def create_mesh(body: MeshCreate, user: CurrentUser) -> MeshRead:
    """Administrator, or users allowed to create meshes; the creator manages it."""
    if not (user.is_admin or user.can_create_meshes):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "mesh_creation_forbidden",
            "Not allowed to create meshes",
        )
    await _check_name_free(body.name)
    try:
        async with in_transaction():
            mesh = await Mesh.create(name=body.name, created_by=user)
            if not user.is_admin:  # the administrator needs no access row
                await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.MANAGE)
    except IntegrityError as exc:
        raise conflict("mesh_name_taken", "A mesh with this name already exists") from exc
    return to_mesh_read(mesh, MeshAccessLevel.MANAGE)


@router.get(
    "/meshes/{mesh_id}", response_model=MeshRead, responses=READ_ERRORS, summary="Read a mesh"
)
async def get_mesh(mesh: ReadableMesh, user: CurrentUser) -> MeshRead:
    level = await access_level(user, mesh.id)
    assert level is not None  # noqa: S101 (checked by ReadableMesh)
    return to_mesh_read(mesh, level)


@router.patch(
    "/meshes/{mesh_id}", response_model=MeshRead, responses=WRITE_ERRORS, summary="Rename a mesh"
)
async def update_mesh(body: MeshUpdate, mesh: ManagedMesh) -> MeshRead:
    if body.name is not None:
        await _check_name_free(body.name, mesh.id)
        mesh.name = body.name
        try:
            await mesh.save()
        except IntegrityError as exc:
            raise conflict("mesh_name_taken", "A mesh with this name already exists") from exc
    return to_mesh_read(mesh, MeshAccessLevel.MANAGE)


@router.delete(
    "/meshes/{mesh_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
    summary="Delete an empty mesh",
)
async def delete_mesh(mesh: ManagedMesh) -> None:
    """Refused while the mesh contains sites; its accesses are deleted with it."""
    if await Site.filter(mesh_id=mesh.id).exists():
        raise conflict("mesh_not_empty", "Delete the sites of the mesh first")
    try:
        await mesh.delete()
    except IntegrityError as exc:  # a site was created meanwhile
        raise conflict("mesh_not_empty", "Delete the sites of the mesh first") from exc


# --- accesses ----------------------------------------------------------------


def to_access_read(access: MeshAccess) -> MeshAccessRead:
    return MeshAccessRead(user_id=access.user.id, username=access.user.username, level=access.level)


async def _target_user(user_id: UUID) -> User:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "No such user")
    return user


@router.get(
    "/meshes/{mesh_id}/accesses",
    response_model=list[MeshAccessRead],
    responses=READ_ERRORS,
    summary="List the accesses to a mesh",
)
async def list_mesh_accesses(mesh: ManagedMesh) -> list[MeshAccessRead]:
    accesses = await MeshAccess.filter(mesh_id=mesh.id).select_related("user")
    return sorted((to_access_read(a) for a in accesses), key=lambda a: a.username)


@router.put(
    "/meshes/{mesh_id}/accesses/{user_id}",
    response_model=MeshAccessRead,
    responses=WRITE_ERRORS,
    summary="Grant or change the access of a user to a mesh",
)
async def grant_mesh_access(
    user_id: UUID, body: MeshAccessGrant, mesh: ManagedMesh
) -> MeshAccessRead:
    target = await _target_user(user_id)
    if target.is_admin:
        raise conflict("user_is_admin", "The administrator already has access to every mesh")
    access = await MeshAccess.get_or_none(user_id=target.id, mesh_id=mesh.id)
    try:
        if access is None:
            access = await MeshAccess.create(user=target, mesh=mesh, level=body.level)
        else:
            access.level = body.level
            await access.save()
    except IntegrityError as exc:  # granted concurrently
        raise conflict("conflict", "The access changed meanwhile, try again") from exc
    access.user = target
    return to_access_read(access)


@router.delete(
    "/meshes/{mesh_id}/accesses/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
    summary="Remove the access of a user to a mesh",
)
async def revoke_mesh_access(user_id: UUID, mesh: ManagedMesh) -> None:
    deleted = await MeshAccess.filter(user_id=user_id, mesh_id=mesh.id).delete()
    if not deleted:
        raise ApiError(status.HTTP_404_NOT_FOUND, "access_not_found", "No such access")
