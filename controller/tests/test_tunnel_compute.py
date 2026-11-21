"""Pure tunnel computation: no database."""

import itertools
import random
import uuid
from uuid import UUID

import pytest

from h42mesh.controller.models import AddressFamily, ConnectionRole, DirectMode
from h42mesh.controller.tunnels.compute import (
    ConnectionInfo,
    DesiredTunnel,
    choose_ends,
    desired_tunnels,
    tunnel_families,
    tunnel_role,
)

ACTIVE, BACKUP = ConnectionRole.ACTIVE, ConnectionRole.BACKUP
NONE, V4, V6, BOTH = DirectMode.NONE, DirectMode.IPV4, DirectMode.IPV6, DirectMode.BOTH

SITE_LOW = uuid.UUID(int=1)  # AS 4200000001
SITE_HIGH = uuid.UUID(int=2)  # AS 4200000002
ASN = {SITE_LOW: 4_200_000_001, SITE_HIGH: 4_200_000_002}
_ids = itertools.count(100)


def conn(
    site: UUID = SITE_LOW, role: ConnectionRole = ACTIVE, direct: DirectMode = NONE
) -> ConnectionInfo:
    return ConnectionInfo(
        id=uuid.UUID(int=next(_ids)),
        site_id=site,
        site_asn=ASN.get(site, 4_200_000_000 + site.int),
        role=role,
        direct=direct,
    )


# --- the full grid: 4 role combinations x 16 direct combinations -------------

ROLE_PAIRS = [(ACTIVE, ACTIVE), (ACTIVE, BACKUP), (BACKUP, ACTIVE), (BACKUP, BACKUP)]
DIRECTS = [NONE, V4, V6, BOTH]


@pytest.mark.parametrize(("role_low", "role_high"), ROLE_PAIRS)
@pytest.mark.parametrize("direct_low", DIRECTS)
@pytest.mark.parametrize("direct_high", DIRECTS)
def test_grid(
    role_low: ConnectionRole,
    role_high: ConnectionRole,
    direct_low: DirectMode,
    direct_high: DirectMode,
) -> None:
    low = conn(SITE_LOW, role_low, direct_low)  # site with the lower AS
    high = conn(SITE_HIGH, role_high, direct_high)
    tunnels = desired_tunnels([low, high])

    both_backup = role_low is BACKUP and role_high is BACKUP
    nobody_accepts = direct_low is NONE and direct_high is NONE
    if both_backup or nobody_accepts:
        assert tunnels == []
        return

    (tunnel,) = tunnels
    if direct_high is NONE:
        assert tunnel == DesiredTunnel(a_id=low.id, b_id=high.id)  # only low accepts
    elif direct_low is NONE:
        assert tunnel == DesiredTunnel(a_id=high.id, b_id=low.id)  # only high accepts
    else:
        assert tunnel == DesiredTunnel(a_id=low.id, b_id=high.id)  # both: lower AS


# --- explicit cases ----------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((ACTIVE, ACTIVE), True),
        ((ACTIVE, BACKUP), True),
        ((BACKUP, ACTIVE), True),
        ((BACKUP, BACKUP), False),
    ],
)
def test_role_combinations(roles: tuple[ConnectionRole, ConnectionRole], expected: bool) -> None:
    first = conn(SITE_LOW, roles[0], BOTH)
    second = conn(SITE_HIGH, roles[1], BOTH)
    assert bool(desired_tunnels([first, second])) is expected


@pytest.mark.parametrize("direct", [V4, V6, BOTH])
def test_one_accepting_side_is_enough(direct: DirectMode) -> None:
    listener = conn(SITE_HIGH, direct=direct)
    initiator = conn(SITE_LOW, direct=NONE)  # behind CGNAT, lower AS
    assert desired_tunnels([initiator, listener]) == [
        DesiredTunnel(a_id=listener.id, b_id=initiator.id)
    ]


def test_no_tunnel_without_accepting_side() -> None:
    assert desired_tunnels([conn(SITE_LOW), conn(SITE_HIGH)]) == []


@pytest.mark.parametrize(
    ("direct_low", "direct_high"), [(V4, V6), (V6, V4), (BOTH, V4), (V4, BOTH)]
)
def test_both_accept_in_any_family_lower_as_is_a(
    direct_low: DirectMode, direct_high: DirectMode
) -> None:
    low = conn(SITE_LOW, direct=direct_low)
    high = conn(SITE_HIGH, direct=direct_high)
    for order in ([low, high], [high, low]):
        assert desired_tunnels(order) == [DesiredTunnel(a_id=low.id, b_id=high.id)]


