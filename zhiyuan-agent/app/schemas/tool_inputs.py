from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MajorIntentPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level1: list[str] = Field(default_factory=list)
    level2: list[str] = Field(default_factory=list)
    level3: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "level3",
            "add",
            "include",
            "interested",
            "interest",
            "priority",
            "desired",
            "prefer",
            "preferred",
            "positive",
            "major",
            "majors",
            "values",
        ),
    )
    negative_level1: list[str] = Field(default_factory=list)
    negative_level2: list[str] = Field(default_factory=list)
    negative_level3: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "negative_level3",
            "delete",
            "remove",
            "exclude",
            "avoid",
            "unwanted",
            "negative",
        ),
    )


class SchoolIntentPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colleges: list[str] = Field(default_factory=list)
    negative_colleges: list[str] = Field(default_factory=list)


class CityIntentPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    province: list[str] = Field(default_factory=list)
    city: list[str] = Field(default_factory=list)
    area: list[str] = Field(default_factory=list)
    negative_province: list[str] = Field(default_factory=list)
    negative_city: list[str] = Field(default_factory=list)
    negative_area: list[str] = Field(default_factory=list)


class CareerIntentPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)

