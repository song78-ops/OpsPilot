"""Validated ticket-draft tool arguments and API responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateTicketDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4_000)
    device_or_system: str = Field(default="", max_length=200)


class GetTicketDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class UpdateTicketDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    device_or_system: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def at_least_one_update(self) -> "UpdateTicketDraftArgs":
        if all(
            value is None
            for value in (
                self.title,
                self.description,
                self.device_or_system,
            )
        ):
            raise ValueError("At least one draft field must be updated")
        return self


class TicketDraftResponse(BaseModel):
    id: str
    title: str
    description: str
    device_or_system: str
    status: Literal["draft"]
    created_at: datetime
    updated_at: datetime


class TicketDraftListResponse(BaseModel):
    items: list[TicketDraftResponse]
    total: int


class TicketDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    device_or_system: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def at_least_one_update(self) -> "TicketDraftUpdateRequest":
        if all(
            value is None
            for value in (
                self.title,
                self.description,
                self.device_or_system,
            )
        ):
            raise ValueError("At least one draft field must be updated")
        return self

