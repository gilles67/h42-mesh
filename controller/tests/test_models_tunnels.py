from typing import Any

import pytest
from tortoise.exceptions import IntegrityError, ValidationError

from factories import (
    FAKE_SECRET,
    Topology,
    in_hours,
    key,
    make_connection,
    make_router,
    make_tunnel,
)
from h42mesh.controller.models import (
    AddressFamily,
    BgpRoute,
    BgpRouteSource,
    Tunnel,
    TunnelStatus,
)

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
async def topo() -> Topology:
    return await Topology.create()


# --- Tunnel ------------------------------------------------------------------


async def test_create_tunnel(topo: Topology) -> None:
    tunnel = await make_tunnel(
        topo.mesh,
        topo.conn_a,
        topo.conn_b,
        public_key_a=key(1),
        public_key_b=key(2),
        port_a=42000,
        port_b=42001,
    )
    loaded = await Tunnel.get(id=tunnel.id)
    assert loaded.ipv4_network == "169.254.12.34/31"
    assert loaded.ipv6_network == "fe80::a9fe:c22/127"
    assert loaded.preshared_key == FAKE_SECRET
    assert (loaded.port_a, loaded.port_b) == (42000, 42001)
    assert (loaded.public_key_a, loaded.public_key_b) == (key(1), key(2))


async def test_tunnel_optional_fields_default_to_none(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    loaded = await Tunnel.get(id=tunnel.id)
    assert (loaded.public_key_a, loaded.public_key_b, loaded.port_a, loaded.port_b) == (
        None,
        None,
        None,
        None,
    )


async def test_tunnel_update_keeps_checks_passing(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    tunnel.port_a = 42000
    await tunnel.save()
    assert (await Tunnel.get(id=tunnel.id)).port_a == 42000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port_a": 0},
        {"port_b": 65536},
        {"public_key_a": "short"},
        {"ipv6_network": "fe80::a9fe:c24/127"},  # not derived from the IPv4 pair
    ],
)
async def test_tunnel_rejected_values(topo: Topology, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b, **kwargs)


async def test_tunnel_pair_unique_in_both_directions(topo: Topology) -> None:
    await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b, "169.254.1.0/31")
    with pytest.raises(IntegrityError):
        await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b, "169.254.1.2/31")
    with pytest.raises(IntegrityError, match="other direction"):
        await make_tunnel(topo.mesh, topo.conn_b, topo.conn_a, "169.254.1.4/31")


async def test_tunnel_addresses_unique_within_mesh(topo: Topology) -> None:
    await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b, "169.254.1.0/31")
    other_conn = await make_connection(topo.router_b, 1)
    with pytest.raises(IntegrityError):
        await make_tunnel(topo.mesh, topo.conn_a, other_conn, "169.254.1.0/31")

    # The same pair in another mesh: allowed.
    other = await Topology.create("other")
    await make_tunnel(other.mesh, other.conn_a, other.conn_b, "169.254.1.0/31")


async def test_tunnel_rejects_same_connection(topo: Topology) -> None:
    with pytest.raises(ValidationError, match="itself"):
        await make_tunnel(topo.mesh, topo.conn_a, topo.conn_a)


async def test_tunnel_rejects_same_site(topo: Topology) -> None:
    r1 = await make_router(topo.site_a, 1)
    conn = await make_connection(r1, 0)
    with pytest.raises(ValidationError, match="different sites"):
        await make_tunnel(topo.mesh, topo.conn_a, conn)


async def test_tunnel_rejects_mesh_mismatch(topo: Topology) -> None:
    other = await Topology.create("other")
    with pytest.raises(ValidationError, match="mesh"):
        await make_tunnel(other.mesh, topo.conn_a, topo.conn_b)
    with pytest.raises(ValidationError, match="mesh"):
        await make_tunnel(topo.mesh, topo.conn_a, other.conn_b)


# --- TunnelStatus ------------------------------------------------------------


async def test_tunnel_status(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    status = await TunnelStatus.create(tunnel=tunnel, router=topo.router_b, reported_at=in_hours(0))
    loaded = await TunnelStatus.get(id=status.id)
    assert loaded.family_in_use is None
    assert loaded.bgp_established is False
    assert loaded.last_handshake_at is None

    loaded.family_in_use = AddressFamily.IPV4
    loaded.bgp_established = True
    await loaded.save()
    assert (await TunnelStatus.get(id=status.id)).family_in_use is AddressFamily.IPV4


async def test_tunnel_status_unique_per_tunnel_and_router(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    await TunnelStatus.create(tunnel=tunnel, router=topo.router_a, reported_at=in_hours(0))
    await TunnelStatus.create(tunnel=tunnel, router=topo.router_b, reported_at=in_hours(0))
    with pytest.raises(IntegrityError):
        await TunnelStatus.create(tunnel=tunnel, router=topo.router_a, reported_at=in_hours(0))


async def test_tunnel_status_router_must_be_an_end(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    stranger = await make_router(topo.site_a, 1)
    with pytest.raises(ValidationError, match="not an end"):
        await TunnelStatus.create(tunnel=tunnel, router=stranger, reported_at=in_hours(0))


# --- BgpRoute ----------------------------------------------------------------


async def test_bgp_routes(topo: Topology) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    await BgpRoute.create(
        router=topo.router_a,
        prefix="192.168.1.0/24",
        source=BgpRouteSource.LOCAL,
        as_path=[],
        is_best=True,
        is_backup=False,
    )
    learnt = await BgpRoute.create(
        router=topo.router_a,
        prefix="192.168.2.0/24",
        source=BgpRouteSource.TUNNEL,
        tunnel=tunnel,
        as_path=[4_200_000_001],
        origin_asn=4_200_000_001,
        is_best=True,
        is_backup=True,
        local_pref=50,
    )
    # Same prefix through another path: no uniqueness on (router, prefix).
    await BgpRoute.create(
        router=topo.router_a,
        prefix="192.168.2.0/24",
        source=BgpRouteSource.INTERNAL,
        as_path=[4_200_000_001],
        is_best=False,
        is_backup=False,
    )
    loaded = await BgpRoute.get(id=learnt.id)
    assert loaded.as_path == [4_200_000_001]
    assert loaded.tunnel_id == tunnel.id
    assert await topo.router_a.bgp_routes.all().count() == 3


@pytest.mark.parametrize(
    ("source", "with_tunnel"),
    [(BgpRouteSource.TUNNEL, False), (BgpRouteSource.LOCAL, True), (BgpRouteSource.INTERNAL, True)],
)
async def test_bgp_route_tunnel_iff_source_tunnel(
    topo: Topology, source: BgpRouteSource, with_tunnel: bool
) -> None:
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    with pytest.raises(ValidationError, match="tunnel is required"):
        await BgpRoute.create(
            router=topo.router_a,
            prefix="10.0.0.0/8",
            source=source,
            tunnel=tunnel if with_tunnel else None,
            as_path=[],
            is_best=True,
            is_backup=False,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prefix": "10.0.0.1/8"},
        {"as_path": [-1]},
        {"origin_asn": 4_294_967_296},
        {"local_pref": -1},
    ],
)
async def test_bgp_route_rejected_values(topo: Topology, kwargs: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "prefix": "10.0.0.0/8",
        "source": BgpRouteSource.LOCAL,
        "as_path": [],
        "is_best": True,
        "is_backup": False,
    }
    with pytest.raises(ValidationError):
        await BgpRoute.create(router=topo.router_a, **(values | kwargs))
