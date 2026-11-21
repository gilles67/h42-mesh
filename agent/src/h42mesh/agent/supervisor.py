"""Launching and restarting the connection instances (children of the main process)."""

import asyncio
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from h42mesh.agent.config import ConnectionSettings

logger = logging.getLogger(__name__)

INITIAL_DELAY = 1.0
MAX_DELAY = 60.0
STABLE_AFTER = 300.0  # a run this long resets the delay


def agent_executable() -> list[str]:
    """How to run the agent again (same interpreter, whatever the PATH)."""
    return [sys.executable, "-m", "h42mesh.agent"]


def worker_command(
    settings: ConnectionSettings,
    config_path: Path,
    socket_path: Path,
    executable: Sequence[str] | None = None,
) -> list[str]:
    """``ip vrf exec <vrf> h42-mesh-agent --config … connection-worker <uid> --socket …``"""
    return [
        "ip",
        "vrf",
        "exec",
        settings.vrf,
        *(executable or agent_executable()),
        "--config",
        str(config_path),
        "connection-worker",
        str(settings.uid),
        "--socket",
        str(socket_path),
    ]


@dataclass
class Backoff:
    """Delay before a restart: 1 s, doubled up to 60 s; reset after a stable run."""

    initial: float = INITIAL_DELAY
    maximum: float = MAX_DELAY
    stable_after: float = STABLE_AFTER
    current: float = field(default=0.0)

    def next_delay(self, run_duration: float) -> float:
        if run_duration >= self.stable_after or self.current == 0.0:
            self.current = self.initial
        else:
            self.current = min(self.current * 2, self.maximum)
        return self.current


class Process(Protocol):
    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...


Launcher = Callable[[list[str]], Awaitable[Process]]
VrfCheck = Callable[[str], bool]
Sleep = Callable[[float], Awaitable[None]]


async def launch(argv: list[str]) -> Process:
    process = await asyncio.create_subprocess_exec(*argv)
    return process


class InstanceSupervisor:
    """Keeps one instance per connection running; restarts it when it stops."""

    def __init__(
        self,
        settings: ConnectionSettings,
        command: list[str],
        vrf_exists: VrfCheck,
        launcher: Launcher = launch,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.command = command
        self.vrf_exists = vrf_exists
        self.launcher = launcher
        self.sleep = sleep
        self.clock = clock
        self.backoff = Backoff()
        self.process: Process | None = None
        self.starts = 0
        self._stopping = False

    async def run(self, max_starts: int | None = None) -> None:
        """Until stop() (or ``max_starts`` launches, for tests)."""
        while not self._stopping and (max_starts is None or self.starts < max_starts):
            if not self.vrf_exists(self.settings.vrf):
                # Created by the system configuration, never by the agent.
                logger.error(
                    "VRF %s of connection %s does not exist", self.settings.vrf, self.settings.uid
                )
                await self.sleep(self.backoff.next_delay(0.0))
                continue
            started = self.clock()
            self.starts += 1
            try:
                self.process = await self.launcher(self.command)
            except OSError as exc:
                logger.error("cannot start the instance of %s: %s", self.settings.uid, exc)
                await self.sleep(self.backoff.next_delay(0.0))
                continue
            code = await self.process.wait()
            if self._stopping:
                break
            duration = self.clock() - started
            delay = self.backoff.next_delay(duration)
            logger.warning(
                "instance of %s stopped (code %s) after %.0f s; restart in %.0f s",
                self.settings.uid,
                code,
                duration,
                delay,
            )
            await self.sleep(delay)

    def stop(self) -> None:
        self._stopping = True
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
