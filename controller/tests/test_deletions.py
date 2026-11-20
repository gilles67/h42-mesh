"""Deletion rules of docs/data-model.md: cascades and refused deletions."""

import pytest
from tortoise.exceptions import IntegrityError

from factories import (
    Topology,
    digest,
    in_hours,
    make_connection,
    make_mesh,
    make_router,
    make_site,
    make_token,
    make_tunnel,
    make_user,
)
from h42mesh.controller.models import (
    BgpRoute,
    BgpRouteSource,
    Connection,
    EnrollmentToken,
    Mesh,
    MeshAccess,
    MeshAccessLevel,
    Router,
    Site,
    Tunnel,
    TunnelStatus,
    UsedJwtId,
    User,
    UserSession,
)

pytestmark = pytest.mark.usefixtures("db")


async def populate(topo: Topology) -> Tunnel:
    """Attach every kind of router-dependent row to the topology."""
    user = await make_user("creator")
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    for router in (topo.router_a, topo.router_b):
        await TunnelStatus.create(tunnel=tunnel, router=router, reported_at=in_hours(0))
        await make_token(router, user, f"token-{router.id}")
        await UsedJwtId.create(router=router, jti="jti-1", expires_at=in_hours(0.1))
        await BgpRoute.create(
            router=router,
            prefix="10.1.0.0/16",
            source=BgpRouteSource.TUNNEL,
            tunnel=tunnel,
            as_path=[4_200_000_001],
            is_best=True,
            is_backup=False,
        )
    return tunnel


# --- refused deletions -------------------------------------------------------


async def test_mesh_deletion_refused_while_it_has_sites() -> None:
    mesh = await make_mesh()
    site = await make_site(mesh)
    with pytest.raises(IntegrityError):
        await mesh.delete()
    await site.delete()
    await mesh.delete()
    assert await Mesh.all().count() == 0


async def test_site_deletion_refused_while_it_has_routers() -> None:
    site = await make_site(await make_mesh())
    router = await make_router(site)
    with pytest.raises(IntegrityError):
        await site.delete()
    await router.delete()
    await site.delete()
    assert await Site.all().count() == 0


async def test_administrator_cannot_be_deleted() -> None:
    admin = await make_user("admin", is_admin=True)
    with pytest.raises(IntegrityError, match="administrator"):
        await admin.delete()
    assert await User.filter(id=admin.id).exists()


# --- cascades ----------------------------------------------------------------


async def test_router_deletion_cascades() -> None:
    topo = await Topology.create()
    await populate(topo)
    await make_connection(topo.router_a, 1)

    await topo.router_a.delete()

    assert await Connection.filter(router_id=topo.router_a.id).count() == 0
    assert await Tunnel.all().count() == 0
    # The other end loses its rows tied to the tunnel...
    assert await TunnelStatus.all().count() == 0
    assert await BgpRoute.all().count() == 0
    assert await EnrollmentToken.filter(router_id=topo.router_a.id).count() == 0
    assert await UsedJwtId.filter(router_id=topo.router_a.id).count() == 0
    # ... but keeps its own connection, token and JWT ids.
    assert await Connection.filter(id=topo.conn_b.id).exists()
    assert await EnrollmentToken.filter(router_id=topo.router_b.id).count() == 1
    assert await UsedJwtId.filter(router_id=topo.router_b.id).count() == 1


async def test_connection_deletion_cascades_to_tunnels() -> None:
    topo = await Topology.create()
    await populate(topo)

    await topo.conn_b.delete()

    assert await Tunnel.all().count() == 0
    assert await TunnelStatus.all().count() == 0
    assert await BgpRoute.all().count() == 0
    assert await Router.all().count() == 2
    assert await Connection.filter(id=topo.conn_a.id).exists()


async def test_tunnel_deletion_cascades_to_statuses_and_routes() -> None:
    topo = await Topology.create()
    tunnel = await populate(topo)
    await BgpRoute.create(
        router=topo.router_a,
        prefix="192.168.1.0/24",
        source=BgpRouteSource.LOCAL,
        as_path=[],
        is_best=True,
        is_backup=False,
    )

    await tunnel.delete()

    assert await TunnelStatus.all().count() == 0
    assert await BgpRoute.all().count() == 1  # the local route stays
    assert await Connection.all().count() == 2


async def test_user_deletion_cascades() -> None:
    user = await make_user()
    mesh = await make_mesh(created_by=user)
    await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.MANAGE)
    await UserSession.create(
        user=user, token_hash=digest("s"), expires_at=in_hours(1), last_seen_at=in_hours(0)
    )
    router = await make_router(await make_site(mesh))
    await make_token(router, user)

    await user.delete()

    assert await MeshAccess.all().count() == 0
    assert await UserSession.all().count() == 0
    assert await EnrollmentToken.all().count() == 0
    reloaded = await Mesh.get(id=mesh.id)
    assert reloaded.created_by_id is None
    assert await Router.all().count() == 1


async def test_mesh_deletion_removes_accesses() -> None:
    user = await make_user()
    mesh = await make_mesh()
    await MeshAccess.create(user=user, mesh=mesh, level=MeshAccessLevel.READ)
    await mesh.delete()
    assert await MeshAccess.all().count() == 0
    assert await User.all().count() == 1
