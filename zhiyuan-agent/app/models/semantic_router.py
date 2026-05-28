"""Semantic router frame for quality-first dialog routing.

The router is introduced in shadow mode first.  It describes user intent in a
small, structured frame so current fast-route decisions can be compared with a
model-level semantic judgement before we move anything into the main path.
"""

from __future__ import annotations

import json
from typing import Any

from typing import Literal

from pydantic import BaseModel, Field, model_validator


TaskLayer = Literal["explore", "intent", "plan", "general"]
Verb = Literal[
    "query",
    "analyze",
    "compare",
    "recommend",
    "explain",
    "review",
    "generate",
    "add",
    "remove",
    "move",
    "sort",
    "replace",
    "confirm",
    "reject",
    "set_preference",
    "set_constraint",
    "remove_preference",
    "clarify",
]
Topic = Literal[
    "plan",
    "major",
    "school",
    "region",
    "career",
    "score",
    "policy",
    "requirement",
    "general",
]
SideEffect = Literal["readonly", "preview", "apply", "none"]


class SemanticRouterEntities(BaseModel):
    schools: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    careerDirections: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)
    sortFields: list[str] = Field(default_factory=list)
    reviewIssues: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_entity_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for key in (
            "schools",
            "majors",
            "regions",
            "careerDirections",
            "positions",
            "sortFields",
            "reviewIssues",
        ):
            if key not in normalized:
                continue
            value = normalized[key]
            if value is None:
                normalized[key] = []
                continue
            items = value if isinstance(value, list) else [value]
            normalized[key] = [_stringify_entity_item(item) for item in items]
        return normalized


def _stringify_entity_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, (dict, list)):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


class SemanticResponseNeed(BaseModel):
    depth: Literal["brief", "normal", "rich"] = "normal"
    requiredFacts: list[str] = Field(default_factory=list)
    mustNotDo: list[str] = Field(default_factory=list)


class SemanticIntentFrame(BaseModel):
    taskLayer: TaskLayer = "general"
    verb: Verb = "clarify"
    topic: Topic = "general"
    sideEffect: SideEffect = "readonly"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ambiguity: list[str] = Field(default_factory=list)
    missingInfo: list[str] = Field(default_factory=list)
    entities: SemanticRouterEntities = Field(default_factory=SemanticRouterEntities)
    responseNeed: SemanticResponseNeed = Field(default_factory=SemanticResponseNeed)
    reason: str = ""


class SemanticRouterShadowResult(BaseModel):
    enabled: bool = True
    status: Literal["success", "disabled", "scheduled", "timeout", "error"] = "success"
    frame: SemanticIntentFrame | None = None
    durationMs: int = 0
    promptChars: int = 0
    errorType: str = ""
    errorMessage: str = ""

    def event_payload(self) -> dict:
        payload = self.model_dump(exclude_none=True)
        if payload.get("errorMessage"):
            payload["errorMessage"] = str(payload["errorMessage"])[:200]
        return payload
