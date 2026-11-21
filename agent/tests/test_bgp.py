"""Reading FRR: session states and BGP table (both JSON formats of FRR)."""

import json
import uuid

import pytest

from h42mesh.agent.messages import BgpRouteSource
from h42mesh.agent.routing.bgp import (
    FrrReader,
    RouteContext,
    VtyshError,
    neighbor_states,
    parse_routes,
)

TUNNEL = uuid.UUID(int=101)
CONTEXT = RouteContext(
    tunnel_by_peer={"fe80::a9fe:a00": TUNNEL},
    tunnel_by_interface={"wd0c0rootr0c0": TUNNEL},
    internal_peers={"fe80::1a2b:3cff:fe4d:5e6f", "br-lan"},
)

# "detail" format: prefix -> {"paths": [...]}.
DETAIL = {
    "routes": {
        "192.168.20.0/24": {
            "prefix": "192.168.20.0/24",
            "paths": [
                {
                    "aspath": {"string": "4200000000 4200000002", "length": 2},
                    "bestpath": {"overall": True},
                    "localpref": 100,
                    "peer": {"peerId": "fe80::a9fe:a00", "interface": "wd0c0rootr0c0"},
                },
                {
                    "aspath": {"string": "4200000000 4200000002"},
                    "localpref": 50,
                    "largeCommunity": {"string": "4200000003:1:2 4200000001:1:2"},
                    "peer": {"peerId": "fe80::1a2b:3cff:fe4d:5e6f", "type": "internal"},
                },
            ],
        },
        "192.168.10.0/24": {
            "paths": [
                {
                    "aspath": {"string": ""},
                    "bestpath": {"overall": True},
                    "peer": {"peerId": "0.0.0.0"},
                    "sourced": True,
                }
            ]
        },
        "10.9.9.0/24": {"paths": [{"aspath": {"string": "65000"}, "peer": {"peerId": "fe80::99"}}]},
    }
}

# Table format (older FRR): prefix -> [paths].
TABLE = {
    "routes": {
        "2001:db8:20::/48": [
            {
                "path": "4200000002",
                "bestpath": True,
                "peerId": "fe80::a9fe:a00",
                "nexthops": [{"ip": "fe80::a9fe:a00", "interface": "wd0c0rootr0c0"}],
            }
        ]
    }
}


def test_routes_of_the_detail_format() -> None:
    routes = parse_routes(json.dumps(DETAIL), CONTEXT)
    by_key = {(r.prefix, r.source): r for r in routes}
    tunnel = by_key[("192.168.20.0/24", BgpRouteSource.TUNNEL)]
    assert (tunnel.tunnel_id, tunnel.as_path, tunnel.origin_asn) == (
        TUNNEL,
        [4200000000, 4200000002],
        4200000002,
    )
    assert (tunnel.is_best, tunnel.is_backup, tunnel.local_pref) == (True, False, 100)
    internal = by_key[("192.168.20.0/24", BgpRouteSource.INTERNAL)]
    assert internal.is_backup and not internal.is_best and internal.tunnel_id is None
    local = by_key[("192.168.10.0/24", BgpRouteSource.LOCAL)]
    assert (local.as_path, local.origin_asn, local.is_best) == ([], None, True)
    assert len(routes) == 3  # the path from an unknown peer is skipped


def test_routes_of_the_table_format() -> None:
    (route,) = parse_routes(json.dumps(TABLE), CONTEXT)
    assert (route.prefix, route.source, route.tunnel_id) == (
        "2001:db8:20::/48",
        BgpRouteSource.TUNNEL,
        TUNNEL,
    )
    assert route.as_path == [4200000002] and route.is_best


def test_backup_community_anywhere_in_the_list() -> None:
    document = {
        "routes": {
            "10.1.0.0/16": {
                "paths": [
                    {
                        "aspath": {"string": "4200000000"},
                        "largeCommunity": {"string": "4200000000:5:5 4200000003:1:2"},
                        "peer": {"peerId": "fe80::a9fe:a00"},
                    }
                ]
            }
        }
    }
    (route,) = parse_routes(json.dumps(document), CONTEXT)
    assert route.is_backup


def test_not_a_backup_community() -> None:
    document = {
        "routes": {
            "10.1.0.0/16": [
                {
                    "path": "4200000000",
                    "largeCommunity": {"string": "4200000000:1:20"},
                    "peerId": "fe80::a9fe:a00",
                }
            ]
        }
    }
    (route,) = parse_routes(json.dumps(document), CONTEXT)
    assert not route.is_backup


def test_empty_and_invalid_tables() -> None:
    assert parse_routes(json.dumps({"routes": {}}), CONTEXT) == []
    assert parse_routes("{}", CONTEXT) == []
    with pytest.raises(VtyshError):
        parse_routes("not json", CONTEXT)


def test_neighbor_states() -> None:
    text = json.dumps(
        {
            "fe80::a9fe:a00": {"bgpState": "Established", "remoteAs": 4200000000},
            "fe80::1a2b:3cff:fe4d:5e6f%br-lan": {"bgpState": "Active", "interface": "br-lan"},
            "totalPeers": 2,
        }
    )
    assert neighbor_states(text) == {
        "fe80::a9fe:a00": "Established",
        "fe80::1a2b:3cff:fe4d:5e6f": "Active",
        "br-lan": "Active",
    }


def test_reader_falls_back_without_detail() -> None:
    commands: list[str] = []

    def vtysh(command: str) -> str:
        commands.append(command)
        if "detail" in command:
            raise VtyshError("unknown command")
        return json.dumps(TABLE if "ipv6" in command else {"routes": {}})

    routes = FrrReader(vtysh).routes(CONTEXT)
    assert [r.prefix for r in routes] == ["2001:db8:20::/48"]
    assert commands == [
        "show bgp ipv4 unicast detail json",
        "show bgp ipv4 unicast json",
        "show bgp ipv6 unicast detail json",
        "show bgp ipv6 unicast json",
    ]
