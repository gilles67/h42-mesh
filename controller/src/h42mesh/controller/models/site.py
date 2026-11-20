from typing import TYPE_CHECKING
from uuid import UUID

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.validators import (
    ASN_MAX,
    ASN_MIN,
    NICKNAME_VALIDATOR,
    range_validators,
)

if TYPE_CHECKING:
    from h42mesh.controller.models.mesh import Mesh
    from h42mesh.controller.models.router import Router


class Site(BaseModel):
    """A site (home or VPS hub: there is no site type), with its private AS.

    Deletion is refused while it contains routers.
    """

    mesh: fields.ForeignKeyRelation["Mesh"] = fields.ForeignKeyField(
        "models.Mesh", related_name="sites", on_delete=fields.RESTRICT
    )
    name = fields.CharField(max_length=64)
    # Four-letter code used in tunnel interface names, e.g. "root", "pari".
    nickname = fields.CharField(max_length=4, validators=[NICKNAME_VALIDATOR])
    location = fields.CharField(max_length=64, null=True)
    asn = fields.BigIntField(validators=range_validators(ASN_MIN, ASN_MAX))

    mesh_id: UUID

    routers: fields.ReverseRelation["Router"]

    class Meta:
        table = "site"
        unique_together = (("mesh", "name"), ("mesh", "nickname"), ("mesh", "asn"))
