"""IPv6 → IPv4 fallback of side b (pure state machine)."""

from fake_tunnel_backend import make_spec
from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.tunnels.fallback import ESTABLISHED_WITHIN, Fallback

V6, V4 = AddressFamily.IPV6, AddressFamily.IPV4
T0 = 1_000_000.0


def machine(delay: float = 30, retry: float = 600) -> Fallback:
    fallback = Fallback(make_spec().peer_endpoints, delay, retry)
    assert fallback.start(T0).family is V6
    return fallback


def test_stays_on_ipv6_with_a_handshake() -> None:
    fallback = machine()
    assert fallback.step(T0 + 10, T0 + 2) is None
    assert fallback.step(T0 + 3600, T0 + 3590) is None  # renewed handshakes
    assert fallback.endpoint.family is V6


def test_waits_for_the_delay() -> None:
    fallback = machine()
    assert fallback.step(T0 + 29, None) is None


def test_falls_back_to_ipv4_without_handshake() -> None:
    fallback = machine()
    switched = fallback.step(T0 + 30, None)
    assert switched is not None and switched.family is V4


def test_a_handshake_before_the_switch_does_not_count() -> None:
    fallback = machine()
    assert fallback.step(T0 + 30, T0 - 5) is not None


def test_ipv6_is_tried_again_periodically() -> None:
    fallback = machine()
    fallback.step(T0 + 30, None)  # IPv4 now
    assert fallback.step(T0 + 100, T0 + 32) is None  # established on IPv4
    retry = fallback.step(T0 + 630, T0 + 620)
    assert retry is not None and retry.family is V6
    # Still broken: back to IPv4 after the delay.
    back = fallback.step(T0 + 660, T0 + 620)
    assert back is not None and back.family is V4


def test_ipv6_retry_succeeds() -> None:
    fallback = machine()
    fallback.step(T0 + 30, None)
    fallback.step(T0 + 630, T0 + 620)  # IPv6 again
    assert fallback.step(T0 + 640, T0 + 632) is None
    assert fallback.endpoint.family is V6


def test_ipv4_failing_too_alternates() -> None:
    fallback = machine()
    fallback.step(T0 + 30, None)
    again = fallback.step(T0 + 60, None)
    assert again is not None and again.family is V6


def test_lost_session_is_not_established() -> None:
    fallback = machine()
    last = T0 + 5
    assert fallback.step(last + ESTABLISHED_WITHIN, last) is None
    switched = fallback.step(last + ESTABLISHED_WITHIN + 1, last)
    assert switched is not None and switched.family is V4


def test_single_endpoint_never_switches() -> None:
    (only,) = make_spec().peer_endpoints[1:]
    fallback = Fallback((only,), 30, 600)
    fallback.start(T0)
    assert fallback.step(T0 + 10_000, None) is None
