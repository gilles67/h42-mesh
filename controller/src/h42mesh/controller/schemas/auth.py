from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")]
NewPassword = Annotated[str, StringConstraints(min_length=12, max_length=256)]
TotpCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NextStep(StrEnum):
    """What the GUI must ask next."""

    TOTP = "totp"  # enter the TOTP code
    CHANGE_PASSWORD = "change_password"  # noqa: S105 (mandatory at first login)
    SETUP_TOTP = "setup_totp"  # mandatory at first login
    DONE = "done"


class LoginRequest(_Request):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class LoginResponse(BaseModel):
    next_step: NextStep


class TotpCodeRequest(_Request):
    code: TotpCode


class PasswordChangeRequest(_Request):
    current_password: str = Field(max_length=256)
    new_password: NewPassword


class TotpSetupResponse(BaseModel):
    secret: str = Field(description="Base32 secret, to send back to totp_confirm")
    otpauth_uri: str = Field(description="URI for a QR code (otpauth://totp/…)")


class TotpConfirmRequest(_Request):
    secret: str = Field(min_length=32, max_length=32)
    code: TotpCode


class CurrentUser(BaseModel):
    id: UUID
    username: str
    is_admin: bool
    can_create_meshes: bool
    must_change_password: bool
    totp_enabled: bool
    next_step: NextStep
