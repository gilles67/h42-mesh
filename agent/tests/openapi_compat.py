"""Structural comparison of a Pydantic model with an OpenAPI schema.

``read``: the agent reads what the controller sends (responses).
``write``: the agent sends what the controller reads (requests).
Only JSON types, nullability, required fields and enumeration values are
compared; formats and bounds stay the business of each side.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Direction = Literal["read", "write"]
PRIMITIVES = {"string", "integer", "number", "boolean"}


@dataclass
class Node:
    kind: str  # string, integer, number, boolean, enum, object, array, any
    nullable: bool = False
    values: frozenset[object] = frozenset()
    properties: dict[str, "Node"] = field(default_factory=dict)
    required: frozenset[str] = frozenset()
    items: "Node | None" = None


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[-1]]
    return node


def normalize(node: dict[str, Any], defs: dict[str, Any]) -> Node:
    node = _resolve(node, defs)
    if "anyOf" in node or "oneOf" in node:
        options = node.get("anyOf") or node["oneOf"]
        nullable = any(_resolve(o, defs).get("type") == "null" for o in options)
        rest = [normalize(o, defs) for o in options if _resolve(o, defs).get("type") != "null"]
        if len(rest) == 1 or (rest and all(r.kind == rest[0].kind in PRIMITIVES for r in rest)):
            result = rest[0]
        else:
            result = Node(kind="union")
        result.nullable = result.nullable or nullable
        return result
    if "enum" in node:
        return Node(kind="enum", values=frozenset(node["enum"]))
    kind = node.get("type")
    if kind == "object" or "properties" in node:
        return Node(
            kind="object",
            properties={k: normalize(v, defs) for k, v in node.get("properties", {}).items()},
            required=frozenset(node.get("required", [])),
        )
    if kind == "array":
        return Node(kind="array", items=normalize(node.get("items", {}), defs))
    if kind in PRIMITIVES:
        return Node(kind=kind)
    return Node(kind="any")


def agent_node(model: type[BaseModel]) -> Node:
    schema = model.model_json_schema(mode="validation" if _is_response(model) else "serialization")
    return normalize(schema, schema.get("$defs", {}))


def _is_response(model: type[BaseModel]) -> bool:
    return model.model_config.get("extra") == "ignore"


def server_node(openapi: dict[str, Any], name: str) -> Node:
    schemas = openapi["components"]["schemas"]
    return normalize(schemas[name], schemas)


def compare(agent: Node, server: Node, direction: Direction, path: str = "") -> list[str]:
    where = path or "(root)"
    errors: list[str] = []

    if direction == "read" and server.nullable and not agent.nullable:
        errors.append(f"{where}: the controller may send null")
    if direction == "write" and agent.nullable and not server.nullable:
        errors.append(f"{where}: the agent may send null, refused by the controller")

    if agent.kind == "any" or server.kind == "any":
        return errors
    if {agent.kind, server.kind} == {"enum", "string"}:
        unchecked = (agent.kind == "enum") == (direction == "read")
        if unchecked:
            errors.append(f"{where}: enumeration on one side only ({direction})")
        return errors
    if agent.kind != server.kind:
        return [*errors, f"{where}: agent {agent.kind} vs controller {server.kind}"]

    if agent.kind == "enum":
        source, target = (server, agent) if direction == "read" else (agent, server)
        unknown = source.values - target.values
        if unknown:
            errors.append(f"{where}: values unknown to the reader: {sorted(map(str, unknown))}")
    elif agent.kind == "object":
        errors += _compare_objects(agent, server, direction, path)
    elif agent.kind == "array":
        assert agent.items is not None and server.items is not None
        errors += compare(agent.items, server.items, direction, f"{path}[]")
    return errors


def _compare_objects(agent: Node, server: Node, direction: Direction, path: str) -> list[str]:
    errors: list[str] = []
    for name, child in agent.properties.items():
        here = f"{path}.{name}" if path else name
        if name not in server.properties:
            errors.append(f"{here}: unknown to the controller")
            continue
        if direction == "read" and name in agent.required and name not in server.required:
            errors.append(f"{here}: required by the agent, optional for the controller")
        errors += compare(child, server.properties[name], direction, here)
    if direction == "write":
        for name in sorted(server.required - set(agent.properties)):
            here = f"{path}.{name}" if path else name
            errors.append(f"{here}: required by the controller, not sent by the agent")
    return errors
