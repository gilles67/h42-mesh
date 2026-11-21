"""Login journey of GUI users: first login, two-step login, sessions, limits."""

import logging
from pathlib import Path

import pyotp
import pytest

from api_helpers import (
    ADMIN_NEW_PASSWORD,
    API,
    Env,
    admin_password_from_log,
    code,
    first_login,
    full_login,
    install_clock,
    login,
    make_settings,
    session_token,
    start,
    use_token,
)
from h42mesh.controller.encryption import PassphraseError


def me(env: Env) -> tuple[int, dict[str, object]]:
    response = env.client.get(f"{API}/auth/me")
    return response.status_code, response.json()


# --- administrator created at startup ----------------------------------------


def test_admin_created_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install_clock(monkeypatch)
    settings = make_settings(tmp_path)
    caplog.set_level(logging.INFO, logger="h42mesh")
    for client in start(settings):
        password = admin_password_from_log(caplog)
        assert len(password) >= 20
        assert login(client, "admin", password).json() == {"next_step": "change_password"}
        body = client.get(f"{API}/auth/me").json()
        assert body["is_admin"] is True
        assert body["must_change_password"] is True
        assert body["totp_enabled"] is False

    # A second start on the same database creates and logs nothing.
    caplog.clear()
    for client in start(settings):
        assert login(client, "admin", password).status_code == 200
    assert not [r for r in caplog.records if "administrator created" in r.getMessage()]


# --- first login -------------------------------------------------------------


