from typing import Any

import pytest
from tortoise.exceptions import IntegrityError, ValidationError

from factories import (
    digest,
    in_hours,
    key,
    make_connection,
    make_mesh,
    make_router,
    make_site,
    make_token,
    make_user,
)
from h42mesh.controller.models import (
    Connection,
    ConnectionRole,
    DirectMode,
    EnrollmentToken,
    Router,
    Site,
    UsedJwtId,
)

pytestmark = pytest.mark.usefixtures("db")


# --- Site --------------------------------------------------------------------


async def test_create_site() -> None:
    mesh = await make_mesh()
    site = await make_site(mesh, "root", 4_200_000_000, name="Hub Home42", location="DC 1")
    loaded = await Site.get(id=site.id)
    assert (loaded.name, loaded.nickname, loaded.asn) == ("Hub Home42", "root", 4_200_000_000)
    assert loaded.location == "DC 1"
    assert loaded.mesh_id == mesh.id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"nickname": "Paris"},
        {"nickname": "par"},
        {"asn": 4_199_999_999},
        {"asn": 4_294_967_295},
        {"location": "x" * 65},
    ],
)
async def test_site_rejected_values(kwargs: dict[str, Any]) -> None:
    mesh = await make_mesh()
    with pytest.raises(ValidationError):
        await make_site(mesh, **kwargs)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"name": "Same"}, {"name": "Same"}),
        ({"nickname": "same"}, {"nickname": "same"}),
        ({"asn": 4_200_000_042}, {"asn": 4_200_000_042}),
    ],
)
async def test_site_unique_within_mesh(first: dict[str, Any], second: dict[str, Any]) -> None:
    mesh = await make_mesh()
    other = await make_mesh("other")
    defaults_1: dict[str, Any] = {"nickname": "aaaa", "asn": 4_200_000_001, "name": "A"}
    defaults_2: dict[str, Any] = {"nickname": "bbbb", "asn": 4_200_000_002, "name": "B"}
    await Site.create(mesh=mesh, **(defaults_1 | first))
    # Same value in another mesh: allowed.
    await Site.create(mesh=other, **(defaults_2 | second))
    with pytest.raises(IntegrityError):
        await Site.create(mesh=mesh, **(defaults_2 | second))


# --- Router ------------------------------------------------------------------


async def test_create_router_with_defaults() -> None:
    site = await make_site(await make_mesh())
    router = await make_router(site, 1, signing_public_key=key(1))
    loaded = await Router.get(id=router.id)
    assert loaded.number == 1
    assert loaded.signing_public_key == key(1)
    assert loaded.signing_key_revoked is False
    assert loaded.enrolled_at is None
    assert loaded.last_seen_at is None
    assert loaded.routes_reported_at is None


@pytest.mark.parametrize("kwargs", [{"number": 2}, {"number": -1}, {"signing_public_key": "x"}])
async def test_router_rejected_values(kwargs: dict[str, Any]) -> None:
    site = await make_site(await make_mesh())
    kwargs.setdefault("number", 0)
    with pytest.raises(ValidationError):
        await make_router(site, **kwargs)


async def test_router_number_unique_per_site() -> None:
    mesh = await make_mesh()
    s1 = await make_site(mesh, "aaaa", 4_200_000_001)
    s2 = await make_site(mesh, "bbbb", 4_200_000_002)
    await make_router(s1, 0)
    await make_router(s2, 0)  # same number, other site: allowed
    with pytest.raises(IntegrityError):
        await make_router(s1, 0)


async def test_signing_public_key_unique() -> None:
    site = await make_site(await make_mesh())
    await make_router(site, 0, signing_public_key=key(1))
    await make_router(site, 1)  # several routers without a key: allowed
    with pytest.raises(IntegrityError):
        other = await make_site(await make_mesh("other"))
        await make_router(other, 0, signing_public_key=key(1))


# --- Connection --------------------------------------------------------------


async def test_create_connection_with_defaults() -> None:
    router = await make_router(await make_site(await make_mesh()))
    conn = await make_connection(router, 3, role=ConnectionRole.BACKUP)
    loaded = await Connection.get(id=conn.id)
    assert loaded.role is ConnectionRole.BACKUP
    assert loaded.direct is DirectMode.NONE
    assert loaded.priority is None
    assert loaded.public_ipv4 is None
    assert loaded.public_ipv6 is None


async def test_connection_full() -> None:
    router = await make_router(await make_site(await make_mesh()))
    conn = await make_connection(
        router,
        0,
        priority=10,
        direct=DirectMode.BOTH,
        description="Fiber",
        isp="Example ISP",
        public_ipv4="203.0.113.7",
        public_ipv4_updated_at=in_hours(0),
        public_ipv6="2001:db8::7",
        public_ipv6_updated_at=in_hours(0),
    )
    loaded = await Connection.get(id=conn.id)
    assert (loaded.public_ipv4, loaded.public_ipv6) == ("203.0.113.7", "2001:db8::7")
    assert loaded.direct is DirectMode.BOTH


@pytest.mark.parametrize(
    "kwargs",
    [
        {"number": 10},
        {"public_ipv4": "2001:db8::7"},
        {"public_ipv6": "203.0.113.7"},
        {"public_ipv6": "2001:DB8::7"},
    ],
)
async def test_connection_rejected_values(kwargs: dict[str, Any]) -> None:
    router = await make_router(await make_site(await make_mesh()))
    kwargs.setdefault("number", 0)
    with pytest.raises(ValidationError):
        await make_connection(router, **kwargs)


async def test_connection_number_unique_per_router() -> None:
    site = await make_site(await make_mesh())
    r0 = await make_router(site, 0)
    r1 = await make_router(site, 1)
    await make_connection(r0, 0)
    await make_connection(r1, 0)
    with pytest.raises(IntegrityError):
        await make_connection(r0, 0)


# --- EnrollmentToken and UsedJwtId -------------------------------------------


async def test_enrollment_token() -> None:
    user = await make_user()
    router = await make_router(await make_site(await make_mesh()))
    token = await make_token(router, user)
    loaded = await EnrollmentToken.get(id=token.id).prefetch_related("router", "created_by")
    assert loaded.router.id == router.id
    assert loaded.created_by.id == user.id
    assert loaded.used_at is None


async def test_enrollment_token_hash_unique_and_validated() -> None:
    user = await make_user()
    router = await make_router(await make_site(await make_mesh()))
    await make_token(router, user, "t1")
    with pytest.raises(IntegrityError):
        await make_token(router, user, "t1")
    with pytest.raises(ValidationError):
        await EnrollmentToken.create(
            router=router, token_hash="plain", expires_at=in_hours(1), created_by=user
        )
    assert digest("t1") == (await EnrollmentToken.get()).token_hash


async def test_used_jwt_id_unique_per_router() -> None:
    site = await make_site(await make_mesh())
    r0 = await make_router(site, 0)
    r1 = await make_router(site, 1)
    await UsedJwtId.create(router=r0, jti="abc", expires_at=in_hours(0.1))
    await UsedJwtId.create(router=r1, jti="abc", expires_at=in_hours(0.1))
    with pytest.raises(IntegrityError):
        await UsedJwtId.create(router=r0, jti="abc", expires_at=in_hours(0.1))
