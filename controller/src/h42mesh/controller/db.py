"""Tortoise ORM configuration.

``TORTOISE_ORM`` is read by the ``tortoise`` command (see ``[tool.tortoise]``
in pyproject.toml) to generate and apply migrations.
"""

from typing import Any

from h42mesh.controller.settings import get_settings

APP_LABEL = "models"
MODELS_MODULE = "h42mesh.controller.models"
MIGRATIONS_MODULE = "h42mesh.controller.migrations"


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    """Build the Tortoise configuration for a given database URL.

    Tortoise's SQLite driver already enables WAL and foreign keys.
    """
    return {
        "connections": {"default": database_url},
        "apps": {
            APP_LABEL: {
                "models": [MODELS_MODULE],
                "default_connection": "default",
                "migrations": MIGRATIONS_MODULE,
            }
        },
        "use_tz": True,
        "timezone": "UTC",
    }


TORTOISE_ORM = build_tortoise_config(get_settings().database_url)
