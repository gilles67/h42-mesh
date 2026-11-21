"""GUI sessions: random token in a cookie, only its SHA-256 digest in the database."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response

from h42mesh.controller.models import SessionStage, User, UserSession
from h42mesh.controller.settings import Settings

COOKIE_NAME = "h42_session"
COOKIE_PATH = "/api"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def _lifetime(settings: Settings, stage: SessionStage) -> timedelta:
    minutes = (
        settings.pending_login_minutes
        if stage is SessionStage.TOTP_PENDING
        else settings.session_lifetime_minutes
    )
    return timedelta(minutes=minutes)


async def open_session(
    user: User, stage: SessionStage, settings: Settings
) -> tuple[str, UserSession]:
    """Create a session; returns the cookie token (never stored) and the row."""
    token = secrets.token_urlsafe(32)
    current = now()
    session = await UserSession.create(
        user=user,
        token_hash=token_digest(token),
        stage=stage,
        expires_at=current + _lifetime(settings, stage),
        last_seen_at=current,
    )
    return token, session


async def promote_session(session: UserSession, settings: Settings) -> tuple[str, UserSession]:
    """TOTP verified: replace the pending session by a full one, with a new token."""
    user = await session.user
    await session.delete()
    return await open_session(user, SessionStage.AUTHENTICATED, settings)


def is_expired(session: UserSession, settings: Settings, at: datetime) -> bool:
    idle = timedelta(minutes=settings.session_idle_minutes)
    return at >= session.expires_at or at >= session.last_seen_at + idle


def set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_lifetime_minutes * 60,
        path=COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
