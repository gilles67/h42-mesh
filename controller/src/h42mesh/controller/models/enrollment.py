from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel

if TYPE_CHECKING:
    from h42mesh.controller.models.router import Router


class EnrollmentToken(BaseModel):
    """Single-use enrollment token, bound to a declared router.

    Only the SHA-256 digest is stored: the token is long and random,
    so a slow hash adds nothing.
    """

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="enrollment_tokens", on_delete=fields.CASCADE
    )
    token_hash = fields.CharField(max_length=64, unique=True)
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)

    class Meta:
        table = "enrollment_token"
