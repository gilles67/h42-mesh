"""Main-process registry of the connected instances."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from h42mesh.agent.ipc.channel import HELLO_TIMEOUT, Channel, WorkerLink
from h42mesh.agent.ipc.protocol import Hello, ProtocolError

logger = logging.getLogger(__name__)

OnConnect = Callable[[UUID], Coroutine[Any, Any, None]]


class WorkerHub:
    """Accepts instances on the local socket; one link per connection UID."""

    def __init__(self, expected: set[UUID], on_connect: OnConnect | None = None) -> None:
        self.expected = expected
        self.on_connect = on_connect
        self.links: dict[UUID, WorkerLink] = {}
        self.changed = asyncio.Event()

    def get(self, uid: UUID) -> WorkerLink | None:
        link = self.links.get(uid)
        return None if link is None or link.closed.is_set() else link

    def connected(self) -> set[UUID]:
        return {uid for uid in self.links if self.get(uid) is not None}

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        channel = Channel(reader, writer)
        try:
            hello = await asyncio.wait_for(channel.receive(), HELLO_TIMEOUT)
        except (TimeoutError, ProtocolError, ConnectionError, OSError) as exc:
            logger.warning("local connection refused: %s", exc)
            await channel.close()
            return
        if not isinstance(hello, Hello) or hello.connection_uid not in self.expected:
            logger.warning("local connection refused: unexpected hello %r", hello)
            await channel.close()
            return

        uid = hello.connection_uid
        previous = self.links.get(uid)
        if previous is not None:
            await previous.channel.close()
        link = WorkerLink(uid, channel)
        self.links[uid] = link
        self.changed.set()
        logger.info("instance of connection %s connected (pid %d)", uid, hello.pid)
        if self.on_connect is not None:
            asyncio.get_running_loop().create_task(self.on_connect(uid))
        try:
            await link.read_loop()
        finally:
            if self.links.get(uid) is link:
                del self.links[uid]
            self.changed.set()
            await channel.close()
            logger.info("instance of connection %s disconnected", uid)
