"""Signing key of the agent (Ed25519) and the JWTs it signs for the controller.

The private key is generated on the router and never leaves it: it is stored
in state_dir/agent.key (PEM, PKCS#8, unencrypted, mode 0600) and only read
by the main process.
"""

import base64
import time
import uuid
from dataclasses import dataclass
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALGORITHM = "EdDSA"
TOKEN_LIFETIME_SECONDS = 60  # the controller refuses more than a few minutes


class SigningKeyError(Exception):
    """agent.key cannot be decoded as an Ed25519 private key."""


def generate_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def key_from_pem(data: bytes) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as exc:
        raise SigningKeyError(f"invalid agent key: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("the agent key is not an Ed25519 key")
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    """Raw 32-byte public key in base64, as the controller stores it."""
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


@dataclass(frozen=True)
class TokenSigner:
    """Signs a fresh JWT for each request: iss = sub = router id, unique jti."""

    key: Ed25519PrivateKey
    router_id: UUID
    audience: str
    lifetime: int = TOKEN_LIFETIME_SECONDS

    def sign(self, now: float | None = None) -> str:
        issued = int(time.time() if now is None else now)
        claims = {
            "iss": str(self.router_id),
            "sub": str(self.router_id),
            "aud": self.audience,
            "iat": issued,
            "exp": issued + self.lifetime,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self.key, algorithm=ALGORITHM)

    def authorization(self) -> str:
        return f"Bearer {self.sign()}"
