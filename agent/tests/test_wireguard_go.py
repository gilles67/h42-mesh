"""wireguard-go backend with fake processes and commands (no root needed)."""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from agent_harness import wait_for
from fake_tunnel_backend import key, make_spec
from h42mesh.agent.messages import AddressFamily, TunnelSide
from h42mesh.agent.tunnels.backend import TunnelError, TunnelSpec
from h42mesh.agent.tunnels.wireguard_go import Commands, WireguardGoBackend

T0 = 1_767_225_600.0
NAME = "wd0c0parir0c0"


class FakeProcess:
    def __init__(self, on_exit: Callable[[], None]) -> None:
        self.returncode: int | None = None
        self._done = asyncio.Event()
        self._on_exit = on_exit

    def exit(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
            self._on_exit()  # wireguard-go removes its interface
            self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.exit(-15)

    def kill(self) -> None:
        self.exit(-9)


class FakeCommands:
    def __init__(self) -> None:
        self.present: set[str] = set()
        self.processes: list[FakeProcess] = []
        self.log: list[tuple[Any, ...]] = []
        self.handshake = 0  # latest-handshake given by the dump
        self.endpoint = "(none)"
        self.failing: set[str] = set()  # "start", "ready", "syncconf", "setup"

    async def start_wireguard(self, name: str) -> FakeProcess:
        self.log.append(("start", name))
        if "start" in self.failing:
            raise TunnelError("cannot start")
        process = FakeProcess(lambda: self.present.discard(name))
        self.processes.append(process)
        self.present.add(name)
        return process

    async def wait_ready(self, name: str, process: Any) -> None:
        self.log.append(("ready", name))
        if "ready" in self.failing:
            raise TunnelError("not ready")

    async def wg(self, *args: str, stdin: str | None = None) -> str:
        self.log.append(("wg", *args, stdin))
        if args[0] in self.failing:
            raise TunnelError(f"wg {args[0]} failed")
        if args[0] == "show":
            return (
                f"{key(1)}\t{key(4)}\t42001\toff\n"
                f"{key(2)}\t{key(3)}\t{self.endpoint}\t0.0.0.0/0,::/0\t{self.handshake}\t10\t20\t25\n"
            )
        return ""

    async def setup_interface(self, spec: TunnelSpec) -> None:
        self.log.append(("setup", spec.name, spec.local_ipv4, spec.local_ipv6))
        if "setup" in self.failing:
            raise TunnelError("setup failed")

    async def interfaces(self) -> list[str]:
        return sorted(self.present)

    async def delete_interface(self, name: str) -> None:
        self.log.append(("delete", name))
        self.present.discard(name)

    def wg_calls(self, subcommand: str) -> list[tuple[Any, ...]]:
        return [entry for entry in self.log if entry[0] == "wg" and entry[1] == subcommand]


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def commands() -> FakeCommands:
    return FakeCommands()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def backend(commands: FakeCommands, clock: Clock, sleeps: list[float]) -> WireguardGoBackend:
    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    checked: Commands = commands  # the fake follows the protocol
    return WireguardGoBackend("wd0c0", checked, clock=clock, sleep=sleep, monitor_interval=0.01)


# --- create ------------------------------------------------------------------


async def test_create(backend: WireguardGoBackend, commands: FakeCommands) -> None:
    spec = make_spec()
    await backend.create(spec)
    steps = [entry[0] if entry[0] != "wg" else entry[1] for entry in commands.log]
    assert steps == ["start", "ready", "setup", "syncconf"]
    ((_, _, name, path, text),) = commands.wg_calls("syncconf")
    assert (name, path) == (NAME, "/dev/stdin")
    assert "Endpoint = [2001:db8::1]:42000" in text  # IPv6 first
    assert f"PresharedKey = {key(3)}" in text
    assert await backend.list() == [NAME]
    await backend.close()


async def test_secrets_never_in_arguments(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    await backend.create(make_spec())
    await backend.update(make_spec(peer_endpoints=make_spec().peer_endpoints[1:]))
    for entry in commands.log:
        arguments = " ".join(str(a) for a in (entry[:-1] if entry[0] == "wg" else entry))
        assert key(1) not in arguments and key(3) not in arguments
    await backend.close()


async def test_create_twice_is_refused(backend: WireguardGoBackend) -> None:
    await backend.create(make_spec())
    with pytest.raises(TunnelError, match="already exists"):
        await backend.create(make_spec())
    await backend.close()


async def test_left_over_interface_is_replaced(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    commands.present.add(NAME)
    await backend.create(make_spec())
    assert commands.log[0] == ("delete", NAME)
    await backend.close()


@pytest.mark.parametrize("failing", ["ready", "setup", "syncconf"])
async def test_failed_creation_leaves_nothing(
    backend: WireguardGoBackend, commands: FakeCommands, failing: str
) -> None:
    commands.failing.add(failing)
    with pytest.raises(TunnelError):
        await backend.create(make_spec())
    assert commands.processes[0].returncode is not None
    assert commands.present == set()
    assert await backend.list() == []


async def test_tunnel_of_another_connection(backend: WireguardGoBackend) -> None:
    with pytest.raises(TunnelError, match="not a tunnel of this connection"):
        await backend.create(make_spec(name="wd0c1parir0c0"))


# --- update and delete -------------------------------------------------------


async def test_update_without_change(backend: WireguardGoBackend, commands: FakeCommands) -> None:
    await backend.create(make_spec())
    commands.log.clear()
    await backend.update(make_spec())
    assert commands.log == []
    await backend.close()


async def test_update_of_the_peer_key(backend: WireguardGoBackend, commands: FakeCommands) -> None:
    await backend.create(make_spec())
    commands.log.clear()
    await backend.update(make_spec(peer_public_key=key(5)))
    assert [e[1] for e in commands.log] == ["syncconf"]  # syncconf replaces the peer
    assert f"PublicKey = {key(5)}" in commands.log[0][-1]
    await backend.close()


async def test_update_of_the_endpoints_forces_a_handshake(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    await backend.create(make_spec())
    commands.log.clear()
    ipv4_only = make_spec().peer_endpoints[1:]
    await backend.update(make_spec(peer_endpoints=ipv4_only))
    assert commands.log[0][:6] == ("wg", "set", NAME, "peer", key(2), "remove")
    assert "Endpoint = 198.51.100.1:42000" in commands.log[1][-1]
    await backend.close()


async def test_update_of_the_addresses(backend: WireguardGoBackend, commands: FakeCommands) -> None:
    import ipaddress

    await backend.create(make_spec())
    commands.log.clear()
    await backend.update(make_spec(local_ipv4=ipaddress.IPv4Interface("169.254.20.1/31")))
    assert commands.log[0][0] == "setup"
    await backend.close()


async def test_update_of_an_unknown_tunnel(backend: WireguardGoBackend) -> None:
    with pytest.raises(TunnelError, match="not managed"):
        await backend.update(make_spec())


async def test_delete(backend: WireguardGoBackend, commands: FakeCommands) -> None:
    await backend.create(make_spec())
    await backend.delete(NAME)
    assert commands.processes[0].returncode == -15
    assert await backend.list() == []
    assert await backend.status(NAME) is None


async def test_delete_a_left_over_interface(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    commands.present.add(NAME)
    await backend.delete(NAME)
    assert commands.present == set()


async def test_list_only_the_connection(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    commands.present |= {"eth0", "wd0c1parir0c0", "wd0c0oldsr0c0"}
    assert await backend.list() == ["wd0c0oldsr0c0"]
    status = await backend.status("wd0c0oldsr0c0")
    assert status is not None and status.tunnel_id is None


async def test_close_stops_every_tunnel(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    await backend.create(make_spec())
    await backend.create(make_spec(name="wd0c0rootr0c0", listen_port=42002))
    await backend.close()
    assert all(p.returncode is not None for p in commands.processes)
    assert await backend.list() == []


# --- supervision -------------------------------------------------------------


async def test_stopped_process_is_restarted(
    backend: WireguardGoBackend, commands: FakeCommands, sleeps: list[float]
) -> None:
    await backend.create(make_spec())
    commands.processes[0].exit(2)
    await wait_for(lambda: len(commands.wg_calls("syncconf")) == 2)
    assert len(commands.processes) == 2 and sleeps == [1.0]
    status = await backend.status(NAME)
    assert status is not None and status.running and status.restarts == 1
    await backend.close()


async def test_restart_is_retried_with_a_longer_delay(
    backend: WireguardGoBackend, commands: FakeCommands, sleeps: list[float]
) -> None:
    await backend.create(make_spec())
    commands.failing.add("start")
    commands.processes[0].exit(1)
    await wait_for(lambda: len(sleeps) >= 3)
    assert sleeps[:3] == [1.0, 2.0, 4.0]
    commands.failing.clear()
    await wait_for(lambda: len(commands.processes) == 2)
    await backend.close()


# --- status and fallback -----------------------------------------------------


async def test_status(backend: WireguardGoBackend, commands: FakeCommands, clock: Clock) -> None:
    await backend.create(make_spec())
    commands.endpoint, commands.handshake = "198.51.100.1:42000", int(T0) - 10
    status = await backend.status(NAME)
    assert status is not None
    assert (status.running, status.family_in_use) == (True, AddressFamily.IPV4)
    assert (status.rx_bytes, status.tx_bytes) == (10, 20)
    clock.now = T0 + 3600  # no handshake for an hour
    status = await backend.status(NAME)
    assert status is not None and status.family_in_use is None
    await backend.close()


async def test_status_of_a_stopped_process(
    backend: WireguardGoBackend, commands: FakeCommands
) -> None:
    commands_sleep = asyncio.Event()

    async def blocked(delay: float) -> None:
        await commands_sleep.wait()

    backend.sleep = blocked
    await backend.create(make_spec())
    commands.processes[0].exit(1)
    await wait_for(lambda: NAME not in commands.present)
    status = await backend.status(NAME)
    assert status is not None and not status.running
    assert await backend.list() == [NAME]  # still managed while restarting
    await backend.close()


async def test_fallback_to_ipv4(
    backend: WireguardGoBackend, commands: FakeCommands, clock: Clock
) -> None:
    await backend.create(make_spec(fallback_delay=30))
    clock.now = T0 + 29
    await asyncio.sleep(0.05)
    assert commands.wg_calls("set") == []
    clock.now = T0 + 30
    await wait_for(lambda: len(commands.wg_calls("syncconf")) == 2)
    assert commands.wg_calls("set")[0][2:6] == (NAME, "peer", key(2), "remove")
    assert "Endpoint = 198.51.100.1:42000" in commands.wg_calls("syncconf")[1][-1]
    await backend.close()


async def test_no_fallback_with_a_handshake(
    backend: WireguardGoBackend, commands: FakeCommands, clock: Clock
) -> None:
    await backend.create(make_spec())
    commands.handshake = int(T0) + 2
    clock.now = T0 + 60
    await asyncio.sleep(0.05)
    assert commands.wg_calls("set") == []
    await backend.close()


async def test_side_a_has_no_fallback(
    backend: WireguardGoBackend, commands: FakeCommands, clock: Clock
) -> None:
    await backend.create(make_spec(side=TunnelSide.A))
    clock.now = T0 + 3600
    await asyncio.sleep(0.05)
    assert commands.wg_calls("show") == []
    assert "Endpoint" not in commands.wg_calls("syncconf")[0][-1]
    await backend.close()
