"""Field validators and AS number computation."""

import ipaddress

from tortoise.exceptions import ValidationError
from tortoise.validators import Validator

from h42mesh.controller.models.enums import SiteKind

ROUTER_ID_NETWORK = ipaddress.IPv4Network("10.254.0.0/24")

ASN_BASE = 4_200_000_000
HOME_NUMBERS = range(1, 101)  # 1 to 100
RELAY_NUMBERS = range(101, 1000)  # 101 and above


class IPv4InNetworkValidator(Validator):
    """Check that a text value is an IPv4 host address within a given network."""

    def __init__(self, network: ipaddress.IPv4Network) -> None:
        self.network = network

    def __call__(self, value: object) -> None:
        if value is None:
            return
        if not isinstance(value, str):
            raise ValidationError(f"{value!r} must be an address given as text")
        try:
            address = ipaddress.IPv4Address(value)
        except ValueError as exc:
            raise ValidationError(f"{value!r} is not an IPv4 address") from exc
        if str(address) != value:
            raise ValidationError(f"{value!r} is not in canonical form")
        if address not in self.network or address in (
            self.network.network_address,
            self.network.broadcast_address,
        ):
            raise ValidationError(f"{value} is not a host address of {self.network}")


def asn_for(kind: SiteKind, number: int) -> int:
    """Private 4-byte AS of a site: 4200000000 + number, within the range of its kind."""
    allowed = HOME_NUMBERS if kind is SiteKind.HOME else RELAY_NUMBERS
    if number not in allowed:
        raise ValueError(
            f"number {number} is outside the range {allowed.start}-{allowed.stop - 1} "
            f"for a {kind.value} site"
        )
    return ASN_BASE + number
