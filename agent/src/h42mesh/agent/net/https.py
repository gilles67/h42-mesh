"""HTTPS to the controller, at an address resolved by the agent itself.

The connection goes to the IP address given by the built-in DNS client, while
SNI and certificate verification use the controller name. If the first
controller does not answer, the second one is tried.
"""

import ipaddress
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.net.dns import Address, DnsError, Resolver

# Certificate authorities of the system (managed by the administrator), rather
# than the bundle of certifi.
SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
DEFAULT_TIMEOUT = 10.0
# Answers that mean "this controller cannot serve now": try the other one.
RETRY_STATUSES = frozenset({502, 503, 504})


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    controller: str  # origin that answered


class ControllerUnreachableError(Exception):
    """No controller answered through this connection."""


def default_verify() -> str | bool:
    return SYSTEM_CA_BUNDLE if os.path.exists(SYSTEM_CA_BUNDLE) else True


class _ServerNameAdapter(HTTPAdapter):
    """Connects to the URL host (an IP address) but uses ``server_name`` for SNI
    and for the certificate check."""

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        super().__init__(max_retries=0)

    def init_poolmanager(
        self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: object
    ) -> None:
        pool_kwargs["server_hostname"] = self.server_name
        pool_kwargs["assert_hostname"] = self.server_name
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def https_request(
    origin: str,
    address: Address,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    verify: str | bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpResponse:
    """One HTTPS request to ``origin`` (https://name[:port]) at ``address``."""
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{origin!r} is not an https origin")
    port = parts.port or 443
    host_header = parts.hostname if port == 443 else f"{parts.hostname}:{port}"
    target = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)

    with requests.Session() as session:
        session.trust_env = False  # no proxy, no .netrc from the environment
        session.mount("https://", _ServerNameAdapter(parts.hostname))
        response = session.request(
            method,
            f"https://{target}:{port}{path}",
            data=body,
            headers={**(headers or {}), "Host": host_header},
            verify=verify,
            timeout=timeout,
            allow_redirects=False,
        )
        return HttpResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
            controller=origin,
        )


Transport = Callable[..., HttpResponse]


class ControllerClient:
    """Tries each controller, and each of its addresses (IPv6 first), in turn."""

    def __init__(
        self,
        controllers: list[str],
        resolver: Resolver,
        transport: Transport = https_request,
        verify: str | bool | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.controllers = controllers
        self.resolver = resolver
        self.transport = transport
        self.verify = default_verify() if verify is None else verify
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        family: AddressFamily | None = None,
    ) -> HttpResponse:
        errors: list[str] = []
        for origin in self.controllers:
            host = urlsplit(origin).hostname or ""
            try:
                addresses = self.resolver.resolve(host, family)
            except DnsError as exc:
                errors.append(f"{origin}: {exc}")
                continue
            for address in addresses:
                try:
                    response = self.transport(
                        origin,
                        address,
                        method,
                        path,
                        body=body,
                        headers=headers,
                        verify=self.verify,
                        timeout=self.timeout,
                    )
                except (requests.RequestException, OSError) as exc:
                    errors.append(f"{origin} ({address}): {type(exc).__name__}: {exc}")
                    continue
                if response.status in RETRY_STATUSES:
                    errors.append(f"{origin}: HTTP {response.status}")
                    break  # this controller is up but cannot serve: next one
                return response
        raise ControllerUnreachableError("; ".join(errors) or "no controller configured")
