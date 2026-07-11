"""User profile data models with emotion support."""

from typing import Any
from pydantic import BaseModel, Field


def _normalize_string_list(values: Any) -> list[str]:
    if not values:
        return []

    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []

    if isinstance(values, dict):
        values = [values]

    normalized: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(text)
            continue
        if isinstance(item, dict):
            text = item.get("value") or item.get("label") or item.get("name")
            if isinstance(text, str) and text.strip():
                normalized.append(text.strip())
    return normalized


class SchoolIntent(BaseModel):
    colleges: list[str] = Field(default_factory=list)
    colleges_emotion: list[str] = Field(default_factory=list)
    negative_colleges: list[str] = Field(default_factory=list)
    negative_colleges_emotion: list[str] = Field(default_factory=list)


class MajorIntent(BaseModel):
    level1: list[str] = Field(default_factory=list)
    level1_emotion: list[str] = Field(default_factory=list)
    level2: list[str] = Field(default_factory=list)
    level2_emotion: list[str] = Field(default_factory=list)
    level3: list[str] = Field(default_factory=list)
    level3_emotion: list[str] = Field(default_factory=list)
    negative_level1: list[str] = Field(default_factory=list)
    negative_level1_emotion: list[str] = Field(default_factory=list)
    negative_level2: list[str] = Field(default_factory=list)
    negative_level2_emotion: list[str] = Field(default_factory=list)
    negative_level3: list[str] = Field(default_factory=list)
    negative_level3_emotion: list[str] = Field(default_factory=list)


class CityIntent(BaseModel):
    province: list[str] = Field(default_factory=list)
    province_emotion: list[str] = Field(default_factory=list)
    city: list[str] = Field(default_factory=list)
    city_emotion: list[str] = Field(default_factory=list)
    area: list[str] = Field(default_factory=list)
    negative_province: list[str] = Field(default_factory=list)
    negative_province_emotion: list[str] = Field(default_factory=list)
    negative_city: list[str] = Field(default_factory=list)
    negative_city_emotion: list[str] = Field(default_factory=list)
    negative_area: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    school: SchoolIntent = Field(default_factory=SchoolIntent)
    major: MajorIntent = Field(default_factory=MajorIntent)
    city: CityIntent = Field(default_factory=CityIntent)
    strength_subjects: list[str] = Field(default_factory=list)

    @classmethod
    def from_backend_format(cls, data: dict[str, Any]) -> "UserProfile":
        """Parse UserProfile from the backend response format."""
        # Convert backend payloads to the internal profile model.
        college_info = data.get("college_info", {})
        negative_college_info = data.get("negative_college_info", {})
        school = SchoolIntent(
            colleges=_normalize_string_list(college_info.get("values", [])),
            colleges_emotion=_normalize_string_list(college_info.get("values_emotion", [])),
            negative_colleges=_normalize_string_list(negative_college_info.get("values", [])),
            negative_colleges_emotion=_normalize_string_list(negative_college_info.get("values_emotion", [])),
        )

        major_intent = data.get("major_intent", {})
        negative_major_intent = data.get("negative_major_intent", {})
        major = MajorIntent(
            level1=_normalize_string_list(major_intent.get("level1") or []),
            level1_emotion=_normalize_string_list(major_intent.get("level1_emotion") or []),
            level2=_normalize_string_list(major_intent.get("level2") or []),
            level2_emotion=_normalize_string_list(major_intent.get("level2_emotion") or []),
            level3=_normalize_string_list(major_intent.get("level3") or []),
            level3_emotion=_normalize_string_list(major_intent.get("level3_emotion") or []),
            negative_level1=_normalize_string_list(negative_major_intent.get("level1") or []),
            negative_level1_emotion=_normalize_string_list(negative_major_intent.get("level1_emotion") or []),
            negative_level2=_normalize_string_list(negative_major_intent.get("level2") or []),
            negative_level2_emotion=_normalize_string_list(negative_major_intent.get("level2_emotion") or []),
            negative_level3=_normalize_string_list(negative_major_intent.get("level3") or []),
            negative_level3_emotion=_normalize_string_list(negative_major_intent.get("level3_emotion") or []),
        )

        city_info = data.get("city_info", {})
        negative_city_info = data.get("negative_city_info", {})
        city = CityIntent(
            province=_normalize_string_list(city_info.get("province", [])),
            province_emotion=_normalize_string_list(city_info.get("province_emotion", [])),
            city=_normalize_string_list(city_info.get("city", [])),
            city_emotion=_normalize_string_list(city_info.get("city_emotion", [])),
            area=_normalize_string_list(city_info.get("area", [])),
            negative_province=_normalize_string_list(negative_city_info.get("province", [])),
            negative_province_emotion=_normalize_string_list(negative_city_info.get("province_emotion", [])),
            negative_city=_normalize_string_list(negative_city_info.get("city", [])),
            negative_city_emotion=_normalize_string_list(negative_city_info.get("city_emotion", [])),
            negative_area=_normalize_string_list(negative_city_info.get("area", [])),
        )

        strength_subject_info = data.get("strength_subject_info", {})
        strength_subjects = _normalize_string_list(strength_subject_info.get("values", []) or [])

        return cls(
            school=school,
            major=major,
            city=city,
            strength_subjects=strength_subjects,
        )

    def to_backend_format(self) -> dict[str, Any]:
        """Convert to the backend-compatible profile format."""
        return {
            "major_intent": {
                "level1": self.major.level1 or None,
                "level2": self.major.level2,
                "level3": self.major.level3,
                "level1_emotion": self.major.level1_emotion or None,
                "level2_emotion": self.major.level2_emotion,
                "level3_emotion": self.major.level3_emotion,
            },
            "negative_major_intent": {
                "level1": self.major.negative_level1 or None,
                "level2": self.major.negative_level2,
                "level3": self.major.negative_level3,
                "level1_emotion": self.major.negative_level1_emotion or None,
                "level2_emotion": self.major.negative_level2_emotion,
                "level3_emotion": self.major.negative_level3_emotion,
            },
            "college_info": {
                "values": self.school.colleges,
                "values_emotion": self.school.colleges_emotion,
            },
            "negative_college_info": {
                "values": self.school.negative_colleges,
                "values_emotion": self.school.negative_colleges_emotion,
            },
            "city_info": {
                "province": self.city.province,
                "city": self.city.city,
                "area": self.city.area,
                "province_emotion": self.city.province_emotion,
                "city_emotion": self.city.city_emotion,
            },
            "negative_city_info": {
                "province": self.city.negative_province,
                "city": self.city.negative_city,
                "area": self.city.negative_area,
                "province_emotion": self.city.negative_province_emotion,
                "city_emotion": self.city.negative_city_emotion,
            },
            "strength_subject_info": {
                "values": self.strength_subjects,
                "values_emotion": [],
                "values_code": [],
            },
            "tag_info": {
                "values": None,
                "values_emotion": None,
            },
            "negative_tag_info": {
                "values": None,
                "values_emotion": None,
            },
        }
