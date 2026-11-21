"""Built-in DNS client (dnspython is replaced by a fake query function)."""

import ipaddress

import dns.resolver
import pytest

from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.net import dns as agent_dns
from h42mesh.agent.net.dns import DnsError, Resolver

SERVERS = [ipaddress.ip_address(a) for a in ("1.1.1.1", "2606:4700:4700::1111")]
RECORDS = {
    ("vps1.example.org", "A"): ["198.51.100.1"],
    ("vps1.example.org", "AAAA"): ["2001:db8::1", "2001:db8::2"],
    ("v4only.example.org", "A"): ["198.51.100.4"],
}


class FakeQuery:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, list[str]]] = []
        self.fail = fail

    def __call__(self, name: str, rdtype: str, servers: list[str], timeout: float) -> list[str]:
        self.calls.append((name, rdtype, servers))
        if self.fail:
            raise DnsError("timeout")
        return RECORDS.get((name, rdtype), [])


def resolver(query: FakeQuery, available: set[int] = {4, 6}) -> Resolver:  # noqa: B006
    return Resolver(SERVERS, query=query, family_available=lambda v: v in available)


def test_ipv6_first() -> None:
    addresses = resolver(FakeQuery()).resolve("vps1.example.org")
    assert [str(a) for a in addresses] == ["2001:db8::1", "2001:db8::2", "198.51.100.1"]


def test_family_restriction() -> None:
    query = FakeQuery()
    addresses = resolver(query).resolve("vps1.example.org", AddressFamily.IPV4)
    assert [str(a) for a in addresses] == ["198.51.100.1"]
    assert [c[1] for c in query.calls] == ["A"]


def test_only_available_families_and_servers() -> None:
    query = FakeQuery()
    addresses = resolver(query, available={4}).resolve("vps1.example.org")
    assert [str(a) for a in addresses] == ["198.51.100.1"]
    assert query.calls == [("vps1.example.org", "A", ["1.1.1.1"])]  # no IPv6 server asked


def test_no_usable_family() -> None:
    with pytest.raises(DnsError, match="no usable address family"):
        resolver(FakeQuery(), available={4}).resolve("vps1.example.org", AddressFamily.IPV6)


def test_no_reachable_server() -> None:
    only_v6 = Resolver(
        [ipaddress.ip_address("2606:4700:4700::1111")],
        query=FakeQuery(),
        family_available=lambda v: v == 4,
    )
    with pytest.raises(DnsError, match="no DNS server"):
        only_v6.resolve("vps1.example.org")


def test_unknown_name() -> None:
    with pytest.raises(DnsError, match="no A/AAAA record"):
        resolver(FakeQuery()).resolve("nothing.example.org")


def test_partial_answer() -> None:
    assert [str(a) for a in resolver(FakeQuery()).resolve("v4only.example.org")] == ["198.51.100.4"]


def test_server_failure() -> None:
    with pytest.raises(DnsError, match="timeout"):
        resolver(FakeQuery(fail=True)).resolve("vps1.example.org")


@pytest.mark.parametrize(
    ("host", "expected"), [("198.51.100.9", "198.51.100.9"), ("[2001:db8::9]", "2001:db8::9")]
)
def test_ip_literal_is_not_resolved(host: str, expected: str) -> None:
    query = FakeQuery()
    assert [str(a) for a in resolver(query).resolve(host)] == [expected]
    assert query.calls == []


def test_ip_literal_of_an_unavailable_family() -> None:
    with pytest.raises(DnsError):
        resolver(FakeQuery(), available={4}).resolve("2001:db8::9")


def test_dnspython_never_reads_resolv_conf(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    class FakeResolver:
        def __init__(self, configure: bool = True) -> None:
            created.append({"configure": configure})
            self.nameservers: list[str] = []
            self.lifetime = 0.0

        def resolve(self, name: str, rdtype: str, search: bool = True) -> list[object]:
            created[-1].update(nameservers=self.nameservers, search=search, lifetime=self.lifetime)
            raise dns.resolver.NXDOMAIN

    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)
    assert agent_dns.dnspython_query("x.example.org", "A", ["1.1.1.1"], 3.0) == []
    assert created == [
        {"configure": False, "nameservers": ["1.1.1.1"], "search": False, "lifetime": 3.0}
    ]
