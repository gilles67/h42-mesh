"""Built-in DNS client: resolves the controllers from the VRF of a connection.

The system resolver is bound to the default VRF, which has no route to the
Internet: the agent asks the DNS servers of its configuration itself. Only
servers of an address family available on the connection are used.
"""

import ipaddress
from collections.abc import Callable

import dns.exception
import dns.resolver

from h42mesh.agent.messages import AddressFamily

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
# (name, "A" or "AAAA", nameservers, timeout) -> addresses (empty if none)
Query = Callable[[str, str, list[str], float], list[str]]
FamilyAvailable = Callable[[int], bool]

RECORD_TYPES = {6: "AAAA", 4: "A"}
DEFAULT_TIMEOUT = 5.0


class DnsError(Exception):
    """The name could not be resolved."""


def dnspython_query(name: str, rdtype: str, nameservers: list[str], timeout: float) -> list[str]:
    resolver = dns.resolver.Resolver(configure=False)  # never /etc/resolv.conf
    resolver.nameservers = nameservers
    resolver.lifetime = timeout
    try:
        answer = resolver.resolve(name, rdtype, search=False)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException as exc:
        raise DnsError(f"{name} {rdtype}: {exc}") from exc
    return [record.to_text() for record in answer]


def _always(version: int) -> bool:
    return True


class Resolver:
    def __init__(
        self,
        servers: list[Address],
        query: Query = dnspython_query,
        family_available: FamilyAvailable = _always,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.servers = servers
        self.query = query
        self.family_available = family_available
        self.timeout = timeout

    def resolve(self, host: str, family: AddressFamily | None = None) -> list[Address]:
        """Addresses of ``host``, IPv6 first, in the families usable on the connection.

        ``family`` restricts the answer to one family (public address discovery).
        """
        versions = [v for v in (6, 4) if family is None or v == (4 if family == "ipv4" else 6)]
        versions = [v for v in versions if self.family_available(v)]
        if not versions:
            raise DnsError(f"no usable address family to reach {host}")

        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None
        if literal is not None:
            if literal.version not in versions:
                raise DnsError(f"{host}: family not usable on this connection")
            return [literal]

        servers = [str(s) for s in self.servers if self.family_available(s.version)]
        if not servers:
            raise DnsError("no DNS server reachable on this connection")
        addresses: list[Address] = []
        errors: list[str] = []
        for version in versions:
            try:
                found = self.query(host, RECORD_TYPES[version], servers, self.timeout)
            except DnsError as exc:
                errors.append(str(exc))
                continue
            for text in found:
                address = ipaddress.ip_address(text)
                if address.version == version and address not in addresses:
                    addresses.append(address)
        if not addresses:
            detail = "; ".join(errors) or "no A/AAAA record"
            raise DnsError(f"cannot resolve {host}: {detail}")
        return addresses
