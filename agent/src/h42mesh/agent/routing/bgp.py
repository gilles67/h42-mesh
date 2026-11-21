"""Reading the state of FRR with vtysh (main process, default VRF).

- states of the BGP sessions: ``show bgp neighbors json``;
- the BGP table, every path and not only the best:
  ``show bgp ipv4|ipv6 unicast detail json`` (or without ``detail`` on an
  older FRR), turned into the reports sent to the controller.

The parsers are pure and tolerant: an unknown field is ignored, a path that
cannot be understood is skipped (and logged).
"""

import ipaddress
import json
import logging
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from h42mesh.agent.messages import BgpRouteReport, BgpRouteSource
from h42mesh.agent.routing.frr import BACKUP_LOCAL_PREF

logger = logging.getLogger(__name__)

VTYSH = "vtysh"
VTYSH_TIMEOUT = 30.0
ESTABLISHED = "Established"
MAX_ROUTES = 10_000
_BACKUP_COMMUNITY = re.compile(r"(^|\s)\d+:1:2(\s|$)")
_LOCAL_PEERS = {"", "0.0.0.0", "::", "(unspec)"}  # noqa: S104 (not a bind address)


class VtyshError(Exception):
    pass


Vtysh = Callable[[str], str]


def run_vtysh(command: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 (fixed program, fixed commands)
            [VTYSH, "-c", command],
            capture_output=True,
            text=True,
            timeout=VTYSH_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VtyshError(f"{VTYSH}: {exc}") from exc
    if result.returncode != 0:
        raise VtyshError(f"{command}: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VtyshError(f"not JSON: {exc}") from exc


def _address_key(key: str) -> str:
    """``fe80::1%wd0c0…`` -> ``fe80::1``; other keys unchanged."""
    return key.split("%", 1)[0]


def neighbor_states(text: str) -> dict[str, str]:
    """Neighbor (address, or interface name) -> BGP state, e.g. Established."""
    data = _json(text)
    states: dict[str, str] = {}
    if not isinstance(data, dict):
        return states
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(value.get("bgpState"), str):
            states[_address_key(key)] = value["bgpState"]
            interface = value.get("interface") or value.get("ifName")
            if isinstance(interface, str):
                states.setdefault(interface, value["bgpState"])
    return states


# --- BGP table ---------------------------------------------------------------


@dataclass
class RouteContext:
    """How to tell where a path comes from."""

    tunnel_by_peer: dict[str, UUID] = field(default_factory=dict)  # fe80:: of the other end
    tunnel_by_interface: dict[str, UUID] = field(default_factory=dict)
    internal_peers: set[str] = field(default_factory=set)  # address or interface


def _paths(routes: object) -> Iterator[tuple[str, dict[str, Any]]]:
    """(prefix, path) from both formats: prefix -> [paths] or prefix -> {"paths": […]}."""
    if not isinstance(routes, dict):
        return
    for prefix, value in routes.items():
        paths = value.get("paths") if isinstance(value, dict) else value
        if isinstance(paths, list):
            for path in paths:
                if isinstance(path, dict):
                    yield str(prefix), path


def _as_path(path: Mapping[str, Any]) -> list[int]:
    raw = path.get("aspath")
    text = raw.get("string") if isinstance(raw, dict) else path.get("path", raw)
    if not isinstance(text, str):
        return []
    return [int(item) for item in text.split() if item.isdigit()]


def _best(path: Mapping[str, Any]) -> bool:
    best = path.get("bestpath")
    if isinstance(best, dict):
        return bool(best.get("overall"))
    return bool(best)


def _local_pref(path: Mapping[str, Any]) -> int | None:
    value = path.get("localpref", path.get("locPrf"))
    return value if isinstance(value, int) else None


def _large_communities(path: Mapping[str, Any]) -> str:
    raw = path.get("largeCommunity")
    if isinstance(raw, dict):
        raw = raw.get("string")
    return raw if isinstance(raw, str) else ""


def _peer(path: Mapping[str, Any]) -> tuple[str, str | None]:
    """(peer address, interface) of a path."""
    peer = path.get("peer")
    address = peer.get("peerId") if isinstance(peer, dict) else path.get("peerId")
    interface = peer.get("interface") if isinstance(peer, dict) else None
    if interface is None:
        for hop in path.get("nexthops") or []:
            if isinstance(hop, dict) and isinstance(hop.get("interface"), str):
                interface = hop["interface"]
                break
    return _address_key(str(address or "")), interface


def _route(prefix: str, path: Mapping[str, Any], context: RouteContext) -> BgpRouteReport | None:
    address, interface = _peer(path)
    as_path = _as_path(path)
    tunnel = context.tunnel_by_peer.get(address) or (
        context.tunnel_by_interface.get(interface) if interface else None
    )
    if tunnel is not None:
        source = BgpRouteSource.TUNNEL
    elif address in context.internal_peers or (interface in context.internal_peers):
        source = BgpRouteSource.INTERNAL
    elif address in _LOCAL_PEERS or path.get("local") is True or path.get("sourced") is True:
        source = BgpRouteSource.LOCAL
    else:
        logger.debug("route %s from an unknown peer %s: skipped", prefix, address)
        return None
    local_pref = _local_pref(path)
    return BgpRouteReport(
        prefix=str(ipaddress.ip_network(prefix, strict=False)),
        source=source,
        tunnel_id=tunnel,
        as_path=as_path[:255],
        origin_asn=as_path[-1] if as_path else None,
        is_best=_best(path),
        is_backup=bool(_BACKUP_COMMUNITY.search(_large_communities(path)))
        or local_pref == BACKUP_LOCAL_PREF,
        local_pref=local_pref,
    )


def parse_routes(text: str, context: RouteContext) -> list[BgpRouteReport]:
    data = _json(text)
    routes = data.get("routes") if isinstance(data, dict) else None
    found = []
    for prefix, path in _paths(routes):
        try:
            report = _route(prefix, path, context)
        except (ValueError, ValidationError) as exc:
            logger.warning("route %s not understood: %s", prefix, exc)
            continue
        if report is not None:
            found.append(report)
    return found


@dataclass
class FrrReader:
    """Reads FRR through vtysh (blocking: call it in a thread)."""

    vtysh: Vtysh = run_vtysh

    def neighbor_states(self) -> dict[str, str]:
        return neighbor_states(self.vtysh("show bgp neighbors json"))

    def routes(self, context: RouteContext) -> list[BgpRouteReport]:
        found: list[BgpRouteReport] = []
        for family in ("ipv4", "ipv6"):
            try:
                text = self.vtysh(f"show bgp {family} unicast detail json")
            except VtyshError:
                text = self.vtysh(f"show bgp {family} unicast json")  # older FRR
            found += parse_routes(text, context)
        return found[:MAX_ROUTES]
