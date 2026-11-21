"""Messages exchanged with the controller: tolerance of responses, strict requests."""

import base64
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from h42mesh.agent.messages import (
    BgpRouteReport,
    BgpRouteSource,
    ConfigTunnel,
    Endpoint,
    ErrorResponse,
    PublicAddressReport,
    RouterConfig,
    TunnelKeyReport,
    TunnelSide,
)

KEY = base64.b64encode(bytes(32)).decode()


def tunnel_document(**overrides: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "side": "b",
        "role": "active",
        "families": ["ipv6", "ipv4"],
        "local_connection_id": str(uuid.uuid4()),
        "ipv4_network": "169.254.12.34/31",
        "ipv6_network": "fe80::a9fe:c22/127",
        "local_ipv4": "169.254.12.35",
        "local_ipv6": "fe80::a9fe:c23",
        "peer_ipv4": "169.254.12.34",
        "peer_ipv6": "fe80::a9fe:c22",
        "local_public_key": None,
        "local_port": None,
        "preshared_key": KEY,
        "peer": {
            "connection_id": str(uuid.uuid4()),
            "site_nickname": "root",
            "site_asn": 4200000000,
            "router_number": 0,
            "connection_number": 0,
            "public_key": KEY,
            "port": 42000,
            "endpoints": [
                {"family": "ipv6", "address": "2001:db8::1"},
                {"family": "ipv4", "address": "198.51.100.1"},
            ],
        },
    } | overrides


def config_document(**overrides: Any) -> dict[str, Any]:
    return {
        "format": 1,
        "fingerprint": "f" * 64,
        "mesh": {"id": str(uuid.uuid4()), "name": "home42"},
        "site": {"id": str(uuid.uuid4()), "nickname": "pari", "asn": 4200000001},
        "router": {"id": str(uuid.uuid4()), "number": 0, "name": "r0"},
        "connections": [
            {
                "id": str(uuid.uuid4()),
                "number": 0,
                "name": "fiber",
                "role": "active",
                "priority": None,
                "direct": "none",
                "public_ipv4": "93.184.216.34",
                "public_ipv6": None,
            }
        ],
        "tunnels": [tunnel_document()],
    } | overrides


def router_config(**overrides: Any) -> RouterConfig:
    return RouterConfig.model_validate(config_document(**overrides))


def test_router_config() -> None:
    config = router_config()
    (tunnel,) = config.tunnels
    assert tunnel.side is TunnelSide.B
    assert str(tunnel.peer.endpoints[0].address) == "2001:db8::1"
    assert tunnel.peer.port == 42000
    assert str(config.connections[0].public_ipv4) == "93.184.216.34"


def test_responses_ignore_unknown_fields() -> None:
    """A newer controller may add fields: the agent keeps working."""
    document = config_document(new_top_level=1)
    document["tunnels"][0]["mtu"] = 1420
    document["tunnels"][0]["peer"]["latency"] = 12
    config = RouterConfig.model_validate(document)
    assert not hasattr(config, "new_top_level")
    ErrorResponse.model_validate({"code": "x", "message": "y", "details": []})


def test_requests_refuse_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PublicAddressReport.model_validate(
            {"connection_id": str(uuid.uuid4()), "family": "ipv4", "address": "1.2.3.4"}
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"preshared_key": "short"},
        {"side": "c"},
        {"local_ipv4": "not an address"},
        {"ipv4_network": "169.254.12.35/31"},  # host bits set
        {"local_port": 0},
    ],
)
def test_invalid_tunnel_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ConfigTunnel.model_validate(tunnel_document(**overrides))


def test_endpoint_family_must_match() -> None:
    with pytest.raises(ValidationError, match="not an ipv6 address"):
        Endpoint.model_validate({"family": "ipv6", "address": "198.51.100.1"})


def test_requests_serialise_as_the_controller_expects() -> None:
    tunnel_id = uuid.uuid4()
    report = TunnelKeyReport(tunnel_id=tunnel_id, public_key=KEY, port=42000)
    assert report.model_dump(mode="json") == {
        "tunnel_id": str(tunnel_id),
        "public_key": KEY,
        "port": 42000,
    }


def test_bgp_route_tunnel_iff_source_tunnel() -> None:
    BgpRouteReport(
        prefix="10.0.0.0/8", source=BgpRouteSource.LOCAL, as_path=[], is_best=True, is_backup=False
    )
    with pytest.raises(ValidationError):
        BgpRouteReport(
            prefix="10.0.0.0/8",
            source=BgpRouteSource.TUNNEL,
            as_path=[],
            is_best=True,
            is_backup=False,
        )
