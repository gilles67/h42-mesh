"""Field validators (one value at a time) and tunnel address helpers.

IP addresses and networks are stored as text in canonical form, so that
equality and uniqueness in the database match equality of the values.
"""

import base64
import binascii
import ipaddress
import re

from tortoise.exceptions import ValidationError
from tortoise.validators import MaxValueValidator, MinValueValidator, Validator

# Private 4-byte AS range (RFC 6996), last value excluded (reserved).
ASN_MIN = 4_200_000_000
ASN_MAX = 4_294_967_294
UINT32_MAX = 4_294_967_295

TUNNEL_IPV4_SPACE = ipaddress.IPv4Network("169.254.0.0/16")
# Never drawn: reserved by RFC 3927, and the cloud metadata service range.
TUNNEL_IPV4_EXCLUDED = (
    ipaddress.IPv4Network("169.254.0.0/24"),
    ipaddress.IPv4Network("169.254.169.0/24"),
    ipaddress.IPv4Network("169.254.255.0/24"),
)
TUNNEL_IPV6_SPACE = ipaddress.IPv6Network("fe80::/64")


def range_validators(minimum: int, maximum: int) -> list[Validator]:
    """Inclusive bounds for an integer field."""
    return [MinValueValidator(minimum), MaxValueValidator(maximum)]


def _require_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{value!r} must be text")
    return value


class FullMatchValidator(Validator):
    """The whole text must match the pattern (no trailing newline accepted)."""

    def __init__(self, pattern: str) -> None:
        self.regex = re.compile(pattern)

    def __call__(self, value: object) -> None:
        if value is None:
            return
        if not self.regex.fullmatch(_require_str(value)):
            raise ValidationError(f"{value!r} does not match {self.regex.pattern!r}")


NICKNAME_VALIDATOR = FullMatchValidator(r"[a-z0-9]{4}")
# SHA-256 digest, lowercase hexadecimal.
SHA256_HEX_VALIDATOR = FullMatchValidator(r"[0-9a-f]{64}")


class PublicKeyValidator(Validator):
    """Base64 encoding of a 32-byte key (WireGuard X25519 or Ed25519): 44 characters."""

    def __call__(self, value: object) -> None:
        if value is None:
            return
        text = _require_str(value)
        try:
            raw = base64.b64decode(text, validate=True)
        except binascii.Error as exc:
            raise ValidationError(f"{text!r} is not valid base64") from exc
        if len(raw) != 32 or base64.b64encode(raw).decode() != text:
            raise ValidationError(f"{text!r} is not the canonical base64 of a 32-byte key")


class IPAddressValidator(Validator):
    """A single address of the given family, in canonical form."""

    def __init__(self, version: int) -> None:
        self.version = version

    def __call__(self, value: object) -> None:
        if value is None:
            return
        text = _require_str(value)
        try:
            address = ipaddress.ip_address(text)
        except ValueError as exc:
            raise ValidationError(f"{text!r} is not an IP address") from exc
        if address.version != self.version:
            raise ValidationError(f"{text!r} is not an IPv{self.version} address")
        if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
            raise ValidationError(f"{text!r} must not carry a scope (zone) id")
        if str(address) != text:
            raise ValidationError(f"{text!r} is not in canonical form ({address})")


def _parse_network(text: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise ValidationError(f"{text!r} is not a network (or has host bits set)") from exc
    if str(network) != text:
        raise ValidationError(f"{text!r} is not in canonical form ({network})")
    return network


class NetworkValidator(Validator):
    """An IPv4 or IPv6 network in canonical form, without host bits."""

    def __call__(self, value: object) -> None:
        if value is None:
            return
        _parse_network(_require_str(value))


class TunnelIPv4NetworkValidator(Validator):
    """A /31 in 169.254.0.0/16, outside the excluded ranges."""

    def __call__(self, value: object) -> None:
        if value is None:
            return
        network = _parse_network(_require_str(value))
        if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen != 31:
            raise ValidationError(f"{value!r} is not an IPv4 /31")
        if not network.subnet_of(TUNNEL_IPV4_SPACE):
            raise ValidationError(f"{value!r} is not in {TUNNEL_IPV4_SPACE}")
        for excluded in TUNNEL_IPV4_EXCLUDED:
            if network.subnet_of(excluded):
                raise ValidationError(f"{value!r} is in the excluded range {excluded}")


class TunnelIPv6NetworkValidator(Validator):
    """A /127 in fe80::/64."""

    def __call__(self, value: object) -> None:
        if value is None:
            return
        network = _parse_network(_require_str(value))
        if not isinstance(network, ipaddress.IPv6Network) or network.prefixlen != 127:
            raise ValidationError(f"{value!r} is not an IPv6 /127")
        if not network.subnet_of(TUNNEL_IPV6_SPACE):
            raise ValidationError(f"{value!r} is not in {TUNNEL_IPV6_SPACE}")


class AsPathValidator(Validator):
    """A JSON list of AS numbers (0 to 2**32 - 1)."""

    def __call__(self, value: object) -> None:
        if value is None:
            return
        if not isinstance(value, list):
            raise ValidationError(f"{value!r} must be a list of AS numbers")
        for asn in value:
            # bool is a subclass of int: reject it explicitly.
            if isinstance(asn, bool) or not isinstance(asn, int) or not 0 <= asn <= UINT32_MAX:
                raise ValidationError(f"{asn!r} is not an AS number")


def ipv6_network_for(ipv4_network: str) -> str:
    """Link-local IPv6 pair derived from the tunnel's IPv4 pair.

    The last 32 bits of the IPv6 address are the IPv4 address itself, so the
    prefix is ``fe80::a9fe:`` (169.254) followed by the last two octets:
    ``169.254.12.34/31`` -> ``fe80::a9fe:c22/127``.
    """
    network = ipaddress.IPv4Network(ipv4_network)
    if network.prefixlen != 31 or not network.subnet_of(TUNNEL_IPV4_SPACE):
        raise ValueError(f"{ipv4_network!r} is not a /31 in {TUNNEL_IPV4_SPACE}")
    base = int(TUNNEL_IPV6_SPACE.network_address) | int(network.network_address)
    return str(ipaddress.IPv6Network((base, 127)))
