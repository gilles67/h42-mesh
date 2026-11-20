import pytest
from tortoise.exceptions import ValidationError
from tortoise.validators import Validator

from h42mesh.controller.models.validators import (
    NICKNAME_VALIDATOR,
    SHA256_HEX_VALIDATOR,
    AsPathValidator,
    IPAddressValidator,
    NetworkValidator,
    PublicKeyValidator,
    TunnelIPv4NetworkValidator,
    TunnelIPv6NetworkValidator,
    ipv6_network_for,
)

CASES: list[tuple[Validator, list[object], list[object]]] = [
    # (validator, accepted, rejected)
    (
        NICKNAME_VALIDATOR,
        ["root", "pari", "a1b2"],
        ["Root", "par", "paris", "pa-i", "pari\n", 1234],
    ),
    (SHA256_HEX_VALIDATOR, ["0" * 64, "af" * 32], ["0" * 63, "AF" * 32, "g" * 64]),
    (
        PublicKeyValidator(),
        ["A" * 43 + "=", "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc="],
        ["A" * 44, "A" * 42 + "==", "not base64!" + "A" * 33, "AAAA"],
    ),
    (
        IPAddressValidator(4),
        ["203.0.113.7", "10.0.0.1"],
        ["2001:db8::1", "203.0.113.007", "203.0.113", "x"],
    ),
    (
        IPAddressValidator(6),
        ["2001:db8::1"],
        ["203.0.113.7", "2001:DB8::1", "2001:db8:0::1", "fe80::1%eth0"],
    ),
    (
        NetworkValidator(),
        ["192.168.1.0/24", "2001:db8::/32", "10.0.0.1/32"],
        ["192.168.1.1/24", "2001:DB8::/32", "192.168.1.0", "x"],
    ),
    (
        TunnelIPv4NetworkValidator(),
        ["169.254.12.34/31", "169.254.1.0/31", "169.254.254.254/31"],
        [
            "169.254.12.35/31",  # host bits set
            "169.254.12.34/30",
            "10.0.0.0/31",
            "169.254.0.2/31",  # 169.254.0.0/24 reserved
            "169.254.169.254/31",  # metadata service
            "169.254.255.0/31",  # reserved
        ],
    ),
    (
        TunnelIPv6NetworkValidator(),
        ["fe80::a9fe:c22/127"],
        ["fe80::a9fe:c23/127", "fe80::a9fe:c22/126", "fe80:0:0:1::/127", "2001:db8::/127"],
    ),
    (
        AsPathValidator(),
        [[], [4_200_000_001, 4_200_000_000], [0, 4_294_967_295]],
        [[True], [-1], [4_294_967_296], ["65000"], 65000, {"a": 1}],
    ),
]


@pytest.mark.parametrize(
    ("validator", "value"),
    [(v, value) for v, accepted, _ in CASES for value in accepted],
)
def test_accepted(validator: Validator, value: object) -> None:
    validator(value)


@pytest.mark.parametrize(
    ("validator", "value"),
    [(v, value) for v, _, rejected in CASES for value in rejected],
)
def test_rejected(validator: Validator, value: object) -> None:
    with pytest.raises(ValidationError):
        validator(value)


@pytest.mark.parametrize(
    ("ipv4", "ipv6"),
    [
        ("169.254.12.34/31", "fe80::a9fe:c22/127"),  # example from docs/data-model.md
        ("169.254.1.0/31", "fe80::a9fe:100/127"),
        ("169.254.254.254/31", "fe80::a9fe:fefe/127"),
    ],
)
def test_ipv6_network_for(ipv4: str, ipv6: str) -> None:
    assert ipv6_network_for(ipv4) == ipv6
    TunnelIPv6NetworkValidator()(ipv6)


@pytest.mark.parametrize("ipv4", ["10.0.0.0/31", "169.254.12.32/30"])
def test_ipv6_network_for_rejects(ipv4: str) -> None:
    with pytest.raises(ValueError, match="is not a /31"):
        ipv6_network_for(ipv4)
