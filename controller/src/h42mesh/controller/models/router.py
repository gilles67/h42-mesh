from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.validators import ROUTER_ID_NETWORK, IPv4InNetworkValidator

if TYPE_CHECKING:
    from h42mesh.controller.models.connection import InternetConnection
    from h42mesh.controller.models.enrollment import EnrollmentToken
    from h42mesh.controller.models.site import Site


class Router(BaseModel):
    """A site's router. Private keys never leave the router."""

    site: fields.ForeignKeyRelation["Site"] = fields.ForeignKeyField(
        "models.Site", related_name="routers", on_delete=fields.CASCADE
    )
    name = fields.CharField(max_length=64)
    # BGP router ID, in 10.254.0.0/24, stored as text.
    router_id_address = fields.CharField(
        max_length=15, unique=True, validators=[IPv4InNetworkValidator(ROUTER_ID_NETWORK)]
    )
    # Base64 public keys (32 bytes -> 44 characters), known once enrolled.
    wireguard_public_key = fields.CharField(max_length=44, null=True, unique=True)
    signing_public_key = fields.CharField(max_length=44, null=True, unique=True)
    signing_key_enabled = fields.BooleanField(default=True)  # False = router revoked
    enrolled_at = fields.DatetimeField(null=True)

    connections: fields.ReverseRelation["InternetConnection"]
    enrollment_tokens: fields.ReverseRelation["EnrollmentToken"]

    class Meta:
        table = "router"
        unique_together = (("site", "name"),)
