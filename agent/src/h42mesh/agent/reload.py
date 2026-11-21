"""Changes of agent.toml taken into account by the running service, without restart.

The main process checks the modification time of the file every few seconds
(and at once on SIGHUP, sent by ``h42-mesh-agent connection set/remove``). A
valid new configuration is applied:

- connections added or removed: their instances are started or stopped;
- a connection whose VRF changed: its instance is restarted;
- controllers, DNS servers or mesh number changed: every instance is
  restarted (each reads them from the file when it starts);
- the other settings (ports, forced addresses, delays, internal link) are
  used at the next pass of the loop;
- ``state_dir`` cannot change while running: a restart is needed.

An invalid file is refused (logged) and the current configuration stays.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID

from h42mesh.agent.config import AgentConfig, ConfigError, ConnectionSettings, load_config

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5.0


class Supervisor(Protocol):
    """What the reload needs of an InstanceSupervisor."""

    settings: ConnectionSettings

    async def run(self) -> None: ...

    def stop(self) -> None: ...


SupervisorFactory = Callable[[ConnectionSettings], Supervisor]


def _restart_all(old: AgentConfig, new: AgentConfig) -> bool:
    return (old.controllers, old.dns_servers, old.mesh_number) != (
        new.controllers,
        new.dns_servers,
        new.mesh_number,
    )


@dataclass
class Instances:
    """One supervised instance per connection of agent.toml."""

    factory: SupervisorFactory
    running: dict[UUID, tuple[Supervisor, asyncio.Task[None]]] = field(default_factory=dict)

    def start(self, settings: ConnectionSettings) -> None:
        supervisor = self.factory(settings)
        task = asyncio.get_running_loop().create_task(supervisor.run())
        self.running[settings.uid] = (supervisor, task)

    async def stop(self, uid: UUID) -> None:
        supervisor, task = self.running.pop(uid)
        supervisor.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def follow(self, old: AgentConfig | None, new: AgentConfig) -> None:
        wanted = {c.uid: c for c in new.connections}
        everything = old is not None and _restart_all(old, new)
        for uid in list(self.running):
            supervisor = self.running[uid][0]
            settings = wanted.get(uid)
            if settings is None or everything or settings.vrf != supervisor.settings.vrf:
                await self.stop(uid)
            else:
                supervisor.settings = settings
        for uid, settings in wanted.items():
            if uid not in self.running:
                self.start(settings)

    async def stop_all(self) -> None:
        for uid in list(self.running):
            await self.stop(uid)


def refused_change(old: AgentConfig, new: AgentConfig) -> str | None:
    if old.state_dir != new.state_dir:
        return "state_dir changed: restart the service (systemctl restart h42-mesh-agent)"
    return None


@dataclass
class ConfigWatcher:
    """Reloads agent.toml when it changes (or when asked to)."""

    path: Path
    current: AgentConfig
    on_change: Callable[[AgentConfig], Awaitable[None]]
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    check_interval: float = CHECK_INTERVAL
    _mtime: int | None = None

    def __post_init__(self) -> None:
        self._mtime = self._stat()

    def _stat(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    async def check(self, forced: bool = False) -> bool:
        """True if a new configuration was applied."""
        mtime = self._stat()
        if mtime == self._mtime and not forced:
            return False
        self._mtime = mtime
        try:
            new = load_config(self.path)
        except ConfigError as exc:
            logger.error("agent.toml not reloaded, the current settings stay: %s", exc)
            return False
        if new == self.current:
            return False
        refused = refused_change(self.current, new)
        if refused is not None:
            logger.error("agent.toml not reloaded: %s", refused)
            return False
        await self.on_change(new)
        self.current = new
        logger.info("agent.toml reloaded")
        return True

    async def run(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), self.check_interval)
            forced = self.wake.is_set()
            self.wake.clear()
            await self.check(forced)
