"""Tunnel backend with wireguard-go: one process per tunnel.

- ``wireguard-go -f <iface>`` runs as a child of the connection instance, so
  in the VRF of the connection (inherited from ``ip vrf exec``); its interface
  stays in the default VRF;
- configured with ``wg syncconf`` (secrets on the standard input);
- addresses of the tunnel, loose rp_filter, interface up (netlink);
- supervised: restarted with an increasing delay if it stops, then the whole
  configuration is applied again;
- on side b, IPv6 → IPv4 fallback (see fallback.py), checked every few seconds.

Every access to the system goes through ``Commands``, replaced in the tests.
"""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from h42mesh.agent.supervisor import Backoff
from h42mesh.agent.tunnels import netlink
from h42mesh.agent.tunnels.backend import (
    PeerEndpoint,
    TunnelError,
    TunnelSpec,
    TunnelStatus,
)
from h42mesh.agent.tunnels.fallback import ESTABLISHED_WITHIN, Fallback
from h42mesh.agent.tunnels.wg import DumpError, endpoint_family, parse_dump, render_config

logger = logging.getLogger(__name__)

UAPI_DIR = Path("/var/run/wireguard")
UAPI_TIMEOUT = 10.0
STOP_TIMEOUT = 5.0
MONITOR_INTERVAL = 5.0


class Process(Protocol):
    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class Commands(Protocol):
    """System access of the backend."""

    async def start_wireguard(self, name: str) -> Process: ...

    async def wait_ready(self, name: str, process: Process) -> None: ...

    async def wg(self, *args: str, stdin: str | None = None) -> str: ...

    async def setup_interface(self, spec: TunnelSpec) -> None: ...

    async def interfaces(self) -> list[str]: ...

    async def delete_interface(self, name: str) -> None: ...


class SystemCommands:
    """The real programs: wireguard-go, wg, and netlink through pyroute2."""

    def __init__(self, wireguard_go: str = "wireguard-go", wg: str = "wg") -> None:
        self.wireguard_go = wireguard_go
        self.wg_program = wg

    async def start_wireguard(self, name: str) -> Process:
        try:
            return await asyncio.create_subprocess_exec(
                self.wireguard_go,
                "-f",
                name,
                stdin=asyncio.subprocess.DEVNULL,
                env={**os.environ, "LOG_LEVEL": "error"},
            )
        except OSError as exc:
            raise TunnelError(f"{name}: cannot start {self.wireguard_go}: {exc}") from exc

    async def wait_ready(self, name: str, process: Process) -> None:
        """Until the UAPI socket of the process exists."""
        socket = UAPI_DIR / f"{name}.sock"
        async with asyncio.timeout(UAPI_TIMEOUT):
            while not socket.exists():  # no notification available
                if process.returncode is not None:
                    raise TunnelError(f"{name}: wireguard-go stopped ({process.returncode})")
                await asyncio.sleep(0.05)

    async def wg(self, *args: str, stdin: str | None = None) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.wg_program,
                *args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise TunnelError(f"cannot run {self.wg_program}: {exc}") from exc
        out, err = await process.communicate(stdin.encode() if stdin is not None else None)
        if process.returncode != 0:
            # Only the subcommand: the arguments never hold secrets, but keep it short.
            raise TunnelError(f"wg {args[0]} {args[1]}: {err.decode(errors='replace').strip()}")
        return out.decode()

    async def setup_interface(self, spec: TunnelSpec) -> None:
        try:
            await asyncio.to_thread(
                netlink.setup_interface, spec.name, [spec.local_ipv4, spec.local_ipv6]
            )
        except (OSError, LookupError) as exc:
            raise TunnelError(f"{spec.name}: {exc}") from exc

    async def interfaces(self) -> list[str]:
        return await asyncio.to_thread(netlink.link_names)

    async def delete_interface(self, name: str) -> None:
        try:
            await asyncio.to_thread(netlink.delete_link, name)
        except OSError as exc:
            raise TunnelError(f"{name}: {exc}") from exc


@dataclass
class _Tunnel:
    spec: TunnelSpec
    fallback: Fallback | None = None
    endpoint: PeerEndpoint | None = None
    process: Process | None = None
    started: float = 0.0
    restarts: int = 0
    backoff: Backoff = field(default_factory=Backoff)
    task: asyncio.Task[None] | None = None


