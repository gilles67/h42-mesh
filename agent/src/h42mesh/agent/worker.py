"""Connection instance: runs in the VRF of its connection (ip vrf exec).

It connects to the main process over the local socket, introduces itself and
executes the requests it receives:

- requests to the controller, with the built-in DNS client and HTTPS, so that
  they leave through its connection. It never reads state_dir: the main
  process signs the JWTs and passes them in the request headers;
- the wanted tunnels of its connection, reconciled with the tunnel backend
  (whose processes inherit the VRF of the instance), and their states.

The implementation of the tunnel backend is chosen here, and only here.
"""

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from uuid import UUID

from h42mesh.agent import system
from h42mesh.agent.config import AgentConfig
from h42mesh.agent.config.names import tunnel_interface_prefix
from h42mesh.agent.ipc.channel import Channel
from h42mesh.agent.ipc.protocol import (
    CallFailed,
    Hello,
    HttpCall,
    HttpResult,
    TunnelsApplied,
    TunnelsApply,
    TunnelStatuses,
    TunnelStatusQuery,
    b64,
)
from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.net.dns import Resolver
from h42mesh.agent.net.https import ControllerClient, ControllerUnreachableError, HttpResponse
from h42mesh.agent.tunnels.backend import TunnelBackend
from h42mesh.agent.tunnels.reconcile import TunnelManager
from h42mesh.agent.tunnels.wireguard_go import WireguardGoBackend

logger = logging.getLogger(__name__)


class Requester(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = ...,
        headers: Mapping[str, str] | None = ...,
        family: AddressFamily | None = ...,
    ) -> HttpResponse: ...


def controller_client(config: AgentConfig) -> ControllerClient:
    resolver = Resolver(list(config.dns_servers), family_available=system.family_available)
    return ControllerClient(list(config.controllers), resolver)


async def execute(call: HttpCall, client: Requester) -> HttpResult | CallFailed:
    """Run one request in a thread (requests and dnspython are blocking)."""
    try:
        response = await asyncio.to_thread(
            client.request,
            call.method,
            call.path,
            body=call.body,
            headers=call.headers,
            family=call.family,
        )
    except ControllerUnreachableError as exc:
        return CallFailed(id=call.id, reason=str(exc))
    except Exception as exc:  # report any local failure instead of dying
        logger.exception("request %s %s failed", call.method, call.path)
        return CallFailed(id=call.id, reason=f"{type(exc).__name__}: {exc}")
    return HttpResult(
        id=call.id,
        status=response.status,
        headers=response.headers,
        body_b64=b64(response.body),
        controller=response.controller,
    )


BackendFactory = Callable[[str], TunnelBackend]  # interface prefix -> backend


def default_backend(prefix: str) -> TunnelBackend:
    """The tunnel backend in use: wireguard-go."""
    return WireguardGoBackend(prefix)


class InstanceTunnels:
    """Tunnels of the connection; the backend is created at the first request,
    when the number of the connection (in the interface names) is known."""

    def __init__(self, mesh_number: int, factory: BackendFactory = default_backend) -> None:
        self.mesh_number = mesh_number
        self.factory = factory
        self.manager: TunnelManager | None = None
        self.prefix: str | None = None
        self._lock = asyncio.Lock()

    async def apply(self, message: TunnelsApply) -> TunnelsApplied:
        async with self._lock:
            prefix = tunnel_interface_prefix(self.mesh_number, message.connection_number)
            if self.manager is None or prefix != self.prefix:
                if self.manager is not None:  # renumbered connection
                    await self.manager.close()
                self.manager, self.prefix = TunnelManager(self.factory(prefix)), prefix
            report = await self.manager.reconcile(message.tunnels)
        return TunnelsApplied(
            id=message.id,
            created=report.created,
            updated=report.updated,
            deleted=report.deleted,
            errors=report.errors,
        )

    async def statuses(self, message: TunnelStatusQuery) -> TunnelStatuses:
        async with self._lock:
            found = await self.manager.statuses() if self.manager is not None else []
        return TunnelStatuses(id=message.id, tunnels=found)

    async def close(self) -> None:
        async with self._lock:
            if self.manager is not None:
                await self.manager.close()
                self.manager = None


async def _answer_tunnels(
    message: TunnelsApply | TunnelStatusQuery, tunnels: InstanceTunnels
) -> TunnelsApplied | TunnelStatuses | CallFailed:
    try:
        if isinstance(message, TunnelsApply):
            return await tunnels.apply(message)
        return await tunnels.statuses(message)
    except Exception as exc:  # report any local failure instead of dying
        logger.exception("%s failed", message.type)
        return CallFailed(id=message.id, reason=f"{type(exc).__name__}: {exc}")


async def serve(
    channel: Channel, uid: UUID, client: Requester, tunnels: InstanceTunnels | None = None
) -> None:
    """Introduce the instance, then answer requests until the main process leaves."""
    await channel.send(Hello(connection_uid=uid, pid=os.getpid()))
    tasks: set[asyncio.Task[None]] = set()

    async def answer(message: HttpCall | TunnelsApply | TunnelStatusQuery) -> None:
        if isinstance(message, HttpCall):
            await channel.send(await execute(message, client))
        elif tunnels is None:
            await channel.send(CallFailed(id=message.id, reason="no tunnel management"))
        else:
            await channel.send(await _answer_tunnels(message, tunnels))

    while (message := await channel.receive()) is not None:
        if not isinstance(message, HttpCall | TunnelsApply | TunnelStatusQuery):
            logger.warning("unexpected %s from the main process", message.type)
            continue
        task = asyncio.get_running_loop().create_task(answer(message))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    for task in tasks:
        task.cancel()


ClientFactory = Callable[[AgentConfig], Requester]


async def run_worker(
    config: AgentConfig,
    uid: UUID,
    socket: Path,
    client_factory: ClientFactory = controller_client,
    backend_factory: BackendFactory = default_backend,
) -> int:
    """Entry point of ``h42-mesh-agent connection-worker``: exit when the main process
    closes the socket (the main process restarts the instance if needed)."""
    if uid not in {c.uid for c in config.connections}:
        logger.error("connection %s is not in the local configuration", uid)
        return 2
    reader, writer = await system.open_unix_connection(socket)
    channel = Channel(reader, writer)
    tunnels = InstanceTunnels(config.mesh_number, backend_factory)
    try:
        await serve(channel, uid, client_factory(config), tunnels)
    finally:
        await tunnels.close()  # the tunnels stop with the instance
        await channel.close()
    return 0
