"""Messages between the main process and the connection instances.

Over a local Unix socket (not affected by VRFs): one JSON object per line.
The instance connects and introduces itself (``hello``); then the main process
sends requests, each answered with the same ``id`` (or by ``call_failed``):

| Request                 | Answer              |
| ----------------------- | ------------------- |
| ``http_call``           | ``http_result``     |
| ``tunnels_apply``       | ``tunnels_applied`` |
| ``tunnel_status_query`` | ``tunnel_statuses`` |
"""

import base64
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.tunnels.backend import TunnelSpec, TunnelStatus

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


class TunnelsApply(_Message):
    """Every wanted tunnel of the connection: the others are removed."""

    type: Literal["tunnels_apply"] = "tunnels_apply"
    id: int
    connection_number: int = Field(ge=0, le=9)
    tunnels: list[TunnelSpec]


class TunnelsApplied(_Message):
    type: Literal["tunnels_applied"] = "tunnels_applied"
    id: int
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)  # interface name -> error


class TunnelStatusQuery(_Message):
    type: Literal["tunnel_status_query"] = "tunnel_status_query"
    id: int


class TunnelStatuses(_Message):
    type: Literal["tunnel_statuses"] = "tunnel_statuses"
    id: int
    tunnels: list[TunnelStatus]


AnyMessage = (
    Hello
    | HttpCall
    | HttpResult
    | CallFailed
    | TunnelsApply
    | TunnelsApplied
    | TunnelStatusQuery
    | TunnelStatuses
)
CallMessage = HttpCall | TunnelsApply | TunnelStatusQuery  # main process -> instance
AnswerMessage = HttpResult | TunnelsApplied | TunnelStatuses | CallFailed  # instance -> main
Message = Annotated[AnyMessage, Field(discriminator="type")]
_adapter: TypeAdapter[Message] = TypeAdapter(Message)


class ProtocolError(Exception):
    pass


def encode(message: AnyMessage) -> bytes:
    data = message.model_dump_json().encode() + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message too large ({len(data)} bytes)")
    return data


def decode(line: bytes) -> AnyMessage:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message too large")
    try:
        return _adapter.validate_json(line)
    except ValidationError as exc:
        raise ProtocolError(f"invalid message: {exc}") from exc


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
