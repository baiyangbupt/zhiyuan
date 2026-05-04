"""Schemas for career-direction intent extraction."""

from pydantic import BaseModel, Field


class CareerIntentResult(BaseModel):
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