def test_choose_ends_is_symmetric() -> None:
    low = conn(SITE_LOW, direct=BOTH)
    high = conn(SITE_HIGH, direct=V6)
    assert choose_ends(low, high) == choose_ends(high, low) == (low, high)


def test_backup_initiator_to_active_listener() -> None:
    hub = conn(SITE_LOW, ACTIVE, BOTH)
    lte = conn(SITE_HIGH, BACKUP, NONE)
    assert desired_tunnels([lte, hub]) == [DesiredTunnel(a_id=hub.id, b_id=lte.id)]


# --- sites, routers, connections ---------------------------------------------


def test_never_within_a_site() -> None:
    """Two connections of a site (same router or both routers): no tunnel."""
    site = uuid.UUID(int=7)
    r0_c0 = conn(site, direct=BOTH)
    r0_c1 = conn(site, direct=BOTH)
    r1_c0 = conn(site, direct=BOTH)
    assert desired_tunnels([r0_c0, r0_c1, r1_c0]) == []


def test_one_tunnel_per_connection_pair() -> None:
    """Two routers with two connections each: up to four tunnels."""
    home = [conn(SITE_HIGH, ACTIVE, NONE), conn(SITE_HIGH, BACKUP, NONE)]
    hub = [conn(SITE_LOW, ACTIVE, BOTH), conn(SITE_LOW, ACTIVE, V4)]
    tunnels = desired_tunnels(home + hub)
    assert len(tunnels) == 4
    assert {t.a_id for t in tunnels} == {c.id for c in hub}
    assert {t.b_id for t in tunnels} == {c.id for c in home}


def test_three_sites() -> None:
    hub = conn(uuid.UUID(int=10), ACTIVE, BOTH)
    paris = [conn(uuid.UUID(int=11), ACTIVE, V6), conn(uuid.UUID(int=11), BACKUP, NONE)]
    lyon = [conn(uuid.UUID(int=12), ACTIVE, NONE), conn(uuid.UUID(int=12), BACKUP, NONE)]
    tunnels = desired_tunnels([hub, *paris, *lyon])
    pairs = {t.pair for t in tunnels}
    assert pairs == {
        frozenset((hub.id, paris[0].id)),
        frozenset((hub.id, paris[1].id)),
        frozenset((hub.id, lyon[0].id)),
        frozenset((hub.id, lyon[1].id)),
        frozenset((paris[0].id, lyon[0].id)),  # Paris fibre accepts IPv6
        frozenset((paris[0].id, lyon[1].id)),  # backup <-> active is allowed
        # paris backup <-> lyon: neither accepts or backup <-> backup: none
    }
    # hub has the lowest AS and accepts: always a.
    assert all(t.a_id == hub.id for t in tunnels if hub.id in t.pair)


def test_empty_and_single() -> None:
    assert desired_tunnels([]) == []
    assert desired_tunnels([conn(direct=BOTH)]) == []


def test_independent_of_input_order() -> None:
    connections = [
        conn(uuid.UUID(int=20 + i % 4), ACTIVE if i % 3 else BACKUP, DIRECTS[i % 4])
        for i in range(12)
    ]
    expected = desired_tunnels(connections)
    assert expected  # non-trivial input
    shuffler = random.Random(42)
    for _ in range(10):
        shuffled = connections[:]
        shuffler.shuffle(shuffled)
        assert desired_tunnels(shuffled) == expected


def test_no_duplicate_pairs() -> None:
    connections = [conn(uuid.UUID(int=30 + i % 3), ACTIVE, BOTH) for i in range(9)]
    tunnels = desired_tunnels(connections)
    assert len({t.pair for t in tunnels}) == len(tunnels) == 27  # 3 x 3 x 3 cross-site pairs


# --- role and families -------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "expected"),
    [((ACTIVE, ACTIVE), ACTIVE), ((ACTIVE, BACKUP), BACKUP), ((BACKUP, ACTIVE), BACKUP)],
)
def test_tunnel_role(
    roles: tuple[ConnectionRole, ConnectionRole], expected: ConnectionRole
) -> None:
    assert tunnel_role(conn(role=roles[0]), conn(role=roles[1])) is expected


@pytest.mark.parametrize(
    ("direct", "families"),
    [
        (NONE, ()),
        (V4, (AddressFamily.IPV4,)),
        (V6, (AddressFamily.IPV6,)),
        (BOTH, (AddressFamily.IPV6, AddressFamily.IPV4)),
    ],
)
def test_tunnel_families(direct: DirectMode, families: tuple[AddressFamily, ...]) -> None:
    assert tunnel_families(direct) == families
