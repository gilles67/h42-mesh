from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.enums import SiteKind

if TYPE_CHECKING:
    from h42mesh.controller.models.router import Router


class Site(BaseModel):
    """A home (``home``) or a VPS (``relay``), with its private AS."""

    name = fields.CharField(max_length=64, unique=True)
    kind = fields.CharEnumField(SiteKind, max_length=16)
    number = fields.IntField(unique=True)
    asn = fields.BigIntField(unique=True)  # = asn_for(kind, number)

    routers: fields.ReverseRelation["Router"]

    class Meta:
        table = "site"
