"""Authentication of agents: short-lived JWTs signed with their Ed25519 key.

Only EdDSA is accepted (never ``none``, HMAC or another public-key algorithm).
Required claims: ``iss`` = ``sub`` = router UUID, ``aud``, ``exp`` (at most
``agent_jwt_max_lifetime_seconds`` ahead) and ``jti``, recorded against replay.
"""

import base64
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tortoise.exceptions import IntegrityError

from h42mesh.controller.models import Router, UsedJwtId
from h42mesh.controller.settings import Settings

logger = logging.getLogger(__name__)

ALGORITHM = "EdDSA"
MAX_JTI_LENGTH = 128
PURGE_INTERVAL_SECONDS = 60.0
_last_purge = 0.0


class InvalidAgentTokenError(Exception):
    """The JWT is not acceptable; the reason is logged, never returned."""


class RouterRevokedError(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def public_key(signing_public_key: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(signing_public_key))


def _reject(reason: str) -> InvalidAgentTokenError:
    logger.info("agent JWT rejected: %s", reason)
    return InvalidAgentTokenError(reason)


def _unverified_router_id(token: str) -> UUID:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise _reject(f"malformed: {exc}") from exc
    if header.get("alg") != ALGORITHM:
        raise _reject(f"algorithm {header.get('alg')!r} refused")
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError as exc:
        raise _reject(f"malformed: {exc}") from exc
    issuer = claims.get("iss")
    try:
        return UUID(str(issuer))
    except ValueError as exc:
        raise _reject(f"iss {issuer!r} is not a router id") from exc


def _verify(token: str, router: Router, settings: Settings) -> dict[str, Any]:
    assert router.signing_public_key is not None  # noqa: S101 (checked by the caller)
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=public_key(router.signing_public_key),
            algorithms=[ALGORITHM],
            audience=settings.agent_jwt_audience,
            issuer=str(router.id),
            leeway=settings.agent_jwt_leeway_seconds,
            options={"require": ["iss", "sub", "aud", "exp", "jti"]},
        )
    except jwt.InvalidTokenError as exc:
        raise _reject(str(exc)) from exc
    if claims["sub"] != claims["iss"]:
        raise _reject("sub differs from iss")
    jti = claims["jti"]
    if not isinstance(jti, str) or not 0 < len(jti) <= MAX_JTI_LENGTH:
        raise _reject("invalid jti")
    latest = (
        time.time() + settings.agent_jwt_max_lifetime_seconds + settings.agent_jwt_leeway_seconds
    )
    if claims["exp"] > latest:
        raise _reject("exp too far in the future")
    return claims


async def authenticate(token: str, settings: Settings) -> Router:
    """The router that signed ``token``; raises on any problem."""
    router_id = _unverified_router_id(token)
    router = await Router.get_or_none(id=router_id).select_related("site")
    if router is None or router.signing_public_key is None:
        raise _reject("unknown or not enrolled router")
    # Signature first: revocation is only revealed to the key holder.
    claims = _verify(token, router, settings)
    if router.signing_key_revoked:
        logger.info("agent JWT rejected: router %s is revoked", router.id)
        raise RouterRevokedError

    expires_at = datetime.fromtimestamp(claims["exp"], UTC)
    try:
        await UsedJwtId.create(router=router, jti=claims["jti"], expires_at=expires_at)
    except IntegrityError as exc:
        raise _reject("jti already used (replay)") from exc

    router.last_seen_at = now()
    await router.save(update_fields=["last_seen_at"])
    await purge_expired(settings)
    return router


async def purge_expired(settings: Settings, force: bool = False) -> int:
    """Delete used JWT ids past their expiry; at most once a minute per process."""
    global _last_purge
    if not force and time.monotonic() - _last_purge < PURGE_INTERVAL_SECONDS:
        return 0
    _last_purge = time.monotonic()
    limit = now() - timedelta(seconds=settings.agent_jwt_leeway_seconds)
    return await UsedJwtId.filter(expires_at__lt=limit).delete()
