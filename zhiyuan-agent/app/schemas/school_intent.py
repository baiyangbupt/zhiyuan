"""School intent extraction result schema."""

from pydantic import BaseModel, Field


class SchoolIntentResult(BaseModel):
    """Result of school intent extraction from chat history."""

    allkeys: list[str] = Field(default_factory=list, description="原始院校词汇")
    newkeys: list[str] = Field(default_factory=list, description="匹配后实体名称")
    colleges: list[str] = Field(default_factory=list, description="正面意向院校")
    negative_colleges: list[str] = Field(default_factory=list, description="负面意向院校")
