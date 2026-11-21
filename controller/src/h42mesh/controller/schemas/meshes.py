from datetime import datetime
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from h42mesh.controller.models import MeshAccessLevel

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class PatchRequest(BaseModel):
    """Partial update: only the fields sent are changed.

    ``null`` clears an optional field and is refused for a required one
    (listed in ``required_fields``).
    """

    model_config = ConfigDict(extra="forbid")
    required_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_for_required(self) -> "PatchRequest":
        for name in self.model_fields_set & self.required_fields:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class MeshCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class MeshUpdate(PatchRequest):
    required_fields = frozenset({"name"})

    name: Name | None = None


class MeshRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    access_level: MeshAccessLevel  # of the current user (manage for the administrator)


class MeshAccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: MeshAccessLevel


class MeshAccessRead(BaseModel):
    user_id: UUID
    username: str
    level: MeshAccessLevel
