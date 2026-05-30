"""Major intent extraction result schemas."""

from pydantic import BaseModel, Field


class MajorIntentResult(BaseModel):
    """Major intent extraction result."""

    allkeys: list[str] = Field(default_factory=list, description="原始专业词汇")
    level1: list[str] = Field(default_factory=list, description="一级专业（门类）")
    level2: list[str] = Field(default_factory=list, description="二级专业（大类）")
    level3: list[str] = Field(default_factory=list, description="三级专业（具体专业）")


class NegativeMajorIntentResult(BaseModel):
    """Negative major intent extraction result."""

    allkeys: list[str] = Field(default_factory=list, description="原始专业词汇")
    level1: list[str] = Field(default_factory=list, description="负面一级专业（门类）")
    level2: list[str] = Field(default_factory=list, description="负面二级专业")
    level3: list[str] = Field(default_factory=list, description="负面三级专业")


class MajorIntentPolarityResult(BaseModel):
    """Combined positive/negative major intent extraction result."""

    positive: MajorIntentResult = Field(default_factory=MajorIntentResult, description="正面专业意向")
    negative: NegativeMajorIntentResult = Field(default_factory=NegativeMajorIntentResult, description="负面专业意向")
