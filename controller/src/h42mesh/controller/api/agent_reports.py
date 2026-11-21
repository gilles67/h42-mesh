"""Agent API: router configuration and reports (addresses, tunnels, states, BGP).

Every call is authenticated by the agent's JWT and confined to its router:
a connection or tunnel of another router is answered as unknown (404).
"""

import ipaddress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from h42mesh.controller import geoip
from h42mesh.controller.agent_config import build_router_config, etag, matches_if_none_match
from h42mesh.controller.api.agent import AGENT_ERRORS, AgentRouter
from h42mesh.controller.api.deps import SettingsDep
from h42mesh.controller.auth import agent_jwt
from h42mesh.controller.errors import ApiError, conflict, error_responses
from h42mesh.controller.models import (
    AddressFamily,
    BgpRoute,
    Connection,
    Router,
    Tunnel,
    TunnelStatus,
)
from h42mesh.controller.schemas.agent import (
    BgpRoutesReport,
    PublicAddressReport,
    PublicAddressResult,
    RouterConfig,
    TunnelKeysReport,
    TunnelSide,
    TunnelStatusesReport,
)
from h42mesh.controller.settings import Settings

router = APIRouter(prefix="/agent", tags=["agent"])

Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def _unprocessable(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


# --- configuration -----------------------------------------------------------


@router.get(
    "/config",
    response_model=RouterConfig,
    responses=AGENT_ERRORS | {304: {"description": "Not modified (If-None-Match)"}},
    summary="Desired configuration of the router",
)
async def get_router_config(
    router_: AgentRouter, if_none_match: Annotated[str | None, Header()] = None
) -> Response:
    """Site, connections and tunnels of the router, with the PSK of its tunnels only.

    The ETag is the fingerprint: with the same fingerprint in If-None-Match,
    the answer is 304 without a body.
    """
    config = await build_router_config(router_)
    headers = {"ETag": etag(config.fingerprint), "Cache-Control": "no-store"}
    if matches_if_none_match(if_none_match, config.fingerprint):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return JSONResponse(config.model_dump(mode="json"), headers=headers)


# --- public addresses --------------------------------------------------------


def is_public(address: Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def parse_address(text: str) -> Address | None:
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped  # ::ffff:a.b.c.d seen on a dual-stack socket
    return address


def seen_address(request: Request, settings: Settings) -> Address | None:
    """Source address of the request; X-Forwarded-For only from trusted proxies.

    The header is read from the right, skipping trusted proxies: the first
    other address is the client (anything further left could be forged).
    """
    peer = parse_address(request.client.host) if request.client else None
    trusted = [ipaddress.ip_network(n) for n in settings.trusted_proxies]

    def is_trusted(address: Address) -> bool:
        return any(address.version == n.version and address in n for n in trusted)

    if peer is None or not is_trusted(peer):
        return peer
    hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        address = parse_address(hop)
        if address is None:
            return None
        if not is_trusted(address):
            return address
    return peer


async def _own_connection(connection_id: UUID, router_: Router) -> Connection:
    connection = await Connection.get_or_none(id=connection_id, router_id=router_.id)
    if connection is None:  # unknown, or another router's: not revealed
        raise ApiError(status.HTTP_404_NOT_FOUND, "connection_not_found", "No such connection")
    return connection


@router.post(
    "/public-address",
    response_model=PublicAddressResult,
    responses=AGENT_ERRORS | error_responses(404, 422),
    summary="Discover the public address of a connection",
)
async def report_public_address(
    body: PublicAddressReport, request: Request, router_: AgentRouter, settings: SettingsDep
) -> PublicAddressResult:
    """Sent through the connection itself, once per family.

    The controller records the source address it sees, or the address forced
    by the local configuration of the agent.
    """
    connection = await _own_connection(body.connection_id, router_)
    version = 4 if body.family is AddressFamily.IPV4 else 6
    address: Address | None
    if body.forced_address is not None:
        address = parse_address(body.forced_address)
        if address is None or str(address) != body.forced_address:
            raise _unprocessable("invalid_address", "forced_address is not a canonical address")
    else:
        address = seen_address(request, settings)
        if address is None:
            raise _unprocessable("address_unknown", "The source address cannot be determined")
        if address.version == version and not is_public(address):
            raise _unprocessable("address_not_public", f"Source address {address} is not public")
    if address.version != version:
        raise _unprocessable("family_mismatch", f"{address} is not an {body.family} address")

    current = agent_jwt.now()
    if version == 4:
        connection.public_ipv4, connection.public_ipv4_updated_at = str(address), current
    else:
        connection.public_ipv6, connection.public_ipv6_updated_at = str(address), current
    best = connection.public_ipv4 or connection.public_ipv6  # IPv4 first for the operator
    if settings.geolite2_asn_file is not None and best is not None:
        connection.isp = geoip.isp_for(best, settings.geolite2_asn_file)
    await connection.save()
    return PublicAddressResult(family=body.family, address=str(address), isp=connection.isp)


# --- tunnel keys and ports ---------------------------------------------------


async def _router_tunnels(router_: Router) -> dict[UUID, tuple[Tunnel, TunnelSide]]:
    """Tunnels with an end on the router, and the side of the router on each."""
    tunnels = await Tunnel.filter(
        Q(connection_a__router_id=router_.id) | Q(connection_b__router_id=router_.id)
    ).select_related("connection_a")
    return {
        t.id: (t, TunnelSide.A if t.connection_a.router_id == router_.id else TunnelSide.B)
        for t in tunnels
    }


def _check_owned(ids: list[UUID], owned: dict[UUID, tuple[Tunnel, TunnelSide]]) -> None:
    unknown = [i for i in ids if i not in owned]
    if unknown:  # unknown, or another router's: not revealed
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "tunnel_not_found", f"No such tunnel: {unknown[0]}"
        )
    if len(set(ids)) != len(ids):
        raise _unprocessable("duplicate_tunnel", "A tunnel is reported twice")


@router.post(
    "/tunnels",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AGENT_ERRORS | error_responses(404, 409, 422),
    summary="Report the public key and port of tunnel ends of the router",
)
async def report_tunnel_keys(body: TunnelKeysReport, router_: AgentRouter) -> None:
    """All or nothing. A port is used once per router, all connections included."""
    owned = await _router_tunnels(router_)
    _check_owned([r.tunnel_id for r in body.tunnels], owned)
    reports = {r.tunnel_id: r for r in body.tunnels}

    ports: dict[int, UUID] = {}
    for tunnel_id, (tunnel, side) in owned.items():
        report = reports.get(tunnel_id)
        if report is not None:
            port: int | None = report.port
        else:
            port = tunnel.port_a if side is TunnelSide.A else tunnel.port_b
        if port is None:
            continue
        if port in ports:
            raise conflict("port_in_use", f"Port {port} is used by two tunnels of the router")
        ports[port] = tunnel_id

    async with in_transaction() as db:
        for tunnel_id, report in reports.items():
            tunnel, side = owned[tunnel_id]
            if side is TunnelSide.A:
                tunnel.public_key_a, tunnel.port_a = report.public_key, report.port
            else:
                tunnel.public_key_b, tunnel.port_b = report.public_key, report.port
            await tunnel.save(using_db=db)


# --- tunnel status and BGP table ---------------------------------------------


@router.put(
    "/tunnel-status",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AGENT_ERRORS | error_responses(404, 422),
    summary="Report the state of the tunnels of the router (full snapshot)",
)
async def report_tunnel_status(body: TunnelStatusesReport, router_: AgentRouter) -> None:
    """Replaces every status reported by this router."""
    owned = await _router_tunnels(router_)
    _check_owned([r.tunnel_id for r in body.tunnels], owned)
    current = agent_jwt.now()
    async with in_transaction() as db:
        await TunnelStatus.filter(router_id=router_.id).using_db(db).delete()
        for report in body.tunnels:
            await TunnelStatus.create(
                using_db=db,
                tunnel=owned[report.tunnel_id][0],
                router=router_,
                family_in_use=report.family_in_use,
                last_handshake_at=report.last_handshake_at,
                bgp_established=report.bgp_established,
                reported_at=current,
            )


@router.put(
    "/bgp-routes",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AGENT_ERRORS | error_responses(404, 422),
    summary="Report the BGP table of the router (replaces the previous one)",
)
async def report_bgp_routes(body: BgpRoutesReport, router_: AgentRouter) -> None:
    """Every known path, not only the best; no history is kept."""
    owned = await _router_tunnels(router_)
    tunnel_ids = sorted({r.tunnel_id for r in body.routes if r.tunnel_id is not None})
    _check_owned(tunnel_ids, owned)
    async with in_transaction() as db:
        await BgpRoute.filter(router_id=router_.id).using_db(db).delete()
        for route in body.routes:
            await BgpRoute.create(
                using_db=db,
                router=router_,
                prefix=route.prefix,
                source=route.source,
                tunnel=owned[route.tunnel_id][0] if route.tunnel_id else None,
                as_path=route.as_path,
                origin_asn=route.origin_asn,
                is_best=route.is_best,
                is_backup=route.is_backup,
                local_pref=route.local_pref,
            )
        router_.routes_reported_at = agent_jwt.now()
        await router_.save(using_db=db, update_fields=["routes_reported_at"])
