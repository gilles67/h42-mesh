from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from h42mesh.controller.schemas.auth import Username


class UserRead(BaseModel):
    """A user as shown to the administrator: never a hash nor a secret."""

    id: UUID
    username: str
    is_admin: bool
    can_create_meshes: bool
    must_change_password: bool
    totp_enabled: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username
    can_create_meshes: bool = False


class UserCreated(BaseModel):
    user: UserRead
    initial_password: str  # shown once; the user must change it at first login


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username | None = None
    can_create_meshes: bool | None = None


class UserSummary(BaseModel):
    """What a mesh manager may learn about a user: enough to grant an access."""

    id: UUID
    username: str
