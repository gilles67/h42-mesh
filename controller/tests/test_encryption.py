import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from factories import Topology, make_tunnel, make_user
from h42mesh.controller import encryption
from h42mesh.controller.encryption import (
    InvalidSecretFormatError,
    PassphraseError,
    SecretBox,
    SecretDecryptionError,
    configure,
    configure_from_settings,
    decrypt_secret,
    encrypt_secret,
    read_passphrase,
    verify_passphrase,
)
from h42mesh.controller.models import Tunnel, User
from h42mesh.controller.settings import Settings

PSK = "dGhpcyBpcyBhIDMyLWJ5dGUgV2lyZUd1YXJkIFBTSyE="  # shape of `wg genpsk`


@pytest.fixture(scope="module")
def box() -> SecretBox:
    # Shared by the module: real scrypt parameters, derived keys stay cached.
    return SecretBox("correct horse battery staple")


@pytest.fixture(autouse=True)
def _reset_module_box() -> Iterator[None]:
    yield
    encryption.reset()


def tampered(payload: dict[str, Any], field: str) -> dict[str, Any]:
    """Flip one bit of a base64 field."""
    raw = bytearray(base64.b64decode(payload[field]))
    raw[0] ^= 1
    return payload | {field: base64.b64encode(bytes(raw)).decode()}


# --- encryption --------------------------------------------------------------


@pytest.mark.parametrize("secret", [PSK, "JBSWY3DPEHPK3PXP", "", "é → ✓"])
def test_round_trip(box: SecretBox, secret: str) -> None:
    assert box.decrypt(box.encrypt(secret)) == secret


def test_encrypted_object_format(box: SecretBox) -> None:
    payload = box.encrypt(PSK)
    assert set(payload) == {"v", "kdf", "salt", "nonce", "ciphertext"}
    assert (payload["v"], payload["kdf"]) == (1, "scrypt")
    assert len(base64.b64decode(payload["salt"])) == 16
    assert len(base64.b64decode(payload["nonce"])) == 12
    assert PSK not in str(payload)


def test_same_secret_gets_different_salt_nonce_and_ciphertext(box: SecretBox) -> None:
    first = box.encrypt(PSK)
    second = box.encrypt(PSK)
    assert first["salt"] != second["salt"]
    assert first["nonce"] != second["nonce"]
    assert first["ciphertext"] != second["ciphertext"]
    assert box.decrypt(first) == box.decrypt(second) == PSK


def test_wrong_passphrase(box: SecretBox) -> None:
    payload = box.encrypt(PSK)
    with pytest.raises(SecretDecryptionError, match="wrong passphrase"):
        SecretBox("wrong passphrase").decrypt(payload)


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "salt"])
def test_altered_object(box: SecretBox, field: str) -> None:
    with pytest.raises(SecretDecryptionError):
        box.decrypt(tampered(box.encrypt(PSK), field))


def test_truncated_ciphertext(box: SecretBox) -> None:
    payload = box.encrypt(PSK)
    raw = base64.b64decode(payload["ciphertext"])[:-1]
    with pytest.raises(SecretDecryptionError):
        box.decrypt(payload | {"ciphertext": base64.b64encode(raw).decode()})


@pytest.mark.parametrize(
    "change",
    [
        {"v": 2},
        {"v": True},
        {"kdf": "argon2id"},
        {"salt": "not base64!"},
        {"nonce": 12},
        {"nonce": base64.b64encode(b"short").decode()},
        {"extra": "x"},
    ],
)
def test_invalid_format(box: SecretBox, change: dict[str, Any]) -> None:
    with pytest.raises(InvalidSecretFormatError):
        box.decrypt(box.encrypt(PSK) | change)


def test_missing_field(box: SecretBox) -> None:
    payload = box.encrypt(PSK)
    del payload["nonce"]
    with pytest.raises(InvalidSecretFormatError):
        box.decrypt(payload)


def test_derived_keys_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real_scrypt = Scrypt

    def counting_scrypt(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_scrypt(**kwargs)

    monkeypatch.setattr(encryption, "Scrypt", counting_scrypt)
    box = SecretBox("passphrase")
    payload = box.encrypt(PSK)  # derives the key for this salt
    box.decrypt(payload)
    box.decrypt(payload)
    assert calls == 1
    box.encrypt(PSK)  # new salt, new derivation
    assert calls == 2


def test_empty_passphrase_rejected() -> None:
    with pytest.raises(PassphraseError):
        SecretBox("")


# --- passphrase file and module functions ------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [("secret\n", "secret"), ("secret\r\n", "secret"), ("  with spaces  ", "  with spaces  ")],
)
def test_read_passphrase(tmp_path: Path, content: str, expected: str) -> None:
    path = tmp_path / "passphrase"
    path.write_bytes(content.encode())
    assert read_passphrase(path) == expected


@pytest.mark.parametrize("content", ["", "\n", "   \n"])
def test_read_passphrase_rejects_empty(tmp_path: Path, content: str) -> None:
    path = tmp_path / "passphrase"
    path.write_text(content)
    with pytest.raises(PassphraseError, match="empty"):
        read_passphrase(path)


def test_read_passphrase_missing_file_or_setting(tmp_path: Path) -> None:
    with pytest.raises(PassphraseError, match="cannot read"):
        read_passphrase(tmp_path / "absent")
    with pytest.raises(PassphraseError, match="not set"):
        read_passphrase(None)


def test_module_functions_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "passphrase"
    path.write_text("from the file\n")
    monkeypatch.setenv("H42_MESH_PASSPHRASE_FILE", str(path))
    configure_from_settings(Settings())
    payload = encrypt_secret(PSK)
    assert decrypt_secret(payload) == PSK
    assert SecretBox("from the file").decrypt(payload) == PSK


def test_module_functions_require_configuration() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        encrypt_secret(PSK)


# --- startup check -----------------------------------------------------------


@pytest.mark.usefixtures("db")
async def test_verify_passphrase_without_secrets(box: SecretBox) -> None:
    await make_user()  # a user without TOTP holds no secret
    assert await verify_passphrase(box) is False


@pytest.mark.usefixtures("db")
async def test_verify_passphrase_with_tunnel_psk(box: SecretBox) -> None:
    topo = await Topology.create()
    await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b, preshared_key=box.encrypt(PSK))
    # Stored as JSON and read back unchanged.
    stored = await Tunnel.get()
    assert box.decrypt(stored.preshared_key) == PSK

    assert await verify_passphrase(box) is True
    with pytest.raises(PassphraseError, match="H42_MESH_PASSPHRASE_FILE"):
        await verify_passphrase(SecretBox("wrong"))


@pytest.mark.usefixtures("db")
async def test_verify_passphrase_with_totp_secret_only(box: SecretBox) -> None:
    await make_user("bob")
    await make_user("alice", totp_secret=box.encrypt("JBSWY3DPEHPK3PXP"))
    assert (await User.get(username="alice")).totp_secret is not None
    configure("correct horse battery staple")
    assert await verify_passphrase() is True  # uses the module-level box
    with pytest.raises(PassphraseError):
        await verify_passphrase(SecretBox("wrong"))
