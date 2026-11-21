"""Main process and instances wired through local streams, with a fake controller.

TCP on 127.0.0.1 stands in for the Unix socket (asyncio has no Unix sockets
on Windows); the protocol and the code are the same.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from h42mesh.agent.ipc.channel import Channel
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.net.https import ControllerUnreachableError, HttpResponse
from h42mesh.agent.worker import InstanceTunnels, serve

Handler = Callable[[dict[str, Any]], HttpResponse]


@dataclass
class FakeController:
    """Requester used by an instance; records every request it executes."""

    handler: Handler
    calls: list[dict[str, Any]] = field(default_factory=list)
    unreachable: bool = False

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: Any = None,
        family: AddressFamily | None = None,
    ) -> HttpResponse:
        call = {
            "method": method,
            "path": path,
            "body": body,
            "headers": dict(headers or {}),
            "family": family,
        }
        self.calls.append(call)
        if self.unreachable:
            raise ControllerUnreachableError("no route")
        return self.handler(call)


def answer(status: int, body: bytes = b"", **headers: str) -> HttpResponse:
    return HttpResponse(status=status, headers=headers, body=body, controller="https://vps1.test")


@contextlib.asynccontextmanager
async def wired(
    hub: WorkerHub,
    instances: dict[UUID, FakeController],
    tunnels: dict[UUID, InstanceTunnels] | None = None,
) -> AsyncIterator[dict[UUID, asyncio.Task[None]]]:
    """Start a local server for ``hub`` and connect one instance per entry
    (with its tunnel management from ``tunnels``, if given)."""
    server = await asyncio.start_server(hub.handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    tasks: dict[UUID, asyncio.Task[None]] = {}
    try:
        for uid, controller in instances.items():
            instance_tunnels = (tunnels or {}).get(uid)
            tasks[uid] = asyncio.create_task(
                connect_instance(port, uid, controller, instance_tunnels)
            )
        await wait_for(lambda: hub.connected() == set(instances))
        yield tasks
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        server.close()


async def connect_instance(
    port: int, uid: UUID, controller: FakeController, tunnels: InstanceTunnels | None = None
) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    channel = Channel(reader, writer)
    try:
        await serve(channel, uid, controller, tunnels)
    finally:
        await channel.close()


async def wait_for(condition: Callable[[], bool], limit: float = 5.0) -> None:
    async with asyncio.timeout(limit):
        while not condition():  # noqa: ASYNC110 (polling test conditions)
            await asyncio.sleep(0.01)
