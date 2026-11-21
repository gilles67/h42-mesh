"""The agent's message models against the controller's OpenAPI description.

Fails when the controller changes a message in a way the agent cannot follow:
regenerate openapi/controller.json, then adapt h42mesh.agent.messages.
"""

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from h42mesh.agent import messages
from h42mesh.agent.messages import API_PREFIX, ENDPOINTS, Request, Response
from openapi_compat import Direction, agent_node, compare, server_node

OPENAPI_FILE = Path(__file__).resolve().parents[2] / "openapi" / "controller.json"


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    return document


def message_models() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(messages, inspect.isclass)
        if issubclass(obj, (Request, Response)) and obj not in {Request, Response}
    ]


@pytest.mark.parametrize("model", message_models(), ids=lambda m: m.__name__)
def test_model_matches_openapi(openapi: dict[str, Any], model: type[BaseModel]) -> None:
    direction: Direction = "read" if issubclass(model, Response) else "write"
    assert model.__name__ in openapi["components"]["schemas"], "schema missing"
    errors = compare(agent_node(model), server_node(openapi, model.__name__), direction)
    assert errors == []


ENUMS = [
    messages.AddressFamily,
    messages.ConnectionRole,
    messages.DirectMode,
    messages.TunnelSide,
    messages.BgpRouteSource,
]


@pytest.mark.parametrize("enum", ENUMS, ids=lambda e: e.__name__)
def test_enumerations_match(openapi: dict[str, Any], enum: type) -> None:
    server = set(openapi["components"]["schemas"][enum.__name__]["enum"])
    assert {member.value for member in enum} == server  # type: ignore[attr-defined]


def _ref_name(schema: dict[str, Any] | None) -> str | None:
    return schema["$ref"].rsplit("/", 1)[-1] if schema and "$ref" in schema else None


@pytest.mark.parametrize(("method", "path"), list(ENDPOINTS), ids=lambda value: str(value))
def test_endpoints_exist(openapi: dict[str, Any], method: str, path: str) -> None:
    request_model, response_model = ENDPOINTS[(method, path)]
    operation = openapi["paths"].get(API_PREFIX + path, {}).get(method.lower())
    assert operation is not None, f"{method} {API_PREFIX}{path} not in the OpenAPI description"

    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    assert _ref_name(body.get("schema")) == (request_model.__name__ if request_model else None)

    success = {code: r for code, r in operation["responses"].items() if code.startswith("2")}
    (response,) = success.values()
    content = response.get("content", {}).get("application/json", {})
    assert _ref_name(content.get("schema")) == (response_model.__name__ if response_model else None)


# --- the comparison itself ---------------------------------------------------


def test_comparison_detects_incompatibilities(openapi: dict[str, Any]) -> None:
    """Deliberately wrong models must be reported."""

    class AgentIdentity(Response):  # reads a field the controller does not send
        router_id: str
        hostname: str

    class PublicAddressResult(Response):  # isp may be null on the controller side
        family: messages.AddressFamily
        address: str
        isp: str

    class EnrollRequest(Request):  # forgets a required field
        token: str

    class PublicAddressReport(Request):  # sends an unknown field
        connection_id: str
        family: str
        forced_address: str | None = None
        comment: str

    class ConfigConnection(Response):  # misses a role value the controller sends
        role: str
        number: str  # wrong type

    def errors(model: type[BaseModel], direction: str) -> list[str]:
        return compare(agent_node(model), server_node(openapi, model.__name__), direction)  # type: ignore[arg-type]

    assert errors(AgentIdentity, "read") == ["hostname: unknown to the controller"]
    assert errors(PublicAddressResult, "read") == ["isp: the controller may send null"]
    assert errors(EnrollRequest, "write") == [
        "signing_public_key: required by the controller, not sent by the agent"
    ]
    assert "comment: unknown to the controller" in errors(PublicAddressReport, "write")
    assert errors(ConfigConnection, "read") == ["number: agent string vs controller integer"]


def test_enum_values_unknown_to_the_reader(openapi: dict[str, Any]) -> None:
    from enum import StrEnum

    class Role(StrEnum):
        ACTIVE = "active"

    class ConfigConnection(Response):
        role: Role

    found = compare(agent_node(ConfigConnection), server_node(openapi, "ConfigConnection"), "read")
    assert found == ["role: values unknown to the reader: ['backup']"]
