from typing import TYPE_CHECKING, Any

from tortoise import fields
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.enums import MeshAccessLevel, SessionStage
from h42mesh.controller.models.validators import SHA256_HEX_VALIDATOR

if TYPE_CHECKING:
    from collections.abc import Iterable

    from h42mesh.controller.models.enrollment import EnrollmentToken
    from h42mesh.controller.models.mesh import Mesh


class User(BaseModel):
    """GUI user. A single administrator, created at installation, sees every mesh.

    The single-administrator rule and the refusal to delete the administrator
    are checked here (a "single true" constraint is not portable). They do not
    apply to bulk queryset operations.
    """

    username = fields.CharField(max_length=64, unique=True)
    password_hash = fields.CharField(max_length=255)  # Argon2
    must_change_password = fields.BooleanField(default=True)
    # Encrypted secret (JSON object: v, kdf, salt, nonce, ciphertext).
    totp_secret: dict[str, Any] | None = fields.JSONField(null=True)
    # Last accepted TOTP time step (30 s window): a code cannot be replayed.
    totp_last_step = fields.BigIntField(null=True)
    is_admin = fields.BooleanField(default=False)
    can_create_meshes = fields.BooleanField(default=False)
    failed_login_count = fields.IntField(default=0)
    locked_until = fields.DatetimeField(null=True)
    last_login_at = fields.DatetimeField(null=True)

    mesh_accesses: fields.ReverseRelation["MeshAccess"]
    sessions: fields.ReverseRelation["UserSession"]
    created_meshes: fields.ReverseRelation["Mesh"]
    enrollment_tokens: fields.ReverseRelation["EnrollmentToken"]

    class Meta:
        # "user" is a reserved word in PostgreSQL.
        table = "user_account"

    async def save(
        self,
        using_db: BaseDBAsyncClient | None = None,
        update_fields: "Iterable[str] | None" = None,
        force_create: bool = False,
        force_update: bool = False,
    ) -> None:
        if self.is_admin:
            others = User.filter(is_admin=True)
            if self._saved_in_db:
                others = others.exclude(id=self.id)
            if await others.using_db(using_db).exists():
                raise IntegrityError("an administrator already exists")
        await super().save(using_db, update_fields, force_create, force_update)

    async def delete(self, using_db: BaseDBAsyncClient | None = None) -> None:
        if self.is_admin:
            raise IntegrityError("the administrator cannot be deleted")
        await super().delete(using_db)


class MeshAccess(BaseModel):
    """Access of a user to a mesh. The administrator needs none."""

    user: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="mesh_accesses", on_delete=fields.CASCADE
    )
    mesh: fields.ForeignKeyRelation["Mesh"] = fields.ForeignKeyField(
        "models.Mesh", related_name="accesses", on_delete=fields.CASCADE
    )
    level = fields.CharEnumField(MeshAccessLevel, max_length=16)

    class Meta:
        table = "mesh_access"
        unique_together = (("user", "mesh"),)


class UserSession(BaseModel):
    """GUI session. Only the digest of the cookie token is stored."""

    user: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="sessions", on_delete=fields.CASCADE
    )
    token_hash = fields.CharField(max_length=64, unique=True, validators=[SHA256_HEX_VALIDATOR])
    stage = fields.CharEnumField(SessionStage, max_length=16)
    expires_at = fields.DatetimeField()
    last_seen_at = fields.DatetimeField()  # expiry after inactivity

    class Meta:
        table = "user_session"