def test_first_login_journey(env: Env) -> None:
    client = env.client
    response = login(client, "admin", env.admin_password)
    assert response.status_code == 200
    assert response.json() == {"next_step": "change_password"}

    cookie = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/api"):
        assert attribute in cookie

    # Setup not finished: business routes refused.
    response = client.get(f"{API}/users")
    assert response.status_code == 403
    assert response.json()["code"] == "setup_required"

    response = client.post(
        f"{API}/auth/password",
        json={"current_password": env.admin_password, "new_password": ADMIN_NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert me(env)[1]["next_step"] == "setup_totp"
    assert client.get(f"{API}/users").json()["code"] == "setup_required"

    setup = client.post(f"{API}/auth/totp/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/h42-mesh:admin?")
    assert setup["secret"] in setup["otpauth_uri"]

    response = client.post(
        f"{API}/auth/totp/confirm", json={"secret": setup["secret"], "code": "000000"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_totp_code"

    response = client.post(
        f"{API}/auth/totp/confirm",
        json={"secret": setup["secret"], "code": code(setup["secret"], env.clock)},
    )
    assert response.status_code == 204
    status, body = me(env)
    assert status == 200
    assert body["next_step"] == "done"
    assert body["totp_enabled"] is True
    assert client.get(f"{API}/users").status_code == 200

    # TOTP cannot be replaced through setup once enabled.
    assert client.post(f"{API}/auth/totp/setup").json()["code"] == "totp_already_enabled"


def test_totp_confirm_rejects_invalid_secret(env: Env) -> None:
    login(env.client, "admin", env.admin_password)
    response = env.client.post(
        f"{API}/auth/totp/confirm", json={"secret": "a" * 32, "code": "123456"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_totp_secret"


def test_totp_secret_is_encrypted_with_passphrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The stored TOTP secret is checked at startup: a wrong passphrase stops it."""
    clock = install_clock(monkeypatch)
    settings = make_settings(tmp_path)
    caplog.set_level(logging.INFO, logger="h42mesh")
    for client in start(settings):
        password = admin_password_from_log(caplog)
        first_login(client, clock, "admin", password, ADMIN_NEW_PASSWORD)

    assert settings.passphrase_file is not None
    settings.passphrase_file.write_text("another passphrase")
    with pytest.raises(PassphraseError, match="does not decrypt"):
        for _ in start(settings):
            pass


# --- two-step login ----------------------------------------------------------


@pytest.fixture
def secret(env: Env) -> str:
    secret = first_login(env.client, env.clock, "admin", env.admin_password, ADMIN_NEW_PASSWORD)
    env.client.post(f"{API}/auth/logout")
    return secret


def test_two_step_login(env: Env, secret: str) -> None:
    client = env.client
    env.clock.advance(seconds=30)
    assert login(client, "admin", ADMIN_NEW_PASSWORD).json() == {"next_step": "totp"}
    pending_token = session_token(client)

    # Pending session: only the TOTP step is accepted.
    assert me(env)[0] == 401
    assert client.get(f"{API}/users").status_code == 401

    response = client.post(f"{API}/auth/totp", json={"code": "000000"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_totp_code"

    response = client.post(f"{API}/auth/totp", json={"code": code(secret, env.clock)})
    assert response.status_code == 200
    assert response.json() == {"next_step": "done"}
    full_token = session_token(client)
    assert full_token is not None
    assert full_token != pending_token
    assert me(env)[0] == 200

    # The pending token died with the promotion.
    use_token(client, pending_token)
    assert me(env)[0] == 401
    use_token(client, full_token)
    assert me(env)[0] == 200


def test_totp_code_cannot_be_replayed(env: Env, secret: str) -> None:
    client = env.client
    env.clock.advance(seconds=30)
    used = code(secret, env.clock)
    login(client, "admin", ADMIN_NEW_PASSWORD)
    assert client.post(f"{API}/auth/totp", json={"code": used}).status_code == 200
    client.post(f"{API}/auth/logout")

    login(client, "admin", ADMIN_NEW_PASSWORD)
    response = client.post(f"{API}/auth/totp", json={"code": used})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_totp_code"


def test_totp_code_tolerates_one_step_of_drift(env: Env, secret: str) -> None:
    env.clock.advance(seconds=60)
    previous_step = env.clock.current.timestamp() - 30
    login(env.client, "admin", ADMIN_NEW_PASSWORD)
    response = env.client.post(
        f"{API}/auth/totp", json={"code": pyotp.TOTP(secret).at(previous_step)}
    )
    assert response.status_code == 200


def test_malformed_totp_code(env: Env, secret: str) -> None:
    login(env.client, "admin", ADMIN_NEW_PASSWORD)
    assert env.client.post(f"{API}/auth/totp", json={"code": "12345"}).status_code == 422


def test_pending_login_expires(env: Env, secret: str) -> None:
    login(env.client, "admin", ADMIN_NEW_PASSWORD)
    env.clock.advance(minutes=6)
    response = env.client.post(f"{API}/auth/totp", json={"code": code(secret, env.clock)})
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


# --- session lifetime and logout ---------------------------------------------


def test_session_expires_after_inactivity(env: Env, secret: str) -> None:
    assert full_login(env.client, env.clock, "admin", ADMIN_NEW_PASSWORD, secret).is_success
    env.clock.advance(minutes=29)
    assert me(env)[0] == 200  # activity postpones the idle expiry
    env.clock.advance(minutes=29)
    assert me(env)[0] == 200
    env.clock.advance(minutes=31)
    assert me(env)[0] == 401


def test_session_absolute_expiry(env: Env, secret: str) -> None:
    assert full_login(env.client, env.clock, "admin", ADMIN_NEW_PASSWORD, secret).is_success
    for _ in range(12 * 3 - 1):  # active every 20 minutes for almost 12 hours
        env.clock.advance(minutes=20)
        assert me(env)[0] == 200
    env.clock.advance(minutes=20)
    assert me(env)[0] == 401


def test_logout(env: Env, secret: str) -> None:
    client = env.client
    assert full_login(client, env.clock, "admin", ADMIN_NEW_PASSWORD, secret).is_success
    token = session_token(client)
    response = client.post(f"{API}/auth/logout")
    assert response.status_code == 204
    assert 'h42_session=""' in response.headers["set-cookie"]
    assert me(env)[0] == 401
    use_token(client, token)  # the old token is gone server-side too
    assert me(env)[0] == 401
    assert client.post(f"{API}/auth/logout").status_code == 204  # idempotent


def test_unknown_or_forged_cookie(env: Env) -> None:
    use_token(env.client, "forged")
    status, body = me(env)
    assert status == 401
    assert body["code"] == "not_authenticated"


# --- attempt limiting --------------------------------------------------------


def test_unknown_user_gets_the_same_error(env: Env) -> None:
    unknown = login(env.client, "nobody", "whatever")
    wrong = login(env.client, "admin", "wrong password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown.json()["code"] == "invalid_credentials"


def test_lockout_after_failed_passwords(env: Env) -> None:
    for _ in range(5):
        assert login(env.client, "admin", "wrong password").status_code == 401
    response = login(env.client, "admin", env.admin_password)  # right password, still locked
    assert response.status_code == 429
    assert response.json()["code"] == "account_locked"
    assert int(response.headers["retry-after"]) > 14 * 60

    env.clock.advance(minutes=16)
    assert login(env.client, "admin", env.admin_password).status_code == 200


def test_success_resets_the_failure_count(env: Env) -> None:
    for _ in range(4):
        login(env.client, "admin", "wrong password")
    assert login(env.client, "admin", env.admin_password).status_code == 200
    for _ in range(4):
        login(env.client, "admin", "wrong password")
    assert login(env.client, "admin", env.admin_password).status_code == 200


def test_lockout_counts_totp_failures(env: Env, secret: str) -> None:
    env.clock.advance(seconds=30)
    login(env.client, "admin", ADMIN_NEW_PASSWORD)
    for _ in range(5):
        assert env.client.post(f"{API}/auth/totp", json={"code": "000000"}).status_code == 401
    response = env.client.post(f"{API}/auth/totp", json={"code": code(secret, env.clock)})
    assert response.status_code == 429
    assert login(env.client, "admin", ADMIN_NEW_PASSWORD).status_code == 429


# --- password change ---------------------------------------------------------


def test_password_change_rules(env: Env) -> None:
    client = env.client
    login(client, "admin", env.admin_password)

    def change(current: str, new: str) -> tuple[int, str | None]:
        response = client.post(
            f"{API}/auth/password", json={"current_password": current, "new_password": new}
        )
        detail = response.json().get("code") if response.content else None
        return response.status_code, detail

    assert change("wrong password", ADMIN_NEW_PASSWORD) == (400, "invalid_password")
    assert change(env.admin_password, "short")[0] == 422
    assert change(env.admin_password, env.admin_password) == (400, "password_unchanged")
    assert change(env.admin_password, ADMIN_NEW_PASSWORD) == (204, None)
    assert login(client, "admin", env.admin_password).status_code == 401
    assert login(client, "admin", ADMIN_NEW_PASSWORD).status_code == 200


def test_password_change_closes_other_sessions(env: Env) -> None:
    client = env.client
    login(client, "admin", env.admin_password)
    other = session_token(client)
    login(client, "admin", env.admin_password)
    current = session_token(client)
    client.post(
        f"{API}/auth/password",
        json={"current_password": env.admin_password, "new_password": ADMIN_NEW_PASSWORD},
    )
    assert me(env)[0] == 200
    use_token(client, other)
    assert me(env)[0] == 401
    use_token(client, current)
    assert me(env)[0] == 200


def test_request_bodies_reject_unknown_fields(env: Env) -> None:
    response = env.client.post(
        f"{API}/auth/login", json={"username": "admin", "password": "x", "extra": 1}
    )
    assert response.status_code == 422


def test_admin_password_logged_as_warning(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    # Logged while the fixture started the application.
    records = [r for r in caplog.get_records("setup") if "administrator created" in r.getMessage()]
    assert [r.levelno for r in records] == [logging.WARNING]
