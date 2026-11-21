from datetime import timedelta

import pytest
from tortoise.exceptions import IntegrityError, ValidationError

from factories import FAKE_SECRET, digest, in_hours, make_mesh, make_user
from h42mesh.controller.models import (
    Mesh,
    MeshAccess,
    MeshAccessLevel,
    SessionStage,
    User,
    UserSession,
)

pytestmark = pytest.mark.usefixtures("db")


async def test_create_user_with_defaults() -> None:
    user = await make_user()
    loaded = await User.get(id=user.id)
    assert loaded.must_change_password is True
    assert loaded.totp_secret is None
    assert loaded.is_admin is False
    assert loaded.can_create_meshes is False
    assert loaded.failed_login_count == 0
    assert loaded.locked_until is None
    assert loaded.last_login_at is None
    assert loaded.created_at.utcoffset() == timedelta(0)


async def test_totp_secret_is_stored_as_json() -> None:
    user = await make_user(totp_secret=FAKE_SECRET)
    assert (await User.get(id=user.id)).totp_secret == FAKE_SECRET


async def test_username_unique() -> None:
    await make_user("alice")
    with pytest.raises(IntegrityError):
        await make_user("alice")


async def test_single_administrator() -> None:
    admin = await make_user("admin", is_admin=True)
    admin.can_create_meshes = True
    await admin.save()  # updating the administrator itself is allowed
    with pytest.raises(IntegrityError, match="administrator already exists"):
        await make_user("other", is_admin=True)
    bob = await make_user("bob")
    bob.is_admin = True
    with pytest.raises(IntegrityError):
        await bob.save()


async def test_mesh_access() -> None:
    user = await make_user()
    mesh = await make_mesh()
    await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.READ)
    access = await MeshAccess.get(user=user, mesh=mesh)
    assert access.level is MeshAccessLevel.READ


async def test_mesh_access_unique_per_user_and_mesh() -> None:
    user = await make_user()
    mesh = await make_mesh()
    other_mesh = await make_mesh("other")
    await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.READ)
    await MeshAccess.create(user=user, mesh=other_mesh, level=MeshAccessLevel.MANAGE)
    with pytest.raises(IntegrityError):
        await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.MANAGE)


async def test_user_session() -> None:
    user = await make_user()
    await UserSession.create(
        stage=SessionStage.AUTHENTICATED,
        user=user,
        token_hash=digest("s1"),
        expires_at=in_hours(12),
        last_seen_at=in_hours(0),
    )
    assert await user.sessions.all().count() == 1


async def test_session_token_hash_unique_and_validated() -> None:
    user = await make_user()
    await UserSession.create(
        stage=SessionStage.AUTHENTICATED,
        user=user,
        token_hash=digest("s1"),
        expires_at=in_hours(12),
        last_seen_at=in_hours(0),
    )
    with pytest.raises(IntegrityError):
        await UserSession.create(
            stage=SessionStage.AUTHENTICATED,
            user=user,
            token_hash=digest("s1"),
            expires_at=in_hours(12),
            last_seen_at=in_hours(0),
        )
    with pytest.raises(ValidationError):
        await UserSession.create(
            stage=SessionStage.AUTHENTICATED,
            user=user,
            token_hash="raw-token",
            expires_at=in_hours(12),
            last_seen_at=in_hours(0),
        )


async def test_mesh_created_by_and_name_unique() -> None:
    user = await make_user()
    mesh = await make_mesh("home42", created_by=user)
    loaded = await Mesh.get(id=mesh.id).prefetch_related("created_by")
    assert loaded.created_by is not None
    assert loaded.created_by.id == user.id
    assert (await make_mesh("orphan")).created_by_id is None
    with pytest.raises(IntegrityError):
        await make_mesh("home42")
