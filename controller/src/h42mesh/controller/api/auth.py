"""Login (password then TOTP), logout, password change and TOTP setup."""

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status

from h42mesh.controller.api.deps import (
    FullSession,
    PendingSession,
    SessionUser,
    SettingsDep,
    next_step,
)
from h42mesh.controller.auth import passwords, totp
from h42mesh.controller.auth.sessions import (
    COOKIE_NAME,
    clear_cookie,
    now,
    open_session,
    promote_session,
    set_cookie,
    token_digest,
)
from h42mesh.controller.encryption import decrypt_secret, encrypt_secret
from h42mesh.controller.errors import ApiError, error_responses
from h42mesh.controller.models import SessionStage, User, UserSession
from h42mesh.controller.schemas.auth import (
    CurrentUser,
    LoginRequest,
    LoginResponse,
    NextStep,
    PasswordChangeRequest,
    TotpCodeRequest,
    TotpConfirmRequest,
    TotpSetupResponse,
)
from h42mesh.controller.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


# --- attempt limiting --------------------------------------------------------


def _check_not_locked(user: User) -> None:
    current = now()
    if user.locked_until is not None and user.locked_until > current:
        retry_after = max(1, int((user.locked_until - current).total_seconds()))
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "account_locked",
            "Too many failed attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )


async def _record_failure(user: User, settings: Settings) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= settings.max_failed_logins:
        user.locked_until = now() + timedelta(minutes=settings.lockout_minutes)
        user.failed_login_count = 0
    await user.save(update_fields=["failed_login_count", "locked_until"])


async def _record_success(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now()
    await user.save(update_fields=["failed_login_count", "locked_until", "last_login_at"])


def _invalid_credentials() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Invalid username or password"
    )


# --- login -------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    responses=error_responses(401, 429),
    summary="Log in with username and password",
)
async def login(body: LoginRequest, response: Response, settings: SettingsDep) -> LoginResponse:
    """First step: opens a session (cookie).

    If the user has TOTP enabled, the session only accepts the TOTP code;
    otherwise (first login) it is limited to the password change and TOTP setup.
    """
    user = await User.get_or_none(username=body.username)
    if user is not None:
        _check_not_locked(user)
    if user is None or not passwords.verify_password(user.password_hash, body.password):
        if user is None:
            passwords.verify_password(None, body.password)  # same work as a real check
        else:
            await _record_failure(user, settings)
        raise _invalid_credentials()
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(body.password)
        await user.save(update_fields=["password_hash"])

    if user.totp_secret is not None:
        token, _ = await open_session(user, SessionStage.TOTP_PENDING, settings)
        step = NextStep.TOTP
    else:
        await _record_success(user)
        token, _ = await open_session(user, SessionStage.AUTHENTICATED, settings)
        step = next_step(user)
    set_cookie(response, token, settings)
    return LoginResponse(next_step=step)


@router.post(
    "/totp",
    response_model=LoginResponse,
    responses=error_responses(401, 429),
    summary="Second login step: TOTP code",
)
async def login_totp(
    body: TotpCodeRequest, session: PendingSession, response: Response, settings: SettingsDep
) -> LoginResponse:
    """Completes the login; the session gets a new token."""
    user = session.user
    _check_not_locked(user)
    if user.totp_secret is None:  # TOTP removed since the password step
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_totp_code", "Invalid TOTP code")
    step = totp.matching_step(decrypt_secret(user.totp_secret), body.code, user.totp_last_step)
    if step is None:
        await _record_failure(user, settings)
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_totp_code", "Invalid TOTP code")
    user.totp_last_step = step
    await user.save(update_fields=["totp_last_step"])
    await _record_success(user)
    token, _ = await promote_session(session, settings)
    set_cookie(response, token, settings)
    return LoginResponse(next_step=next_step(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def logout(request: Request, settings: SettingsDep) -> Response:
    """Deletes the session, if any, and clears the cookie (always succeeds)."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await UserSession.filter(token_hash=token_digest(token)).delete()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_cookie(response, settings)
    return response


# --- current user ------------------------------------------------------------


@router.get(
    "/me", response_model=CurrentUser, responses=error_responses(401), summary="Current user"
)
async def get_me(user: SessionUser) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        can_create_meshes=user.can_create_meshes,
        must_change_password=user.must_change_password,
        totp_enabled=user.totp_secret is not None,
        next_step=next_step(user),
    )


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 429),
    summary="Change the password",
)
async def change_password(
    body: PasswordChangeRequest, session: FullSession, settings: SettingsDep
) -> None:
    """Mandatory at first login. The other sessions of the user are closed."""
    user = session.user
    _check_not_locked(user)
    if not passwords.verify_password(user.password_hash, body.current_password):
        await _record_failure(user, settings)
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_password", "Wrong current password")
    if body.new_password == body.current_password:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "password_unchanged",
            "The new password must differ from the current one",
        )
    user.password_hash = passwords.hash_password(body.new_password)
    user.must_change_password = False
    await user.save(update_fields=["password_hash", "must_change_password"])
    await UserSession.filter(user_id=user.id).exclude(id=session.id).delete()


# --- TOTP setup --------------------------------------------------------------


def _check_totp_not_enabled(user: User) -> None:
    if user.totp_secret is not None:
        raise ApiError(status.HTTP_409_CONFLICT, "totp_already_enabled", "TOTP is already enabled")


@router.post(
    "/totp/setup",
    response_model=TotpSetupResponse,
    responses=error_responses(401, 409),
    summary="Start TOTP setup",
)
async def setup_totp(user: SessionUser) -> TotpSetupResponse:
    """Returns a new secret to show as a QR code; nothing is stored until confirmed."""
    _check_totp_not_enabled(user)
    secret = totp.generate_secret()
    return TotpSetupResponse(
        secret=secret, otpauth_uri=totp.provisioning_uri(secret, user.username)
    )


@router.post(
    "/totp/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 409),
    summary="Confirm TOTP setup with a first code",
)
async def confirm_totp(body: TotpConfirmRequest, user: SessionUser) -> None:
    """Stores the secret, encrypted, once a code generated from it is verified."""
    _check_totp_not_enabled(user)
    if not totp.is_valid_secret(body.secret):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_totp_secret", "Invalid TOTP secret")
    step = totp.matching_step(body.secret, body.code, None)
    if step is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_totp_code", "Invalid TOTP code")
    user.totp_secret = encrypt_secret(body.secret)
    user.totp_last_step = step
    await user.save(update_fields=["totp_secret", "totp_last_step"])
