"""FastAPI dependencies: settings, session and rights checks."""

from typing import Annotated

from fastapi import Depends, Request, status

from h42mesh.controller.auth.sessions import COOKIE_NAME, is_expired, now, token_digest
from h42mesh.controller.errors import ApiError, not_authenticated
from h42mesh.controller.models import SessionStage, User, UserSession
from h42mesh.controller.schemas.auth import NextStep
from h42mesh.controller.settings import Settings


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_session(request: Request, settings: SettingsDep) -> UserSession:
    """Session of the cookie, with its user; 401 if absent, unknown or expired."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise not_authenticated()
    session = await UserSession.get_or_none(token_hash=token_digest(token)).select_related("user")
    if session is None:
        raise not_authenticated()
    current = now()
    if is_expired(session, settings, current):
        await session.delete()
        raise not_authenticated()
    session.last_seen_at = current
    await session.save(update_fields=["last_seen_at"])
    return session


AnySession = Annotated[UserSession, Depends(get_session)]


async def require_pending_login(session: AnySession) -> UserSession:
    """Password verified, TOTP code expected."""
    if session.stage is not SessionStage.TOTP_PENDING:
        raise not_authenticated()
    return session


async def require_full_session(session: AnySession) -> UserSession:
    """Fully authenticated session, first-login setup possibly unfinished."""
    if session.stage is not SessionStage.AUTHENTICATED:
        raise not_authenticated()
    return session


PendingSession = Annotated[UserSession, Depends(require_pending_login)]
FullSession = Annotated[UserSession, Depends(require_full_session)]


def next_step(user: User) -> NextStep:
    if user.must_change_password:
        return NextStep.CHANGE_PASSWORD
    if user.totp_secret is None:
        return NextStep.SETUP_TOTP
    return NextStep.DONE


async def require_session_user(session: FullSession) -> User:
    """User of a full session; allowed to finish the first-login setup."""
    return session.user


SessionUser = Annotated[User, Depends(require_session_user)]


async def require_user(user: SessionUser) -> User:
    """User allowed to use the API: password changed and TOTP enabled."""
    if next_step(user) is not NextStep.DONE:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "setup_required",
            "Change the password and enable TOTP first",
        )
    return user


CurrentUser = Annotated[User, Depends(require_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise ApiError(status.HTTP_403_FORBIDDEN, "admin_required", "Administrator only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
