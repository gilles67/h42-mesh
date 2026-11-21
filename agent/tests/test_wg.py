"""Text given to and read from wg."""

from datetime import UTC, datetime

import pytest

from fake_tunnel_backend import key, make_spec
from h42mesh.agent.messages import AddressFamily, TunnelSide
from h42mesh.agent.tunnels.wg import DumpError, endpoint_family, parse_dump, render_config


def test_config_of_side_b() -> None:
    spec = make_spec()
    text = render_config(spec, spec.peer_endpoints[0])
    assert text == (
        "[Interface]\n"
        f"PrivateKey = {key(1)}\n"
        "ListenPort = 42001\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {key(2)}\n"
        f"PresharedKey = {key(3)}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "Endpoint = [2001:db8::1]:42000\n"
        "PersistentKeepalive = 25\n"
    )


def test_config_of_side_a() -> None:
    text = render_config(make_spec(side=TunnelSide.A), None)
    assert "Endpoint" not in text and "PersistentKeepalive" not in text
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in text


DUMP = (
    f"{key(1)}\t{key(4)}\t42001\toff\n"
    f"{key(2)}\t{key(3)}\t198.51.100.1:42000\t0.0.0.0/0,::/0\t1767225600\t1200\t3400\t25\n"
)


def test_dump() -> None:
    dump = parse_dump(DUMP)
    assert (dump.public_key, dump.listen_port) == (key(4), 42001)
    (peer,) = dump.peers
    assert peer.endpoint == "198.51.100.1:42000"
    assert peer.last_handshake_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert (peer.rx_bytes, peer.tx_bytes) == (1200, 3400)


def test_dump_without_handshake_nor_endpoint() -> None:
    text = f"{key(1)}\t{key(4)}\t42001\toff\n{key(2)}\t(none)\t(none)\t0.0.0.0/0\t0\t0\t0\toff\n"
    (peer,) = parse_dump(text).peers
    assert (peer.endpoint, peer.latest_handshake) == (None, None)


@pytest.mark.parametrize(
    "text", ["", "a\tb\n", f"{key(1)}\t{key(4)}\tport\toff\n", DUMP + "x\ty\n"]
)
def test_invalid_dump(text: str) -> None:
    with pytest.raises(DumpError):
        parse_dump(text)


def test_endpoint_family() -> None:
    assert endpoint_family("198.51.100.1:42000") is AddressFamily.IPV4
    assert endpoint_family("[2001:db8::1]:42000") is AddressFamily.IPV6
    assert endpoint_family("[fe80::1%eth0]:1") is AddressFamily.IPV6
    assert endpoint_family(None) is None
    assert endpoint_family("garbage") is None
