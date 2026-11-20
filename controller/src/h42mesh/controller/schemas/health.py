from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"] = Field(
        description="'unavailable' when the database cannot be reached"
    )
    version: str = Field(description="Controller version", examples=["0.1.0"])
