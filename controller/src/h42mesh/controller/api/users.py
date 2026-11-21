"""User management, administrator only; lookup by username for mesh managers."""

from uuid import UUID

from fastapi import APIRouter, Query, status
from tortoise.exceptions import IntegrityError

from h42mesh.controller.api.deps import AdminUser, CurrentUser
from h42mesh.controller.auth import passwords
from h42mesh.controller.errors import ApiError, error_responses
from h42mesh.controller.models import MeshAccess, MeshAccessLevel, User
from h42mesh.controller.schemas.users import (
    UserCreate,
    UserCreated,
    UserRead,
    UserSummary,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])
ADMIN_ERRORS = error_responses(401, 403)


def to_user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        can_create_meshes=user.can_create_meshes,
        must_change_password=user.must_change_password,
        totp_enabled=user.totp_secret is not None,
        locked_until=user.locked_until,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _username_taken() -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, "username_taken", "This username is already used")


async def _get_user(user_id: UUID) -> User:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "No such user")
    return user


# Declared before "/{user_id}", which would otherwise capture "lookup".
@router.get(
    "/lookup",
    response_model=UserSummary,
    responses=error_responses(401, 403, 404),
    summary="Find a user by exact username",
)
async def lookup_user(
    user: CurrentUser, username: str = Query(min_length=1, max_length=64)
) -> UserSummary:
    """For mesh managers, to grant an access: returns only the id and username.

    Allowed to the administrator and to users who manage at least one mesh.
    """
    if not user.is_admin and not await MeshAccess.exists(
        user_id=user.id, level=MeshAccessLevel.MANAGE
    ):
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "manage_required", "Manage access to a mesh required"
        )
    found = await User.get_or_none(username=username)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "No such user")
    return UserSummary(id=found.id, username=found.username)


@router.get("", response_model=list[UserRead], responses=ADMIN_ERRORS, summary="List users")
async def list_users(admin: AdminUser) -> list[UserRead]:
    return [to_user_read(user) for user in await User.all().order_by("username")]


@router.post(
    "",
    response_model=UserCreated,
    status_code=status.HTTP_201_CREATED,
    responses=ADMIN_ERRORS | error_responses(409),
    summary="Create a user",
)
async def create_user(body: UserCreate, admin: AdminUser) -> UserCreated:
    """The initial password is generated, returned once, and must be changed."""
    password = passwords.generate_password()
    try:
        user = await User.create(
            username=body.username,
            password_hash=passwords.hash_password(password),
            can_create_meshes=body.can_create_meshes,
        )
    except IntegrityError as exc:
        raise _username_taken() from exc
    return UserCreated(user=to_user_read(user), initial_password=password)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    responses=ADMIN_ERRORS | error_responses(404),
    summary="Read a user",
)
async def get_user(user_id: UUID, admin: AdminUser) -> UserRead:
    return to_user_read(await _get_user(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    responses=ADMIN_ERRORS | error_responses(404, 409),
    summary="Modify a user",
)
async def update_user(user_id: UUID, body: UserUpdate, admin: AdminUser) -> UserRead:
    user = await _get_user(user_id)
    if body.can_create_meshes is not None:
        if user.is_admin:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "admin_rights_fixed",
                "The administrator always has every right",
            )
        user.can_create_meshes = body.can_create_meshes
    if body.username is not None:
        user.username = body.username
    try:
        await user.save()
    except IntegrityError as exc:
        raise _username_taken() from exc
    return to_user_read(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ADMIN_ERRORS | error_responses(404, 409),
    summary="Delete a user",
)
async def delete_user(user_id: UUID, admin: AdminUser) -> None:
    """Also deletes the mesh accesses, sessions and enrollment tokens of the user."""
    user = await _get_user(user_id)
    if user.is_admin:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "admin_cannot_be_deleted",
            "The administrator cannot be deleted",
        )
    await user.delete()
