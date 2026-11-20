"""Enumerations stored as text (CharEnumField), in English; the GUI translates them."""

from enum import StrEnum


class MeshAccessLevel(StrEnum):
    MANAGE = "manage"
    READ = "read"  # every piece of information of the mesh, no modification


class ConnectionRole(StrEnum):
    ACTIVE = "active"
    BACKUP = "backup"  # always lower precedence than an active connection


class DirectMode(StrEnum):
    """Address families in which a connection accepts inbound tunnels."""

    NONE = "none"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    BOTH = "both"


class AddressFamily(StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"


class BgpRouteSource(StrEnum):
    LOCAL = "local"  # announced by this router
    TUNNEL = "tunnel"  # learnt through a tunnel (eBGP)
    INTERNAL = "internal"  # learnt from the other router of the site (iBGP)
