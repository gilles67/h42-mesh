"""Message channel over asyncio streams, and the main side of one instance."""

import asyncio
import contextlib
import itertools
import logging
from uuid import UUID

from h42mesh.agent.ipc.protocol import (
    AnswerMessage,
    AnyMessage,
    CallFailed,
    CallMessage,
    HttpCall,
    HttpResult,
    ProtocolError,
    TunnelsApplied,
    TunnelStatuses,
    decode,
    encode,
)

logger = logging.getLogger(__name__)
HELLO_TIMEOUT = 10.0
CALL_TIMEOUT = 60.0

__all__ = ["CALL_TIMEOUT", "HELLO_TIMEOUT", "AnyMessage", "Channel", "WorkerLink"]


class Channel:
    """One message per line, in both directions."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self._write_lock = asyncio.Lock()

    async def send(self, message: AnyMessage) -> None:
        async with self._write_lock:
            self.writer.write(encode(message))
            await self.writer.drain()

    async def receive(self) -> AnyMessage | None:
        """Next message, or None at the end of the stream."""
        try:
            line = await self.reader.readline()
        except (asyncio.LimitOverrunError, ValueError) as exc:
            raise ProtocolError("message too large") from exc
        if not line:
            return None
        return decode(line)

    async def close(self) -> None:
        self.writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await self.writer.wait_closed()


class WorkerUnavailableError(Exception):
    """The instance is disconnected, failed the call or did not answer in time."""


class WorkerLink:
    """Main-process side of a connected instance: calls with correlated answers."""

    def __init__(self, uid: UUID, channel: Channel) -> None:
        self.uid = uid
        self.channel = channel
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[AnswerMessage]] = {}
        self.closed = asyncio.Event()

    async def read_loop(self) -> None:
        """Dispatch answers until the instance disconnects."""
        answers = (HttpResult, TunnelsApplied, TunnelStatuses, CallFailed)
        try:
            while (message := await self.channel.receive()) is not None:
                if isinstance(message, answers):
                    future = self._pending.pop(message.id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                else:
                    logger.warning("instance %s sent an unexpected %s", self.uid, message.type)
        except (ProtocolError, ConnectionError, OSError) as exc:
            logger.warning("instance %s: %s", self.uid, exc)
        finally:
            self.closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(WorkerUnavailableError(f"instance {self.uid} gone"))
            self._pending.clear()

    async def request[A: AnswerMessage](
        self, message: CallMessage, answer_type: type[A], call_timeout: float = CALL_TIMEOUT
    ) -> A:
        """Send ``message`` (its id is replaced) and wait for its answer."""
        if self.closed.is_set():
            raise WorkerUnavailableError(f"instance {self.uid} is disconnected")
        message = message.model_copy(update={"id": next(self._ids)})
        future: asyncio.Future[AnswerMessage] = asyncio.get_running_loop().create_future()
        self._pending[message.id] = future
        try:
            await self.channel.send(message)
            answer = await asyncio.wait_for(future, call_timeout)
        except (ConnectionError, OSError, TimeoutError) as exc:
            raise WorkerUnavailableError(f"instance {self.uid}: {exc!r}") from exc
        finally:
            self._pending.pop(message.id, None)
        if isinstance(answer, CallFailed):
            raise WorkerUnavailableError(f"instance {self.uid}: {answer.reason}")
        if not isinstance(answer, answer_type):
            raise WorkerUnavailableError(f"instance {self.uid}: unexpected {answer.type}")
        return answer

    async def call(self, call: HttpCall, call_timeout: float = CALL_TIMEOUT) -> HttpResult:
        return await self.request(call, HttpResult, call_timeout)
