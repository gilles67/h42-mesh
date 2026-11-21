"""WireGuard X25519 keys of the tunnel ends, generated on the router (as ``wg genkey``)."""

import base64

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_private_key() -> str:
    """Base64 of a new X25519 private key; it never leaves the router."""
    raw = x25519.X25519PrivateKey.generate().private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    return base64.b64encode(raw).decode()


def public_key(private_key: str) -> str:
    """As ``wg pubkey``."""
    key = x25519.X25519PrivateKey.from_private_bytes(base64.b64decode(private_key, validate=True))
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
