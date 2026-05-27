"""User-facing display text helpers."""

from __future__ import annotations

import re
from typing import Any


def brief_school_major_text(
    school_name: Any,
    major_name: Any,
    *,
    max_length: int = 80,
) -> str:
    """Compact a school-major label for chat replies.

    Backend major names may include admission notes, campus, cooperation, tuition,
    language and score requirements. Those details are useful in tables, but make
    chat samples unreadable. Keep the inspectable school-major identity only.
    """
    school = str(school_name or "未知院校").strip()
    major = str(major_name or "未知专业").strip()
    text = f"{school}-{major}"
    return compact_school_major_text(text, max_length=max_length)


def compact_school_major_text(value: Any, *, max_length: int = 80) -> str:
    text = str(value or "").strip(" ，,；;。")
    if not text:
        return ""

    text = re.split(r"[；;]", text, maxsplit=1)[0].strip()
    parts = text.split("-", 1)
    if len(parts) == 2:
        school, major = parts[0].strip(), parts[1].strip()
        school = re.split(r"[（(]", school, maxsplit=1)[0].strip()
        major = _compact_major_name(major)
        if school and major:
            text = f"{school}-{major}"
    else:
        text = _compact_major_name(text)

    if len(text) > max_length:
        text = text[:max_length].rstrip("，,；;。") + "..."
    return text


def clean_plan_sample_text(value: Any, *, max_length: int = 80) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("(unknown)", "")
    text = re.sub(r"@(\d+)", r"第\1位", text)

    parts = re.split(r"([；;\n])", text)
    cleaned = [
        part if part in {"；", ";", "\n"} else _clean_plan_sample_segment(part, max_length=max_length)
        for part in parts
    ]
    return "".join(cleaned).strip()


def _clean_plan_sample_segment(value: str, *, max_length: int) -> str:
    segment = value.strip()
    if not segment or "-" not in segment or not re.search(r"(?:大学|学院)", segment):
        return value

    tail = ""
    tier_matches = list(re.finditer(r"[（(]([冲稳保])[）)]", segment))
    if tier_matches:
        tier_match = tier_matches[-1]
        tail = segment[tier_match.start() :].strip()
        segment = segment[: tier_match.start()].strip()

    return compact_school_major_text(segment, max_length=max_length) + tail


def _compact_major_name(value: str) -> str:
    text = value.strip()
    text = re.split(
        r"[，,](?=(?:要求|合作方|前三年|每年学费|报考前|只招|不招|按要求|办学地点|学费))",
        text,
        maxsplit=1,
    )[0].strip()
    text = re.split(
        r"[（(](?:冲|稳|保|中外合作|合作|办学地点|要求|只招|不招|学费|前三年|第一|第二|第三|第四)",
        text,
        maxsplit=1,
    )[0].strip()
    text = re.sub(r"[\s　]+", "", text)
    return text.strip(" ，,；;。")
