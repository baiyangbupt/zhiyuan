"""City intent extraction result schemas."""

from pydantic import BaseModel, Field


class CityIntentResult(BaseModel):
    """Positive city intent extraction result."""

    province: list[str] = Field(default_factory=list, description="正面意向省份")
    city: list[str] = Field(default_factory=list, description="正面意向城市")
    area: list[str] = Field(default_factory=list, description="正面意向地区")


class NegativeCityIntentResult(BaseModel):
    """Negative city intent extraction result."""

    province: list[str] = Field(default_factory=list, description="负面意向省份")
    city: list[str] = Field(default_factory=list, description="负面意向城市")
