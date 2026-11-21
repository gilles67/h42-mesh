"""Test agent: Ed25519 key, JWT forging (good and bad), authenticated calls."""

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from httpx2 import Response

from api_helpers import API, World, use_token

AUDIENCE = "h42-mesh-controller"


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode()


@dataclass
class Agent:
    router_id: str
    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def public_key(self) -> str:
        return public_key_b64(self.key)

    def claims(self, **overrides: Any) -> dict[str, Any]:
        claims: dict[str, Any] = {
            "iss": self.router_id,
            "sub": self.router_id,
            "aud": AUDIENCE,
            "exp": int(time.time()) + 60,
            "jti": str(uuid.uuid4()),
        }
        claims.update(overrides)
        return {k: v for k, v in claims.items() if v is not None}

    def token(self, key: Ed25519PrivateKey | None = None, **overrides: Any) -> str:
        """A JWT signed with EdDSA; a claim set to None is left out."""
        return jwt.encode(self.claims(**overrides), key or self.key, algorithm="EdDSA")


def unsigned_token(claims: dict[str, Any]) -> str:
    """``alg: none`` JWT (no signature)."""

    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


def call(client: TestClient, token: str | None, path: str = "/agent/me") -> Response:
    use_token(client, None)  # agents have no session cookie
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.get(f"{API}{path}", headers=headers)


def create_token(world: World, router_id: str | None = None) -> str:
    response = world.as_("manager").post(
        f"{API}/routers/{router_id or world.ids['router']}/enrollment-tokens"
    )
    assert response.status_code == 201, response.text
    token: str = response.json()["token"]
    return token


def enroll(client: TestClient, token: str, public_key: str) -> Response:
    use_token(client, None)
    return client.post(
        f"{API}/agent/enroll", json={"token": token, "signing_public_key": public_key}
    )


def enrolled_agent(world: World) -> Agent:
    agent = Agent(router_id="")
    response = enroll(world.client, create_token(world), agent.public_key)
    assert response.status_code == 200, response.text
    agent.router_id = response.json()["router_id"]
    return agent
