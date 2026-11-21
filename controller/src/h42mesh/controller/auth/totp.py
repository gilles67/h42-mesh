"""TOTP (RFC 6238): SHA-1, 6 digits, 30-second steps, as common authenticator apps."""

import base64
import binascii
import hmac
import time

import pyotp

ISSUER = "h42-mesh"
DIGITS = 6
INTERVAL = 30
TOLERANCE_STEPS = 1  # clock drift accepted on each side
SECRET_LENGTH = 32  # base32 characters, 160 bits


def _now() -> float:
    """Current time; replaced in tests."""
    return time.time()


def generate_secret() -> str:
    return pyotp.random_base32(length=SECRET_LENGTH)


def is_valid_secret(secret: str) -> bool:
    if len(secret) != SECRET_LENGTH or secret != secret.upper():
        return False
    try:
        base64.b32decode(secret, casefold=False)
    except (binascii.Error, ValueError):
        return False
    return True


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret, digits=DIGITS, interval=INTERVAL).provisioning_uri(
        name=username, issuer_name=ISSUER
    )


def matching_step(
    secret: str, code: str, last_step: int | None, now: float | None = None
) -> int | None:
    """Time step matched by ``code``, or None.

    Steps at or before ``last_step`` are refused, so a code cannot be replayed.
    """
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=INTERVAL)
    current = int((_now() if now is None else now) // INTERVAL)
    for step in range(current - TOLERANCE_STEPS, current + TOLERANCE_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.at(step * INTERVAL), code):
            return step
    return None
