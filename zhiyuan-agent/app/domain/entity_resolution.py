"""Shared entity resolution models for dialogue understanding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


EntityType = Literal["major", "school", "school_major_ref"]
EntitySource = Literal["exact", "alias", "auto_alias", "catalog", "extractor", "item_match"]
EntityConfidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class EntityResolutionCandidate:
    entity_type: EntityType
    raw_text: str
    canonical_name: str
    source: EntitySource
    confidence: EntityConfidence
    level: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityResolutionResult:
    raw_text: str
    entity_type: EntityType
    candidates: tuple[EntityResolutionCandidate, ...] = ()
    ambiguous: bool = False

    @property
    def best(self) -> EntityResolutionCandidate | None:
        if self.ambiguous or not self.candidates:
            return None
        return self.candidates[0]

    @property
    def canonical_names(self) -> list[str]:
        return [candidate.canonical_name for candidate in self.candidates]

