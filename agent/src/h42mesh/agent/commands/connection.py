"""h42-mesh-agent connection list/show/set/remove: local connection settings."""

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from h42mesh.agent.commands import load_or_exit, not_implemented
from h42mesh.agent.config import PortRange

_DURATION = re.compile(r"(\d+)([smh]?)")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}
_NUMBER = re.compile(r"c([0-9])")


def parse_duration(text: str) -> int:
    """Seconds from ``30``, ``30s``, ``10m`` or ``1h``."""
    match = _DURATION.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{text!r} is not a duration (examples: 30s, 10m, 1h)")
    return int(match.group(1)) * _UNITS[match.group(2)]


def parse_ports(text: str) -> PortRange:
    """``42000-42999`` (or a single port ``42000``)."""
    low, sep, high = text.strip().partition("-")
    try:
        return PortRange(min=int(low), max=int(high) if sep else int(low))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a port range (example: 42000-42999)") from exc


@dataclass(frozen=True)
class Target:
    """A connection designated by its number (c0…c9) or directly by its UID."""

    number: int | None = None
    uid: UUID | None = None


def parse_target(text: str) -> Target:
    match = _NUMBER.fullmatch(text.strip())
    if match is not None:
        return Target(number=int(match.group(1)))
    try:
        return Target(uid=UUID(text.strip()))
    except ValueError as exc:
        raise ValueError(f"{text!r} is neither c0…c9 nor a connection UID") from exc


@dataclass(frozen=True)
class SetOptions:
    interface: str | None = None
    vrf: str | None = None
    ports: PortRange | None = None
    force_ipv4: str | None = None
    force_ipv6: str | None = None
    fallback_delay: int | None = None
    ipv6_retry: int | None = None
    clear: frozenset[str] = frozenset()


def list_connections(path: Path | None) -> int:
    load_or_exit(path)
    return not_implemented("connection list")


def show_connection(path: Path | None, target: Target) -> int:
    load_or_exit(path)
    return not_implemented("connection show")


def set_connection(path: Path | None, target: Target, options: SetOptions) -> int:
    load_or_exit(path)
    return not_implemented("connection set")


def remove_connection(path: Path | None, target: Target) -> int:
    load_or_exit(path)
    return not_implemented("connection remove")
