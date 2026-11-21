import pyotp
import pytest

from h42mesh.controller.auth import passwords, totp


def test_password_hash_and_verify() -> None:
    hashed = passwords.hash_password("correct horse")
    assert hashed.startswith("$argon2id$")
    assert passwords.verify_password(hashed, "correct horse")
    assert not passwords.verify_password(hashed, "wrong")
    assert not passwords.verify_password("not a hash", "correct horse")
    assert not passwords.verify_password(None, "anything")  # unknown user


def test_generated_passwords_differ() -> None:
    assert passwords.generate_password() != passwords.generate_password()


def test_secret_validation() -> None:
    assert totp.is_valid_secret(totp.generate_secret())
    assert not totp.is_valid_secret("A" * 31)
    assert not totp.is_valid_secret("a" * 32)  # lowercase
    assert not totp.is_valid_secret("1" * 32)  # not base32


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_matching_step_tolerance(offset: int) -> None:
    secret = totp.generate_secret()
    now = 1_800_000_000.0
    step = int(now // 30) + offset
    assert totp.matching_step(secret, pyotp.TOTP(secret).at(step * 30), None, now) == step


@pytest.mark.parametrize("offset", [-2, 2])
def test_matching_step_outside_tolerance(offset: int) -> None:
    secret = totp.generate_secret()
    now = 1_800_000_000.0
    step = int(now // 30) + offset
    assert totp.matching_step(secret, pyotp.TOTP(secret).at(step * 30), None, now) is None


def test_matching_step_refuses_used_steps() -> None:
    secret = totp.generate_secret()
    now = 1_800_000_000.0
    step = int(now // 30)
    current_code = pyotp.TOTP(secret).at(step * 30)
    assert totp.matching_step(secret, current_code, step - 1, now) == step
    assert totp.matching_step(secret, current_code, step, now) is None


def test_provisioning_uri() -> None:
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", "alice")
    assert uri.startswith("otpauth://totp/h42-mesh:alice?")
    assert "issuer=h42-mesh" in uri
