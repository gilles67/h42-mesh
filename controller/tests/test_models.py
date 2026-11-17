from datetime import UTC, datetime, timedelta

import pytest
from tortoise.exceptions import IntegrityError, ValidationError

from h42mesh.controller.models import (
    ConnectionKind,
    ConnectionRole,
    EnrollmentToken,
    InternetConnection,
    Router,
    Site,
    SiteKind,
)
from h42mesh.controller.models.validators import asn_for

pytestmark = pytest.mark.usefixtures("db")


async def make_site(name: str = "home-1", number: int = 1) -> Site:
    return await Site.create(
        name=name, kind=SiteKind.HOME, number=number, asn=asn_for(SiteKind.HOME, number)
    )


async def make_router(site: Site, name: str = "r1", address: str = "10.254.0.1") -> Router:
    return await Router.create(site=site, name=name, router_id_address=address)


# --- asn_for -----------------------------------------------------------------


def test_asn_for_home_and_relay() -> None:
    assert asn_for(SiteKind.HOME, 1) == 4_200_000_001
    assert asn_for(SiteKind.HOME, 100) == 4_200_000_100
    assert asn_for(SiteKind.RELAY, 101) == 4_200_000_101
    assert asn_for(SiteKind.RELAY, 102) == 4_200_000_102


@pytest.mark.parametrize(
    ("kind", "number"),
    [(SiteKind.HOME, 0), (SiteKind.HOME, 101), (SiteKind.RELAY, 100), (SiteKind.RELAY, 1000)],
)
def test_asn_for_rejects_out_of_range(kind: SiteKind, number: int) -> None:
    with pytest.raises(ValueError, match="outside the range"):
        asn_for(kind, number)


# --- create and read back ----------------------------------------------------


async def test_create_full_inventory() -> None:
    site = await make_site()
    router = await make_router(site)
    await InternetConnection.create(
        router=router,
        name="fiber",
        role=ConnectionRole.ACTIVE,
        direct_ipv6=True,
        kind=ConnectionKind.FIBER,
    )
    await InternetConnection.create(
        router=router,
        name="4g",
        role=ConnectionRole.BACKUP,
        ipv4_port_min=51820,
        ipv4_port_max=51829,
        metered=True,
        kind=ConnectionKind.LTE,
    )
    await EnrollmentToken.create(
        router=router, token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(hours=4)
    )

    loaded = await Site.get(name="home-1").prefetch_related(
        "routers__connections", "routers__enrollment_tokens"
    )
    assert loaded.asn == 4_200_000_001
    assert loaded.kind is SiteKind.HOME
    (r,) = loaded.routers
    assert r.signing_public_key is None
    assert r.signing_key_enabled is True
    roles = {c.name: c.role for c in r.connections}
    assert roles == {"fiber": ConnectionRole.ACTIVE, "4g": ConnectionRole.BACKUP}
    assert len(r.enrollment_tokens) == 1


async def test_relay_site() -> None:
    vps = await Site.create(
        name="vps1", kind=SiteKind.RELAY, number=101, asn=asn_for(SiteKind.RELAY, 101)
    )
    assert (await Site.get(id=vps.id)).kind is SiteKind.RELAY


async def test_datetimes_are_utc_aware() -> None:
    site = await make_site()
    loaded = await Site.get(id=site.id)
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)


# --- uniqueness constraints --------------------------------------------------


async def test_site_name_unique() -> None:
    await make_site("home", 1)
    with pytest.raises(IntegrityError):
        await make_site("home", 2)


async def test_site_number_unique() -> None:
    await make_site("a", 1)
    with pytest.raises(IntegrityError):
        await make_site("b", 1)


async def test_router_name_unique_per_site() -> None:
    s1 = await make_site("a", 1)
    s2 = await make_site("b", 2)
    await make_router(s1, "r1", "10.254.0.1")
    await make_router(s2, "r1", "10.254.0.2")  # same name, other site: allowed
    with pytest.raises(IntegrityError):
        await make_router(s1, "r1", "10.254.0.3")


async def test_router_id_address_unique() -> None:
    site = await make_site()
    await make_router(site, "r1", "10.254.0.1")
    with pytest.raises(IntegrityError):
        await make_router(site, "r2", "10.254.0.1")


async def test_connection_name_unique_per_router() -> None:
    router = await make_router(await make_site())
    await InternetConnection.create(router=router, name="fiber", role=ConnectionRole.ACTIVE)
    with pytest.raises(IntegrityError):
        await InternetConnection.create(router=router, name="fiber", role=ConnectionRole.BACKUP)


async def test_token_hash_unique() -> None:
    router = await make_router(await make_site())
    expires = datetime.now(UTC) + timedelta(hours=1)
    await EnrollmentToken.create(router=router, token_hash="b" * 64, expires_at=expires)
    with pytest.raises(IntegrityError):
        await EnrollmentToken.create(router=router, token_hash="b" * 64, expires_at=expires)


# --- address validation ------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["not-an-ip", "10.253.0.1", "10.254.0.0", "10.254.0.255", "10.254.000.1", "fd00::1"],
)
async def test_router_id_address_rejected(address: str) -> None:
    site = await make_site()
    with pytest.raises(ValidationError):
        await make_router(site, "r1", address)


# --- cascading delete --------------------------------------------------------


async def test_delete_site_cascades() -> None:
    site = await make_site()
    router = await make_router(site)
    await InternetConnection.create(router=router, name="fiber", role=ConnectionRole.ACTIVE)
    await EnrollmentToken.create(
        router=router, token_hash="c" * 64, expires_at=datetime.now(UTC) + timedelta(hours=1)
    )

    await site.delete()

    assert await Router.all().count() == 0
    assert await InternetConnection.all().count() == 0
    assert await EnrollmentToken.all().count() == 0
