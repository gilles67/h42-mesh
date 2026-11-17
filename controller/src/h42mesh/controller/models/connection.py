from typing import TYPE_CHECKING

from tortoise import fields

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.enums import ConnectionKind, ConnectionRole

if TYPE_CHECKING:
    from h42mesh.controller.models.router import Router


class InternetConnection(BaseModel):
    """A router's internet connection. Addresses are discovered by the agent."""

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="connections", on_delete=fields.CASCADE
    )
    name = fields.CharField(max_length=64)
    role = fields.CharEnumField(ConnectionRole, max_length=16)
    priority = fields.IntField(null=True)  # tie-breaker within the same role
    direct_ipv4 = fields.BooleanField(default=False)  # accepts inbound tunnels over IPv4
    direct_ipv6 = fields.BooleanField(default=False)  # accepts inbound tunnels over IPv6
    ipv4_port_min = fields.IntField(null=True)  # port range on a shared IPv4
    ipv4_port_max = fields.IntField(null=True)
    metered = fields.BooleanField(default=False)  # billed by volume
    kind = fields.CharEnumField(ConnectionKind, max_length=16, default=ConnectionKind.OTHER)

    class Meta:
        table = "internet_connection"
        unique_together = (("router", "name"),)
