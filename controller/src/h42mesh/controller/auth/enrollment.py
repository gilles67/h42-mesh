"""Single-use enrollment tokens: long, random, only their SHA-256 digest stored."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from tortoise.exceptions import IntegrityError

from h42mesh.controller.models import EnrollmentToken, Router, User
from h42mesh.controller.settings import Settings


class InvalidEnrollmentTokenError(Exception):
    """Unknown, expired or already used token (indistinguishable on purpose)."""


class SigningKeyInUseError(Exception):
    """The public key is already the signing key of another router."""


def now() -> datetime:
    return datetime.now(UTC)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(router: Router, user: User, settings: Settings) -> tuple[str, datetime]:
    """New token for a router; its previous unused tokens are deleted.

    Returns the token (shown once, never stored) and its expiry.
    """
    await EnrollmentToken.filter(router_id=router.id, used_at__isnull=True).delete()
    token = secrets.token_urlsafe(32)
    expires_at = now() + timedelta(hours=settings.enrollment_token_hours)
    await EnrollmentToken.create(
        router=router, token_hash=token_digest(token), expires_at=expires_at, created_by=user
    )
    return token, expires_at


async def enroll(token: str, signing_public_key: str) -> Router:
    """Use a token once and attach the agent's Ed25519 public key to its router.

    Re-enrollment replaces the previous key and lifts a revocation.
    """
    current = now()
    record = await EnrollmentToken.get_or_none(token_hash=token_digest(token))
    if record is None or record.used_at is not None or record.expires_at <= current:
        raise InvalidEnrollmentTokenError
    # Atomic single use: only one concurrent request can mark it used.
    marked = await EnrollmentToken.filter(id=record.id, used_at__isnull=True).update(
        used_at=current
    )
    if marked != 1:
        raise InvalidEnrollmentTokenError

    router = await Router.get(id=record.router_id)  # type: ignore[attr-defined]
    if await Router.filter(signing_public_key=signing_public_key).exclude(id=router.id).exists():
        raise SigningKeyInUseError
    router.signing_public_key = signing_public_key
    router.signing_key_revoked = False
    router.enrolled_at = current
    try:
        await router.save(
            update_fields=["signing_public_key", "signing_key_revoked", "enrolled_at"]
        )
    except IntegrityError as exc:
        raise SigningKeyInUseError from exc
    return router
