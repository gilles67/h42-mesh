from typing import TYPE_CHECKING
from uuid import UUID

from tortoise import fields

from h42mesh.controller.models.base import BaseModel

if TYPE_CHECKING:
    from h42mesh.controller.models.site import Site
    from h42mesh.controller.models.tunnel import Tunnel
    from h42mesh.controller.models.user import MeshAccess, User


class Mesh(BaseModel):
    """An independent mesh. Deletion is refused while it contains sites."""

    name = fields.CharField(max_length=64, unique=True)
    created_by: fields.ForeignKeyNullableRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="created_meshes", null=True, on_delete=fields.SET_NULL
    )

    created_by_id: UUID | None

    sites: fields.ReverseRelation["Site"]
    tunnels: fields.ReverseRelation["Tunnel"]
    accesses: fields.ReverseRelation["MeshAccess"]

    class Meta:
        table = "mesh"
