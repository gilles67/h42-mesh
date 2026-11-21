from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Every API error: a stable code for the GUI to translate, and an English message."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(examples=["invalid_credentials"])
    message: str = Field(examples=["Invalid username or password"])
