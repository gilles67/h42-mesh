"""Messages between the main process and the connection instances.

Over a local Unix socket (not affected by VRFs): one JSON object per line.
The instance connects and introduces itself (``hello``); then the main process
sends requests (``http_call``), each answered by a result or a failure with
the same ``id``.
"""

import base64
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from h42mesh.agent.messages import AddressFamily

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hello(_Message):
    type: Literal["hello"] = "hello"
    connection_uid: UUID
    pid: int


class HttpCall(_Message):
    """A request to the controller, sent through the instance's connection."""

    type: Literal["http_call"] = "http_call"
    id: int
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str = Field(pattern=r"^/[A-Za-z0-9/_\-.]*$")  # absolute path, no query
    headers: dict[str, str] = Field(default_factory=dict)
    body_b64: str | None = None
    family: AddressFamily | None = None  # force one family (address discovery)

    @property
    def body(self) -> bytes | None:
        return None if self.body_b64 is None else base64.b64decode(self.body_b64)


class HttpResult(_Message):
    type: Literal["http_result"] = "http_result"
    id: int
    status: int
    headers: dict[str, str]
    body_b64: str
    controller: str  # origin that answered

    @property
    def body(self) -> bytes:
        return base64.b64decode(self.body_b64)


class CallFailed(_Message):
    """No controller could be reached through this connection (or local error)."""

    type: Literal["call_failed"] = "call_failed"
    id: int
    reason: str


Message = Annotated[Hello | HttpCall | HttpResult | CallFailed, Field(discriminator="type")]
_adapter: TypeAdapter[Message] = TypeAdapter(Message)


class ProtocolError(Exception):
    pass


def encode(message: Hello | HttpCall | HttpResult | CallFailed) -> bytes:
    data = message.model_dump_json().encode() + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message too large ({len(data)} bytes)")
    return data


def decode(line: bytes) -> Hello | HttpCall | HttpResult | CallFailed:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message too large")
    try:
        return _adapter.validate_json(line)
    except ValidationError as exc:
        raise ProtocolError(f"invalid message: {exc}") from exc


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
