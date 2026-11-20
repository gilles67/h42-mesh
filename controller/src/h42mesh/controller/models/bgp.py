from typing import TYPE_CHECKING
from uuid import UUID

from tortoise import fields
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import ValidationError

from h42mesh.controller.models.base import BaseModel
from h42mesh.controller.models.enums import BgpRouteSource
from h42mesh.controller.models.validators import (
    UINT32_MAX,
    AsPathValidator,
    NetworkValidator,
    range_validators,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from h42mesh.controller.models.router import Router
    from h42mesh.controller.models.tunnel import Tunnel


class BgpRoute(BaseModel):
    """One known path to a prefix in a router's BGP table.

    The whole table of a router is replaced on each report (no history); the
    report date is ``Router.routes_reported_at``. No uniqueness on
    (router, prefix): a prefix can be known through several paths.
    """

    router: fields.ForeignKeyRelation["Router"] = fields.ForeignKeyField(
        "models.Router", related_name="bgp_routes", on_delete=fields.CASCADE
    )
    prefix = fields.CharField(max_length=43, validators=[NetworkValidator()])
    source = fields.CharEnumField(BgpRouteSource, max_length=16)
    tunnel: fields.ForeignKeyNullableRelation["Tunnel"] = fields.ForeignKeyField(
        "models.Tunnel", related_name="bgp_routes", null=True, on_delete=fields.CASCADE
    )
    as_path: list[int] = fields.JSONField(validators=[AsPathValidator()])
    origin_asn = fields.BigIntField(null=True, validators=range_validators(0, UINT32_MAX))
    is_best = fields.BooleanField()
    is_backup = fields.BooleanField()  # carries the "backup" community *:1:2
    local_pref = fields.BigIntField(null=True, validators=range_validators(0, UINT32_MAX))

    tunnel_id: UUID | None

    class Meta:
        table = "bgp_route"

    async def save(
        self,
        using_db: BaseDBAsyncClient | None = None,
        update_fields: "Iterable[str] | None" = None,
        force_create: bool = False,
        force_update: bool = False,
    ) -> None:
        has_tunnel = self.tunnel_id is not None
        if has_tunnel != (self.source == BgpRouteSource.TUNNEL):
            raise ValidationError("a tunnel is required if and only if source is 'tunnel'")
        await super().save(using_db, update_fields, force_create, force_update)
