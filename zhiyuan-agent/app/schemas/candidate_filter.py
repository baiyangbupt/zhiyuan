"""Candidate query filter extraction schemas."""

from pydantic import BaseModel, Field


class CandidateFilterExtractionResult(BaseModel):
    """One-turn candidate query filter extraction result."""

    shouldQueryCandidate: bool = Field(default=True, description="是否应按候选池机会查询理解")
    tiers: list[str] = Field(default_factory=list, description="冲稳保筛选，只能包含 冲/稳/保")
    provinceNames: list[str] = Field(default_factory=list, description="省份名称")
    cityNames: list[str] = Field(default_factory=list, description="城市名称")
    schoolKeywords: list[str] = Field(default_factory=list, description="院校名称或院校简称解析后的院校名称")
    majorKeywords: list[str] = Field(default_factory=list, description="专业大类或具体专业名称")
    schoolTags: list[str] = Field(default_factory=list, description="院校标签，如 公办/民办/师范/财经/双一流")
    majorTags: list[str] = Field(default_factory=list, description="专业门类、招生类型或限报要求标签")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="抽取置信度")
    ambiguities: list[str] = Field(default_factory=list, description="不确定点")
