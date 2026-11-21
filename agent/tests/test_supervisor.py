"""Supervision of the connection instances (processes replaced by fakes)."""

import uuid
from pathlib import Path

from h42mesh.agent.config import ConnectionSettings
from h42mesh.agent.supervisor import Backoff, InstanceSupervisor, worker_command

SETTINGS = ConnectionSettings(uid=uuid.UUID(int=7), interface="eth1", vrf="wan0")


def test_worker_command() -> None:
    command = worker_command(
        SETTINGS,
        Path("/etc/h42-mesh/agent.toml"),
        Path("/run/h42-mesh/agent.sock"),
        executable=["/usr/bin/h42-mesh-agent"],
    )
    assert command == [
        "ip",
        "vrf",
        "exec",
        "wan0",
        "/usr/bin/h42-mesh-agent",
        "--config",
        str(Path("/etc/h42-mesh/agent.toml")),
        "connection-worker",
        str(SETTINGS.uid),
        "--socket",
        str(Path("/run/h42-mesh/agent.sock")),
    ]


def test_backoff() -> None:
    backoff = Backoff()
    delays = [backoff.next_delay(1.0) for _ in range(9)]
    assert delays == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert backoff.next_delay(301.0) == 1  # stable run: reset


class FakeProcess:
    def __init__(self, code: int) -> None:
        self._code = code
        self.terminated = False

    @property
    def returncode(self) -> int | None:
        return None if not self.terminated else self._code

    async def wait(self) -> int:
        return self._code

    def terminate(self) -> None:
        self.terminated = True


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_instance_is_restarted_with_growing_delays() -> None:
    launched: list[list[str]] = []

    async def launcher(argv: list[str]) -> FakeProcess:
        launched.append(argv)
        return FakeProcess(1)

    clock = Clock()
    supervisor = InstanceSupervisor(
        SETTINGS, ["cmd"], lambda vrf: True, launcher=launcher, sleep=clock.sleep, clock=clock
    )
    await supervisor.run(max_starts=4)
    assert launched == [["cmd"]] * 4
    assert clock.sleeps == [1, 2, 4, 8]


async def test_missing_vrf_is_reported_and_not_created() -> None:
    checks: list[str] = []
    launched: list[list[str]] = []

    def vrf_exists(name: str) -> bool:
        checks.append(name)
        return len(checks) > 2  # appears after two checks

    async def launcher(argv: list[str]) -> FakeProcess:
        launched.append(argv)
        return FakeProcess(0)

    clock = Clock()
    supervisor = InstanceSupervisor(
        SETTINGS, ["cmd"], vrf_exists, launcher=launcher, sleep=clock.sleep, clock=clock
    )
    await supervisor.run(max_starts=1)
    assert checks == ["wan0", "wan0", "wan0"]
    assert launched == [["cmd"]]


async def test_launch_failure_is_retried() -> None:
    attempts = 0

    async def launcher(argv: list[str]) -> FakeProcess:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FileNotFoundError("ip")
        return FakeProcess(0)

    clock = Clock()
    supervisor = InstanceSupervisor(
        SETTINGS, ["cmd"], lambda vrf: True, launcher=launcher, sleep=clock.sleep, clock=clock
    )
    await supervisor.run(max_starts=2)
    assert attempts == 2


async def test_stop_terminates_the_instance() -> None:
    process = FakeProcess(0)

    async def launcher(argv: list[str]) -> FakeProcess:
        supervisor.stop()
        return process

    supervisor = InstanceSupervisor(SETTINGS, ["cmd"], lambda vrf: True, launcher=launcher)
    await supervisor.run()
    assert supervisor.starts == 1
