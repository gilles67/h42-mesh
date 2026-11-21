import base64
import ipaddress
import random

import pytest

from h42mesh.controller.models.validators import TunnelIPv4NetworkValidator
from h42mesh.controller.tunnels.addresses import (
    PAIR_COUNT,
    NoFreePairError,
    draw_ipv4_pair,
    generate_psk,
    pair_at,
    tunnel_networks,
)

EXCLUDED = [
    ipaddress.IPv4Network(n) for n in ("169.254.0.0/24", "169.254.169.0/24", "169.254.255.0/24")
]


def test_pair_space() -> None:
    assert PAIR_COUNT == 253 * 128
    pairs = {pair_at(i) for i in range(PAIR_COUNT)}
    assert len(pairs) == PAIR_COUNT
    for text in pairs:
        network = ipaddress.IPv4Network(text)
        assert network.prefixlen == 31
        assert not any(network.subnet_of(excluded) for excluded in EXCLUDED)
        TunnelIPv4NetworkValidator()(text)


def test_random_draws_stay_valid() -> None:
    rng = random.Random(1)
    for _ in range(5000):
        TunnelIPv4NetworkValidator()(draw_ipv4_pair((), rng))


def test_draw_avoids_taken_pairs() -> None:
    rng = random.Random(2)
    taken = {pair_at(i) for i in range(PAIR_COUNT) if i != 1234}
    assert draw_ipv4_pair(taken, rng) == pair_at(1234)  # the only free pair


def test_draw_fails_when_all_taken() -> None:
    taken = {pair_at(i) for i in range(PAIR_COUNT)}
    with pytest.raises(NoFreePairError):
        draw_ipv4_pair(taken)


def test_draws_are_spread() -> None:
    rng = random.Random(3)
    draws = {draw_ipv4_pair((), rng) for _ in range(200)}
    assert len(draws) > 190  # random, not sequential


def test_tunnel_networks() -> None:
    assert tunnel_networks("169.254.12.34/31") == ("169.254.12.34/31", "fe80::a9fe:c22/127")


def test_psk_format() -> None:
    psk = generate_psk()
    assert len(psk) == 44
    assert len(base64.b64decode(psk, validate=True)) == 32
    assert generate_psk() != psk
