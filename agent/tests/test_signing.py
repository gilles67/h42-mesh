import base64
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from h42mesh.agent.signing import (
    SigningKeyError,
    TokenSigner,
    generate_key,
    key_from_pem,
    key_to_pem,
    public_key_b64,
)

ROUTER = uuid.UUID("6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f")


def test_key_round_trip() -> None:
    key = generate_key()
    pem = key_to_pem(key)
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert public_key_b64(key_from_pem(pem)) == public_key_b64(key)


def test_public_key_format() -> None:
    raw = base64.b64decode(public_key_b64(generate_key()), validate=True)
    assert len(raw) == 32


def test_not_an_ed25519_key() -> None:
    rsa_pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(SigningKeyError, match="not an Ed25519"):
        key_from_pem(rsa_pem)
    with pytest.raises(SigningKeyError):
        key_from_pem(b"garbage")


def test_token_as_the_controller_checks_it() -> None:
    key = generate_key()
    signer = TokenSigner(key, ROUTER, "h42-mesh-controller")
    token = signer.sign()
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"
    claims = jwt.decode(
        token,
        key.public_key(),
        algorithms=["EdDSA"],
        audience="h42-mesh-controller",
        issuer=str(ROUTER),
        options={"require": ["iss", "sub", "aud", "exp", "jti"]},
    )
    assert claims["sub"] == str(ROUTER)
    assert 55 <= claims["exp"] - time.time() <= 61  # about one minute


def test_each_token_has_its_own_jti() -> None:
    signer = TokenSigner(generate_key(), ROUTER, "aud")
    jtis = {
        jwt.decode(signer.sign(), options={"verify_signature": False})["jti"] for _ in range(50)
    }
    assert len(jtis) == 50


def test_token_signed_by_another_key_is_rejected() -> None:
    token = TokenSigner(generate_key(), ROUTER, "aud").sign()
    other = ed25519.Ed25519PrivateKey.generate().public_key()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other, algorithms=["EdDSA"], audience="aud")


def test_authorization_header() -> None:
    assert TokenSigner(generate_key(), ROUTER, "aud").authorization().startswith("Bearer ey")
