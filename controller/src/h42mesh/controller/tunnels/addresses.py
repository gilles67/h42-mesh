"""Random tunnel address pairs and WireGuard pre-shared keys."""

import base64
import os
import random
from collections.abc import Collection

from h42mesh.controller.models.validators import ipv6_network_for

# Third octet of 169.254.x.y: 0 and 255 are reserved by RFC 3927, 169 holds the
# cloud metadata service (169.254.169.254).
THIRD_OCTETS = tuple(x for x in range(1, 255) if x != 169)
FOURTH_OCTETS = tuple(range(0, 256, 2))  # first address of a /31
PAIR_COUNT = len(THIRD_OCTETS) * len(FOURTH_OCTETS)

_system_random = random.SystemRandom()


class NoFreePairError(Exception):
    """Every address pair of the mesh is taken."""


def pair_at(index: int) -> str:
    """The index-th possible /31, in a fixed order (0 <= index < PAIR_COUNT)."""
    third, fourth = divmod(index, len(FOURTH_OCTETS))
    return f"169.254.{THIRD_OCTETS[third]}.{FOURTH_OCTETS[fourth]}/31"


def draw_ipv4_pair(taken: Collection[str], rng: random.Random | None = None) -> str:
    """A random /31 not in ``taken`` (the pairs already used in the mesh)."""
    rng = rng or _system_random
    if len(taken) >= PAIR_COUNT:
        raise NoFreePairError("no free tunnel address pair left in the mesh")
    # The mesh uses few pairs: random draws almost always succeed at once.
    for _ in range(64):
        candidate = pair_at(rng.randrange(PAIR_COUNT))
        if candidate not in taken:
            return candidate
    free = [pair_at(i) for i in range(PAIR_COUNT) if pair_at(i) not in taken]
    if not free:
        raise NoFreePairError("no free tunnel address pair left in the mesh")
    return rng.choice(free)


def tunnel_networks(ipv4_network: str) -> tuple[str, str]:
    """(ipv4_network, ipv6_network) of a tunnel."""
    return ipv4_network, ipv6_network_for(ipv4_network)


def generate_psk() -> str:
    """WireGuard pre-shared key, as ``wg genpsk``: 32 random bytes in base64."""
    return base64.b64encode(os.urandom(32)).decode()
