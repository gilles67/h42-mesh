"""HTTPS at an address resolved by the agent, certificate checked for the name."""

import ipaddress
import json
import socket
from pathlib import Path
from typing import Any

import pytest
import requests

from h42mesh.agent.net.dns import Address, Resolver
from h42mesh.agent.net.https import (
    ControllerClient,
    ControllerUnreachableError,
    HttpResponse,
    https_request,
)
from tls_helpers import https_server

LOCALHOST = ipaddress.ip_address("127.0.0.1")


def fixed_resolver(table: dict[str, list[str]]) -> Resolver:
    def query(name: str, rdtype: str, servers: list[str], timeout: float) -> list[str]:
        return [a for a in table.get(name, []) if (":" in a) == (rdtype == "AAAA")]

    return Resolver([ipaddress.ip_address("192.0.2.53")], query=query)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def test_request_to_an_ip_with_the_controller_name(tmp_path: Path) -> None:
    with https_server(tmp_path, "controller.test") as (port, ca, recorded):
        response = https_request(
            f"https://controller.test:{port}",
            LOCALHOST,
            "POST",
            "/api/v1/agent/enroll",
            body=b'{"a": 1}',
            headers={"Content-Type": "application/json"},
            verify=str(ca),
        )
    assert response.status == 200
    assert json.loads(response.body) == {"ok": True}
    assert response.headers["etag"] == '"etag-value"'
    assert recorded.server_names == ["controller.test"]  # SNI
    (request,) = recorded.requests
    assert request["headers"]["host"] == f"controller.test:{port}"
    assert request["path"] == "/api/v1/agent/enroll"
    assert request["body"] == b'{"a": 1}'


def test_certificate_for_another_name_is_refused(tmp_path: Path) -> None:
    with (
        https_server(tmp_path, "someone-else.test") as (port, ca, _),
        pytest.raises(requests.exceptions.SSLError),
    ):
        https_request(f"https://controller.test:{port}", LOCALHOST, "GET", "/", verify=str(ca))


def test_unknown_certificate_authority_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    from tls_helpers import make_certificates

    other_ca, _, _ = make_certificates(other, "controller.test")
    with (
        https_server(tmp_path, "controller.test") as (port, _, _),
        pytest.raises(requests.exceptions.SSLError),
    ):
        https_request(
            f"https://controller.test:{port}", LOCALHOST, "GET", "/", verify=str(other_ca)
        )


def test_client_resolves_then_connects(tmp_path: Path) -> None:
    resolver = fixed_resolver({"controller.test": ["127.0.0.1"]})
    with https_server(tmp_path, "controller.test") as (port, ca, recorded):
        client = ControllerClient([f"https://controller.test:{port}"], resolver, verify=str(ca))
        response = client.request("GET", "/api/v1/agent/me", headers={"Authorization": "x"})
    assert response.status == 200
    assert response.controller == f"https://controller.test:{port}"
    assert recorded.requests[0]["headers"]["authorization"] == "x"


def test_second_controller_when_the_first_is_down(tmp_path: Path) -> None:
    resolver = fixed_resolver({"vps1.test": ["127.0.0.1"], "controller.test": ["127.0.0.1"]})
    with https_server(tmp_path, "controller.test") as (port, ca, _):
        client = ControllerClient(
            [f"https://vps1.test:{free_port()}", f"https://controller.test:{port}"],
            resolver,
            verify=str(ca),
            timeout=2,
        )
        response = client.request("GET", "/")
    assert response.controller.startswith("https://controller.test")


# --- failover logic, without network ------------------------------------------


class FakeTransport:
    def __init__(self, answers: dict[tuple[str, str], Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self, origin: str, address: Address, method: str, path: str, **_: Any
    ) -> HttpResponse:
        self.calls.append((origin, str(address)))
        answer = self.answers[(origin, str(address))]
        if isinstance(answer, Exception):
            raise answer
        return HttpResponse(status=answer, headers={}, body=b"", controller=origin)


RESOLVER = fixed_resolver(
    {"vps1.test": ["2001:db8::1", "198.51.100.1"], "vps2.test": ["198.51.100.2"]}
)
VPS1, VPS2 = "https://vps1.test", "https://vps2.test"


def test_ipv6_first_then_ipv4() -> None:
    transport = FakeTransport(
        {(VPS1, "2001:db8::1"): requests.ConnectionError("down"), (VPS1, "198.51.100.1"): 200}
    )
    client = ControllerClient([VPS1, VPS2], RESOLVER, transport=transport, verify=True)
    assert client.request("GET", "/").status == 200
    assert transport.calls == [(VPS1, "2001:db8::1"), (VPS1, "198.51.100.1")]


@pytest.mark.parametrize("status", [502, 503, 504])
def test_unavailable_controller_means_the_next_one(status: int) -> None:
    transport = FakeTransport({(VPS1, "2001:db8::1"): status, (VPS2, "198.51.100.2"): 200})
    client = ControllerClient([VPS1, VPS2], RESOLVER, transport=transport, verify=True)
    assert client.request("GET", "/").controller == VPS2
    assert (VPS1, "198.51.100.1") not in transport.calls  # same controller: not retried


@pytest.mark.parametrize("status", [200, 304, 401, 404, 422, 500])
def test_real_answers_are_returned(status: int) -> None:
    transport = FakeTransport({(VPS1, "2001:db8::1"): status})
    client = ControllerClient([VPS1, VPS2], RESOLVER, transport=transport, verify=True)
    assert client.request("GET", "/").status == status
    assert len(transport.calls) == 1


def test_all_controllers_unreachable() -> None:
    error = requests.ConnectionError("down")
    transport = FakeTransport(
        {(VPS1, "2001:db8::1"): error, (VPS1, "198.51.100.1"): error, (VPS2, "198.51.100.2"): 503}
    )
    client = ControllerClient([VPS1, VPS2], RESOLVER, transport=transport, verify=True)
    with pytest.raises(ControllerUnreachableError, match=r"vps2\.test: HTTP 503"):
        client.request("GET", "/")


def test_dns_failure_moves_to_the_next_controller() -> None:
    transport = FakeTransport({(VPS2, "198.51.100.2"): 200})
    client = ControllerClient(
        ["https://unknown.test", VPS2], RESOLVER, transport=transport, verify=True
    )
    assert client.request("GET", "/").controller == VPS2


def test_family_restriction_is_passed_to_dns() -> None:
    transport = FakeTransport({(VPS1, "198.51.100.1"): 200})
    client = ControllerClient([VPS1], RESOLVER, transport=transport, verify=True)
    client.request("POST", "/", family="ipv4")  # type: ignore[arg-type]
    assert transport.calls == [(VPS1, "198.51.100.1")]
