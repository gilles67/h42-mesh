"""First start: create the administrator when the database has no user."""

import logging

from tortoise.exceptions import IntegrityError

from h42mesh.controller.auth import passwords
from h42mesh.controller.models import User

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"


async def ensure_admin() -> str | None:
    """Create the administrator if there is no user; returns its password, or None.

    The random password is logged once; it must be changed, and TOTP enabled,
    at first login.
    """
    if await User.exists():
        return None
    password = passwords.generate_password()
    try:
        await User.create(
            username=ADMIN_USERNAME,
            password_hash=passwords.hash_password(password),
            is_admin=True,
            must_change_password=True,
        )
    except IntegrityError:
        # Another controller instance created it at the same time.
        return None
    logger.warning(
        "administrator created: username %r, password %r (shown only once; "
        "change it and enable TOTP at first login)",
        ADMIN_USERNAME,
        password,
    )
    return password


def configure_logging() -> None:
    """Make the controller's own log visible (the admin password is logged once)."""
    package_logger = logging.getLogger("h42mesh")
    if not package_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(name)s: %(message)s"))
        package_logger.addHandler(handler)
    if package_logger.level == logging.NOTSET:
        package_logger.setLevel(logging.INFO)
