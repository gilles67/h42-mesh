from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.validators import SHA256_HEX_VALIDATOR

if TYPE_CHECKING:
    from h42mesh.controller.models.router import Router
    from h42mesh.controller.models.user import User


class EnrollmentToken(BaseModel):
    """Single-use enrollment token, bound to a declared router.

    Only the SHA-256 digest is stored: the token is long and random,
    so a slow hash adds nothing. Deleting its creator deletes the token.
    """

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="enrollment_tokens", on_delete=fields.CASCADE
    )
    token_hash = fields.CharField(max_length=64, unique=True, validators=[SHA256_HEX_VALIDATOR])
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)
    created_by: fields.ForeignKeyRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="enrollment_tokens", on_delete=fields.CASCADE
    )

    class Meta:
        table = "enrollment_token"


class UsedJwtId(BaseModel):
    """JWT id already used by an agent (replay protection), purged once expired.

    Stored in the database so that two controller instances share it.
    """

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="used_jwt_ids", on_delete=fields.CASCADE
    )
    jti = fields.CharField(max_length=128)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "used_jwt_id"
        unique_together = (("router", "jti"),)