def _fallback(spec: TunnelSpec) -> Fallback | None:
    if not spec.peer_endpoints:
        return None
    return Fallback(spec.peer_endpoints, spec.fallback_delay, spec.ipv6_retry)


class WireguardGoBackend:
    """Tunnels of one connection, named ``<prefix>…`` (``wd<mesh>c<connection>``)."""

    def __init__(
        self,
        prefix: str,
        commands: Commands | None = None,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monitor_interval: float = MONITOR_INTERVAL,
    ) -> None:
        self.prefix = prefix
        self.commands: Commands = commands or SystemCommands()
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.monitor_interval = monitor_interval
        self._tunnels: dict[str, _Tunnel] = {}

    # --- interface -----------------------------------------------------------

    async def create(self, spec: TunnelSpec) -> None:
        self._check_name(spec.name)
        if spec.name in self._tunnels:
            raise TunnelError(f"{spec.name}: already exists")
        if spec.name in await self.commands.interfaces():
            # Left by a previous instance: its process is not ours, start again.
            logger.info("%s: removing a tunnel left over", spec.name)
            await self.commands.delete_interface(spec.name)
        tunnel = _Tunnel(spec=spec, fallback=_fallback(spec))
        await self._start(tunnel)
        self._tunnels[spec.name] = tunnel
        tunnel.task = asyncio.get_running_loop().create_task(self._supervise(tunnel))
        logger.info("%s: created (port %d)", spec.name, spec.listen_port)

    async def update(self, spec: TunnelSpec) -> None:
        tunnel = self._tunnels.get(spec.name)
        if tunnel is None:
            raise TunnelError(f"{spec.name}: not managed by this instance")
        old, tunnel.spec = tunnel.spec, spec
        if old == spec:
            return
        restart_fallback = (old.peer_endpoints, old.fallback_delay, old.ipv6_retry) != (
            spec.peer_endpoints,
            spec.fallback_delay,
            spec.ipv6_retry,
        )
        if restart_fallback:
            tunnel.fallback = _fallback(spec)
            tunnel.endpoint = None
        if tunnel.process is None or tunnel.process.returncode is not None:
            return  # being restarted: the new spec is applied at the start
        if (old.local_ipv4, old.local_ipv6) != (spec.local_ipv4, spec.local_ipv6):
            await self.commands.setup_interface(spec)
        if restart_fallback and tunnel.fallback is not None:
            tunnel.endpoint = tunnel.fallback.start(self.clock())
        await self._configure(tunnel, force_handshake=restart_fallback and bool(tunnel.endpoint))
        logger.info("%s: updated", spec.name)

    async def delete(self, name: str) -> None:
        self._check_name(name)
        tunnel = self._tunnels.pop(name, None)
        if tunnel is not None:
            if tunnel.task is not None:
                tunnel.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tunnel.task
            await self._stop_process(tunnel)
        if name in await self.commands.interfaces():
            await self.commands.delete_interface(name)
        logger.info("%s: deleted", name)

    async def status(self, name: str) -> TunnelStatus | None:
        tunnel = self._tunnels.get(name)
        if tunnel is None:
            if name.startswith(self.prefix) and name in await self.commands.interfaces():
                return TunnelStatus(name=name, tunnel_id=None, running=True)
            return None
        running = tunnel.process is not None and tunnel.process.returncode is None
        base = TunnelStatus(
            name=name, tunnel_id=tunnel.spec.tunnel_id, running=False, restarts=tunnel.restarts
        )
        if not running:
            return base
        try:
            dump = parse_dump(await self.commands.wg("show", name, "dump"))
        except (TunnelError, DumpError) as exc:
            logger.warning("%s: %s", name, exc)
            return base
        peer = dump.peers[0] if dump.peers else None
        if peer is None:
            return base.model_copy(update={"running": True})
        recent = (
            peer.latest_handshake is not None
            and self.clock() - peer.latest_handshake <= ESTABLISHED_WITHIN
        )
        return base.model_copy(
            update={
                "running": True,
                "family_in_use": endpoint_family(peer.endpoint) if recent else None,
                "endpoint": peer.endpoint,
                "last_handshake_at": peer.last_handshake_at,
                "rx_bytes": peer.rx_bytes,
                "tx_bytes": peer.tx_bytes,
            }
        )

    async def list(self) -> list[str]:
        present = {n for n in await self.commands.interfaces() if n.startswith(self.prefix)}
        return sorted(present | set(self._tunnels))  # a tunnel being restarted included

    async def close(self) -> None:
        for name in list(self._tunnels):
            try:
                await self.delete(name)
            except TunnelError as exc:
                logger.warning("%s", exc)

    # --- internals -----------------------------------------------------------

    def _check_name(self, name: str) -> None:
        if not name.startswith(self.prefix):
            raise TunnelError(f"{name}: not a tunnel of this connection ({self.prefix}…)")

    async def _start(self, tunnel: _Tunnel) -> None:
        """Process, interface, configuration; nothing left behind on failure."""
        name = tunnel.spec.name
        tunnel.process = await self.commands.start_wireguard(name)
        tunnel.started = self.monotonic()
        try:
            await self.commands.wait_ready(name, tunnel.process)
            await self.commands.setup_interface(tunnel.spec)
            if tunnel.fallback is not None:
                tunnel.endpoint = tunnel.fallback.start(self.clock())
            await self._configure(tunnel)
        except (TunnelError, TimeoutError) as exc:
            await self._stop_process(tunnel)
            with contextlib.suppress(TunnelError):
                await self.commands.delete_interface(name)
            raise TunnelError(f"{name}: {exc or 'not ready in time'}") from exc

    async def _configure(self, tunnel: _Tunnel, force_handshake: bool = False) -> None:
        spec = tunnel.spec
        if force_handshake:
            # A new peer has no session: the keepalive sent when it is added
            # starts a handshake at once, on the new endpoint.
            await self.commands.wg("set", spec.name, "peer", spec.peer_public_key, "remove")
        await self.commands.wg(
            "syncconf", spec.name, "/dev/stdin", stdin=render_config(spec, tunnel.endpoint)
        )

    async def _stop_process(self, tunnel: _Tunnel) -> None:
        process, tunnel.process = tunnel.process, None
        if process is None or process.returncode is not None:
            return
        process.terminate()  # wireguard-go removes its interface
        try:
            async with asyncio.timeout(STOP_TIMEOUT):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _supervise(self, tunnel: _Tunnel) -> None:
        """Watch the process and the fallback; restart the process when it stops."""
        while True:
            run = 0.0
            if tunnel.process is not None:
                await self._watch(tunnel, tunnel.process)
                run = self.monotonic() - tunnel.started
            delay = tunnel.backoff.next_delay(run)
            logger.warning("%s: wireguard-go stopped; restart in %.0f s", tunnel.spec.name, delay)
            await self.sleep(delay)
            tunnel.restarts += 1
            with contextlib.suppress(TunnelError):
                await self.commands.delete_interface(tunnel.spec.name)
            try:
                await self._start(tunnel)
            except TunnelError as exc:
                logger.error("%s", exc)

    async def _watch(self, tunnel: _Tunnel, process: Process) -> None:
        waiting = asyncio.ensure_future(process.wait())
        try:
            while True:
                done, _ = await asyncio.wait({waiting}, timeout=self.monitor_interval)
                if done:
                    return
                try:
                    await self._monitor(tunnel)
                except (TunnelError, DumpError) as exc:
                    logger.warning("%s: %s", tunnel.spec.name, exc)
        finally:
            waiting.cancel()

    async def _monitor(self, tunnel: _Tunnel) -> None:
        if tunnel.fallback is None or len(tunnel.fallback.endpoints) < 2:
            return
        dump = parse_dump(await self.commands.wg("show", tunnel.spec.name, "dump"))
        handshake = dump.peers[0].latest_handshake if dump.peers else None
        switch = tunnel.fallback.step(self.clock(), handshake)
        if switch is None:
            return
        logger.info("%s: trying %s %s", tunnel.spec.name, switch.family, switch.text())
        tunnel.endpoint = switch
        await self._configure(tunnel, force_handshake=True)
