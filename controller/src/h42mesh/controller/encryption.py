"""Encryption of the secrets stored in the database (tunnel PSKs, TOTP secrets).

Each secret is stored as a JSON object holding everything needed to decrypt it:

    {"v": 1, "kdf": "scrypt", "salt": "…", "nonce": "…", "ciphertext": "…"}

Version 1: the key is derived from the controller passphrase and a random
per-secret salt with scrypt (n=2**15, r=8, p=1, 32-byte key), and the secret is
encrypted with ChaCha20-Poly1305. Binary values are base64 encoded. The version
and KDF name are authenticated with the ciphertext (associated data).

Derivation is deliberately slow, so derived keys are cached in memory by salt.
A wrong passphrase and a tampered object are indistinguishable: both make the
authenticated decryption fail.
"""

import base64
import binascii
import os
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from h42mesh.controller.settings import Settings

VERSION = 1
KDF = "scrypt"
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
SALT_LENGTH = 16
NONCE_LENGTH = 12
KEY_CACHE_SIZE = 4096  # far above the expected number of secrets
FIELDS = frozenset({"v", "kdf", "salt", "nonce", "ciphertext"})


class SecretError(Exception):
    """Base class of the errors of this module."""


class PassphraseError(SecretError):
    """The passphrase is missing, unreadable, or does not decrypt the stored secrets."""


class InvalidSecretFormatError(SecretError):
    """The JSON object is not an encrypted secret this version can read."""


class SecretDecryptionError(SecretError):
    """Authenticated decryption failed: wrong passphrase or altered object."""


def read_passphrase(path: Path | None) -> str:
    """Read the passphrase file; a single trailing newline is ignored."""
    if path is None:
        raise PassphraseError("H42_MESH_PASSPHRASE_FILE is not set")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PassphraseError(f"cannot read the passphrase file {path}: {exc}") from exc
    passphrase = text.removesuffix("\n").removesuffix("\r")
    if not passphrase.strip():
        raise PassphraseError(f"the passphrase file {path} is empty")
    return passphrase


def _associated_data(version: int, kdf: str) -> bytes:
    return f"h42-mesh-secret:v{version}:{kdf}".encode()


def _b64decode(payload: Mapping[str, Any], name: str) -> bytes:
    value = payload[name]
    if not isinstance(value, str):
        raise InvalidSecretFormatError(f"{name!r} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as exc:
        raise InvalidSecretFormatError(f"{name!r} is not valid base64") from exc


class SecretBox:
    """Encrypts and decrypts secrets with keys derived from one passphrase."""

    def __init__(self, passphrase: str) -> None:
        if not passphrase:
            raise PassphraseError("the passphrase is empty")
        self._passphrase = passphrase.encode("utf-8")
        self._keys: OrderedDict[bytes, bytes] = OrderedDict()

    def _key(self, salt: bytes) -> bytes:
        key = self._keys.get(salt)
        if key is None:
            kdf = Scrypt(salt=salt, length=KEY_LENGTH, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
            key = kdf.derive(self._passphrase)
            self._keys[salt] = key
            if len(self._keys) > KEY_CACHE_SIZE:
                self._keys.popitem(last=False)
        else:
            self._keys.move_to_end(salt)
        return key

    def encrypt(self, plaintext: str) -> dict[str, Any]:
        """Encrypt a string into a JSON-serialisable object, with a fresh salt and nonce."""
        salt = os.urandom(SALT_LENGTH)
        nonce = os.urandom(NONCE_LENGTH)
        ciphertext = ChaCha20Poly1305(self._key(salt)).encrypt(
            nonce, plaintext.encode("utf-8"), _associated_data(VERSION, KDF)
        )
        return {
            "v": VERSION,
            "kdf": KDF,
            "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }

    def decrypt(self, payload: Mapping[str, Any]) -> str:
        """Decrypt an object produced by :meth:`encrypt`."""
        if not isinstance(payload, Mapping) or set(payload) != FIELDS:
            raise InvalidSecretFormatError(
                f"an encrypted secret has exactly the keys {sorted(FIELDS)}"
            )
        version, kdf = payload["v"], payload["kdf"]
        if version != VERSION or isinstance(version, bool) or kdf != KDF:
            raise InvalidSecretFormatError(f"unsupported secret format v={version!r} kdf={kdf!r}")
        salt = _b64decode(payload, "salt")
        nonce = _b64decode(payload, "nonce")
        ciphertext = _b64decode(payload, "ciphertext")
        if len(salt) != SALT_LENGTH or len(nonce) != NONCE_LENGTH:
            raise InvalidSecretFormatError("wrong salt or nonce length")
        try:
            plaintext = ChaCha20Poly1305(self._key(salt)).decrypt(
                nonce, ciphertext, _associated_data(version, kdf)
            )
        except InvalidTag as exc:
            raise SecretDecryptionError(
                "cannot decrypt the secret: wrong passphrase or altered data"
            ) from exc
        return plaintext.decode("utf-8")


# --- module-level box, configured once at startup ---------------------------

_box: SecretBox | None = None


def configure(passphrase: str) -> SecretBox:
    """Install the box used by :func:`encrypt_secret` and :func:`decrypt_secret`."""
    global _box
    _box = SecretBox(passphrase)
    return _box


def configure_from_settings(settings: Settings) -> SecretBox:
    """Read the passphrase file named by the settings and install the box."""
    return configure(read_passphrase(settings.passphrase_file))


def reset() -> None:
    """Forget the configured box and its cached keys (tests, shutdown)."""
    global _box
    _box = None


def _configured_box() -> SecretBox:
    if _box is None:
        raise RuntimeError("secret encryption is not configured: call configure() first")
    return _box


def encrypt_secret(plaintext: str) -> dict[str, Any]:
    """Encrypt a string for storage in a JSON field (Tunnel.preshared_key, User.totp_secret)."""
    return _configured_box().encrypt(plaintext)


def decrypt_secret(payload: Mapping[str, Any]) -> str:
    """Decrypt a JSON object produced by :func:`encrypt_secret`."""
    return _configured_box().decrypt(payload)


async def verify_passphrase(box: SecretBox | None = None) -> bool:
    """Startup check: decrypt one stored secret, if any.

    Returns True if a secret was checked, False if the database holds none.
    Raises PassphraseError with a clear message if the passphrase is wrong.
    The schema must exist (run after migrations).
    """
    from h42mesh.controller.models import Tunnel, User

    box = box or _configured_box()
    payload: dict[str, Any] | None = None
    tunnel = await Tunnel.first()
    if tunnel is not None:
        payload = tunnel.preshared_key
    else:
        user = await User.filter(totp_secret__isnull=False).first()
        if user is not None:
            payload = user.totp_secret
    if payload is None:
        return False
    try:
        box.decrypt(payload)
    except SecretDecryptionError as exc:
        raise PassphraseError(
            "the passphrase does not decrypt the secrets stored in the database: "
            "check H42_MESH_PASSPHRASE_FILE (the same passphrase must be used by every "
            "controller sharing this database)"
        ) from exc
    return True
