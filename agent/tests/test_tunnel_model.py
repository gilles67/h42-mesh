"""Interface names, TunnelSpec, keys."""

import ipaddress

import pytest
from pydantic import ValidationError

from fake_tunnel_backend import key, make_spec
from h42mesh.agent.config.names import tunnel_interface_name, tunnel_interface_prefix
from h42mesh.agent.messages import AddressFamily, TunnelSide
from h42mesh.agent.tunnels.backend import PeerEndpoint
from h42mesh.agent.tunnels.keys import generate_private_key, public_key


def test_interface_name() -> None:
    assert tunnel_interface_name(0, 0, "pari", 0, 0) == "wd0c0parir0c0"
    assert tunnel_interface_name(9, 3, "root", 1, 2) == "wd9c3rootr1c2"
    assert len(tunnel_interface_name(9, 9, "zzzz", 9, 9)) == 13
    assert tunnel_interface_prefix(0, 1) == "wd0c1"


@pytest.mark.parametrize(
    "args",
    [(10, 0, "pari", 0, 0), (0, 10, "pari", 0, 0), (0, 0, "Pari", 0, 0), (0, 0, "par", 0, 0),
     (0, 0, "pari", 10, 0), (0, 0, "pari", 0, -1)],
)  # fmt: skip
def test_invalid_interface_names(args: tuple[int, int, str, int, int]) -> None:
    with pytest.raises(ValueError):
        tunnel_interface_name(*args)


def test_side_b_needs_an_endpoint() -> None:
    with pytest.raises(ValidationError, match="at least one peer endpoint"):
        make_spec(peer_endpoints=())


def test_side_a_has_no_endpoint() -> None:
    assert make_spec(side=TunnelSide.A).peer_endpoints == ()
    endpoint = make_spec().peer_endpoints[0]
    with pytest.raises(ValidationError, match="no peer endpoint"):
        make_spec(side=TunnelSide.A, peer_endpoints=(endpoint,))


def test_one_endpoint_per_family() -> None:
    endpoint = make_spec().peer_endpoints[0]
    with pytest.raises(ValidationError, match="one peer endpoint per family"):
        make_spec(peer_endpoints=(endpoint, endpoint))


def test_tunnel_prefixes() -> None:
    with pytest.raises(ValidationError, match="/31 and a /127"):
        make_spec(local_ipv4=ipaddress.IPv4Interface("169.254.12.35/30"))


def test_name_pattern() -> None:
    with pytest.raises(ValidationError):
        make_spec(name="eth0")


def test_endpoint_family_and_text() -> None:
    v6 = PeerEndpoint(
        family=AddressFamily.IPV6, address=ipaddress.ip_address("2001:db8::1"), port=1
    )
    assert v6.text() == "[2001:db8::1]:1"
    with pytest.raises(ValidationError, match="not an ipv4"):
        PeerEndpoint(family=AddressFamily.IPV4, address=ipaddress.ip_address("2001:db8::1"), port=1)


def test_secrets_are_not_in_repr() -> None:
    spec = make_spec(private_key=key(9), preshared_key=key(8))
    assert key(9) not in repr(spec) and key(8) not in repr(spec)


def test_round_trip_through_json() -> None:
    spec = make_spec()
    assert type(spec).model_validate_json(spec.model_dump_json()) == spec


def test_wireguard_keys() -> None:
    private = generate_private_key()
    assert private != generate_private_key()
    # Known vector (RFC 7748, section 6.1, Alice).
    alice = "dwdtCnMYpX08FsFyUbJmRd9ML4frwJkqsXf7pR25LCo="
    assert public_key(alice) == "hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo="
    assert len(public_key(private)) == 44
