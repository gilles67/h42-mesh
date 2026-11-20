from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.enums import ConnectionRole, DirectMode
from h42mesh.controller.models.validators import IPAddressValidator, range_validators

if TYPE_CHECKING:
    from h42mesh.controller.models.router import Router
    from h42mesh.controller.models.tunnel import Tunnel


class Connection(BaseModel):
    """A router's internet connection (``c0`` to ``c9``).

    Public addresses are never entered by hand: they are reported by the agent.
    Physical interface, port range, forced address and fallback delays live in
    the agent's local configuration. Deleting a connection deletes its tunnels.
    """

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="connections", on_delete=fields.CASCADE
    )
    number = fields.SmallIntField(validators=range_validators(0, 9))
    name = fields.CharField(max_length=64)
    role = fields.CharEnumField(ConnectionRole, max_length=16)
    priority = fields.IntField(null=True)  # tie-breaker within the same role
    direct = fields.CharEnumField(DirectMode, max_length=16, default=DirectMode.NONE)
    description = fields.TextField(null=True)
    isp = fields.CharField(max_length=128, null=True)  # from GeoLite2 ASN
    public_ipv4 = fields.CharField(max_length=15, null=True, validators=[IPAddressValidator(4)])
    public_ipv4_updated_at = fields.DatetimeField(null=True)
    public_ipv6 = fields.CharField(max_length=39, null=True, validators=[IPAddressValidator(6)])
    public_ipv6_updated_at = fields.DatetimeField(null=True)

    tunnels_as_a: fields.ReverseRelation["Tunnel"]
    tunnels_as_b: fields.ReverseRelation["Tunnel"]

    class Meta:
        table = "connection"
        unique_together = (("router", "number"),)
