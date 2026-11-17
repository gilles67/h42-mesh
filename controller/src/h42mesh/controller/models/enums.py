"""Enumerations stored as text (CharEnumField)."""

from enum import StrEnum


class SiteKind(StrEnum):
    HOME = "home"
    RELAY = "relay"  # VPS: single-router site, AS in the 4200000101+ range


class ConnectionRole(StrEnum):
    ACTIVE = "active"
    BACKUP = "backup"  # always lower precedence than an active connection


class ConnectionKind(StrEnum):
    """Connection type: informational only, drives no behaviour."""

    FIBER = "fiber"
    DSL = "dsl"
    CABLE = "cable"
    LTE = "4g"
    NR = "5g"
    STARLINK = "starlink"
    OTHER = "other"
