"""Connection instance: runs in the VRF of its connection (ip vrf exec).

It connects to the main process over the local socket, introduces itself and
executes the requests it receives with the built-in DNS client and HTTPS, so
that they leave through its connection. It never reads state_dir: the main
process signs the JWTs and passes them in the request headers.
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
from h42mesh.agent.ipc.channel import Channel
from h42mesh.agent.ipc.protocol import CallFailed, Hello, HttpCall, HttpResult, b64
from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.net.dns import Resolver
from h42mesh.agent.net.https import ControllerClient, ControllerUnreachableError, HttpResponse

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


async def serve(channel: Channel, uid: UUID, client: Requester) -> None:
    """Introduce the instance, then answer requests until the main process leaves."""
    await channel.send(Hello(connection_uid=uid, pid=os.getpid()))
    tasks: set[asyncio.Task[None]] = set()

    async def answer(call: HttpCall) -> None:
        await channel.send(await execute(call, client))

    while (message := await channel.receive()) is not None:
        if not isinstance(message, HttpCall):
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
) -> int:
    """Entry point of ``h42-mesh-agent connection-worker``: exit when the main process
    closes the socket (the main process restarts the instance if needed)."""
    if uid not in {c.uid for c in config.connections}:
        logger.error("connection %s is not in the local configuration", uid)
        return 2
    reader, writer = await system.open_unix_connection(socket)
    channel = Channel(reader, writer)
    try:
        await serve(channel, uid, client_factory(config))
    finally:
        await channel.close()
    return 0
