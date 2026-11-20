from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.validators import PublicKeyValidator, range_validators

if TYPE_CHECKING:
    from h42mesh.controller.models.bgp import BgpRoute
    from h42mesh.controller.models.connection import Connection
    from h42mesh.controller.models.enrollment import EnrollmentToken, UsedJwtId
    from h42mesh.controller.models.site import Site
    from h42mesh.controller.models.tunnel import TunnelStatus


class Router(BaseModel):
    """A site's router (``r0`` or ``r1``). Private keys never leave the router.

    Deleting a router deletes its connections (hence its tunnels), enrollment
    tokens, tunnel statuses, BGP routes and used JWT ids.
    """

    site: fields.ForeignKeyRelation["Site"] = fields.ForeignKeyField(
        "models.Site", related_name="routers", on_delete=fields.RESTRICT
    )
    number = fields.SmallIntField(validators=range_validators(0, 1))
    name = fields.CharField(max_length=64)
    # Ed25519 public key of the agent; replaced on renewal, no history.
    signing_public_key = fields.CharField(
        max_length=44, null=True, unique=True, validators=[PublicKeyValidator()]
    )
    signing_key_revoked = fields.BooleanField(default=False)
    enrolled_at = fields.DatetimeField(null=True)
    last_seen_at = fields.DatetimeField(null=True)
    routes_reported_at = fields.DatetimeField(null=True)  # last BGP table report

    connections: fields.ReverseRelation["Connection"]
    enrollment_tokens: fields.ReverseRelation["EnrollmentToken"]
    tunnel_statuses: fields.ReverseRelation["TunnelStatus"]
    bgp_routes: fields.ReverseRelation["BgpRoute"]
    used_jwt_ids: fields.ReverseRelation["UsedJwtId"]

    class Meta:
        table = "router"
        unique_together = (("site", "number"),)
