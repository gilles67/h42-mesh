"""Applying the tunnel computation to the database."""

import base64
import random
from collections.abc import Iterator
from typing import Any

import pytest
from tortoise.exceptions import IntegrityError

from factories import key, make_connection, make_mesh, make_router, make_site
from h42mesh.controller import encryption
from h42mesh.controller.models import (
    ConnectionRole,
    DirectMode,
    Mesh,
    Router,
    Site,
    Tunnel,
    TunnelStatus,
)
from h42mesh.controller.models.validators import ipv6_network_for
from h42mesh.controller.tunnels import reconcile
from h42mesh.controller.tunnels.addresses import pair_at
from h42mesh.controller.tunnels.reconcile import TunnelAllocationError, reconcile_mesh

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture(autouse=True)
def secrets(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(encryption, "SCRYPT_N", 2**4)  # fast; real cost tested elsewhere
    encryption.configure("test passphrase")
    yield
    encryption.reset()


async def hub_and_home(mesh: Mesh) -> tuple[Site, Router, Site, Router]:
    hub = await make_site(mesh, "root", 4_200_000_000)
    home = await make_site(mesh, "pari", 4_200_000_001)
    return hub, await make_router(hub), home, await make_router(home)


async def tunnels_of(mesh: Mesh) -> list[Tunnel]:
    return await Tunnel.filter(mesh_id=mesh.id).order_by("created_at")


# --- creation ----------------------------------------------------------------


async def test_creates_tunnels() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    hub_c0 = await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    home_c0 = await make_connection(home_r0, 0)

    result = await reconcile_mesh(mesh.id)

    (tunnel,) = await tunnels_of(mesh)
    assert result.created == [tunnel.id]
    assert (tunnel.connection_a_id, tunnel.connection_b_id) == (hub_c0.id, home_c0.id)
    assert tunnel.ipv6_network == ipv6_network_for(tunnel.ipv4_network)
    assert (tunnel.public_key_a, tunnel.port_a, tunnel.public_key_b, tunnel.port_b) == (
        None,
        None,
        None,
        None,
    )


async def test_psk_is_encrypted_and_random() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    await make_connection(home_r0, 0)
    await make_connection(home_r0, 1)
    await reconcile_mesh(mesh.id)

    psks = []
    for tunnel in await tunnels_of(mesh):
        assert set(tunnel.preshared_key) == {"v", "kdf", "salt", "nonce", "ciphertext"}
        psk = encryption.decrypt_secret(tunnel.preshared_key)
        assert len(base64.b64decode(psk, validate=True)) == 32
        psks.append(psk)
    assert len(set(psks)) == 2


async def test_idempotent() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    await make_connection(home_r0, 0)
    await make_connection(home_r0, 1, role=ConnectionRole.BACKUP)
    await reconcile_mesh(mesh.id)
    before = [(t.id, t.ipv4_network, t.preshared_key) for t in await tunnels_of(mesh)]

    result = await reconcile_mesh(mesh.id)

    assert not result.changed
    assert [(t.id, t.ipv4_network, t.preshared_key) for t in await tunnels_of(mesh)] == before


async def test_empty_mesh() -> None:
    mesh = await make_mesh()
    assert not (await reconcile_mesh(mesh.id)).changed


# --- deletion ----------------------------------------------------------------


async def test_deletes_backup_to_backup() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    hub_c0 = await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    home_c0 = await make_connection(home_r0, 0, role=ConnectionRole.BACKUP)
    await reconcile_mesh(mesh.id)
    (tunnel,) = await tunnels_of(mesh)
    await TunnelStatus.create(tunnel=tunnel, router=hub_r0, reported_at=tunnel.created_at)

    hub_c0.role = ConnectionRole.BACKUP
    await hub_c0.save()
    result = await reconcile_mesh(mesh.id)

    assert result.deleted == [tunnel.id]
    assert await tunnels_of(mesh) == []
    assert await TunnelStatus.all().count() == 0
    assert home_c0.id  # untouched


async def test_deletes_when_nobody_accepts_inbound() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    hub_c0 = await make_connection(hub_r0, 0, direct=DirectMode.IPV4)
    await make_connection(home_r0, 0)
    await reconcile_mesh(mesh.id)
    assert len(await tunnels_of(mesh)) == 1

    hub_c0.direct = DirectMode.NONE
    await hub_c0.save()
    await reconcile_mesh(mesh.id)
    assert await tunnels_of(mesh) == []


# --- a and b swapped ---------------------------------------------------------


async def test_swap_when_as_order_changes() -> None:
    mesh = await make_mesh()
    hub, hub_r0, home, home_r0 = await hub_and_home(mesh)
    hub_c0 = await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    home_c0 = await make_connection(home_r0, 0, direct=DirectMode.BOTH)
    await reconcile_mesh(mesh.id)
    (tunnel,) = await tunnels_of(mesh)
    assert tunnel.connection_a_id == hub_c0.id  # lower AS
    tunnel.public_key_a, tunnel.port_a = key(1), 42000  # reported by the hub agent
    tunnel.public_key_b, tunnel.port_b = key(2), 42001  # reported by the home agent
    await tunnel.save()
    pair, psk = tunnel.ipv4_network, tunnel.preshared_key

    hub.asn = 4_200_000_009  # the home site now has the lower AS
    await hub.save()
    result = await reconcile_mesh(mesh.id)

    (swapped,) = await tunnels_of(mesh)
    assert result.swapped == [tunnel.id]
    assert swapped.id == tunnel.id
    assert (swapped.connection_a_id, swapped.connection_b_id) == (home_c0.id, hub_c0.id)
    # Each connection keeps its key and port; addresses and PSK stay.
    assert (swapped.public_key_a, swapped.port_a) == (key(2), 42001)
    assert (swapped.public_key_b, swapped.port_b) == (key(1), 42000)
    assert (swapped.ipv4_network, swapped.preshared_key) == (pair, psk)
    assert home.id


async def test_swap_when_only_the_other_side_accepts() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    hub_c0 = await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    home_c0 = await make_connection(home_r0, 0, direct=DirectMode.NONE)
    await reconcile_mesh(mesh.id)

    hub_c0.direct, home_c0.direct = DirectMode.NONE, DirectMode.IPV6
    await hub_c0.save()
    await home_c0.save()
    result = await reconcile_mesh(mesh.id)

    (tunnel,) = await tunnels_of(mesh)
    assert result.swapped == [tunnel.id]
    assert tunnel.connection_a_id == home_c0.id


# --- uniqueness of address pairs ---------------------------------------------


async def test_many_tunnels_get_distinct_pairs() -> None:
    mesh = await make_mesh()
    sites = [await make_site(mesh, f"s{i:03d}", 4_200_000_000 + i) for i in range(8)]
    for site in sites:
        router = await make_router(site)
        for number in range(2):
            await make_connection(router, number, direct=DirectMode.BOTH)
    await reconcile_mesh(mesh.id)

    tunnels = await tunnels_of(mesh)
    assert len(tunnels) == 8 * 7 // 2 * 4  # site pairs x connection pairs
    assert len({t.ipv4_network for t in tunnels}) == len(tunnels)
    assert len({t.ipv6_network for t in tunnels}) == len(tunnels)


class FixedRandom(random.Random):
    """Returns the given indexes in turn, then the last one forever."""

    def __init__(self, *indexes: int) -> None:
        super().__init__(0)
        self.indexes = list(indexes)

    def randrange(self, *args: Any, **kwargs: Any) -> int:
        return self.indexes.pop(0) if len(self.indexes) > 1 else self.indexes[0]


async def test_conflicting_pair_is_drawn_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pair taken behind our back (another controller) makes us draw again."""
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    await make_connection(home_r0, 0)
    await make_connection(home_r0, 1)
    await reconcile_mesh(mesh.id, rng=FixedRandom(7))
    (first,) = [t for t in await tunnels_of(mesh)][:1]
    assert first.ipv4_network == pair_at(7)

    # Hide the existing pairs from the in-memory list: the database must refuse.
    calls: list[str] = []
    real_create = Tunnel.create

    async def recording_create(**kwargs: Any) -> Tunnel:
        calls.append(str(kwargs["ipv4_network"]))
        return await real_create(**kwargs)

    await Tunnel.filter(mesh_id=mesh.id).exclude(id=first.id).delete()
    monkeypatch.setattr(Tunnel, "create", recording_create)
    monkeypatch.setattr(reconcile, "draw_ipv4_pair", lambda taken, rng: _draw(calls))
    await reconcile_mesh(mesh.id)

    assert calls == [pair_at(7), pair_at(8)]  # conflict, then a new draw
    assert {t.ipv4_network for t in await tunnels_of(mesh)} == {pair_at(7), pair_at(8)}


def _draw(calls: list[str]) -> str:
    return pair_at(7) if not calls else pair_at(8)


async def test_allocation_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    await make_connection(home_r0, 0)
    await make_connection(home_r0, 1)
    await reconcile_mesh(mesh.id, rng=FixedRandom(7))
    await Tunnel.filter(mesh_id=mesh.id, ipv4_network__not=pair_at(7)).delete()

    monkeypatch.setattr(reconcile, "draw_ipv4_pair", lambda taken, rng: pair_at(7))
    with pytest.raises(TunnelAllocationError):
        await reconcile_mesh(mesh.id)


async def test_same_pair_allowed_in_another_mesh() -> None:
    meshes = [await make_mesh("one"), await make_mesh("two")]
    for mesh in meshes:
        _, hub_r0, _, home_r0 = await hub_and_home(mesh)
        await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
        await make_connection(home_r0, 0)
        await reconcile_mesh(mesh.id, rng=FixedRandom(42))
    assert {t.ipv4_network for t in await Tunnel.all()} == {pair_at(42)}


async def test_database_refuses_duplicate_pair_in_mesh() -> None:
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    home_c0 = await make_connection(home_r0, 0)
    home_c1 = await make_connection(home_r0, 1)
    await reconcile_mesh(mesh.id)
    existing = await Tunnel.get(connection_b_id=home_c0.id)
    await Tunnel.filter(connection_b_id=home_c1.id).delete()
    with pytest.raises(IntegrityError):
        await Tunnel.create(
            mesh_id=mesh.id,
            connection_a_id=existing.connection_a_id,
            connection_b_id=home_c1.id,
            ipv4_network=existing.ipv4_network,
            ipv6_network=existing.ipv6_network,
            preshared_key={},
        )


async def test_tunnel_created_meanwhile_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another run created the same tunnel between our read and our insert."""
    mesh = await make_mesh()
    _, hub_r0, _, home_r0 = await hub_and_home(mesh)
    await make_connection(hub_r0, 0, direct=DirectMode.BOTH)
    await make_connection(home_r0, 0)
    real_create = Tunnel.create
    raced = False

    async def racing_create(**kwargs: Any) -> Tunnel:
        nonlocal raced
        if not raced:
            raced = True
            await real_create(
                **{
                    **kwargs,
                    "ipv4_network": pair_at(1),
                    "ipv6_network": ipv6_network_for(pair_at(1)),
                }
            )
        return await real_create(**kwargs)

    monkeypatch.setattr(Tunnel, "create", racing_create)
    result = await reconcile_mesh(mesh.id)
    assert result.created == []
    assert len(await tunnels_of(mesh)) == 1
