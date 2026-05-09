#!/usr/bin/env python3
"""Analyze copied legacy volunteer plan JSON samples offline.

This script reads local JSON files only. It does not connect to MySQL,
call backend APIs, or write planningState.

Usage:
  python3 scripts/analyze_legacy_plan_samples.py /tmp/zhiyuan-migration-samples
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


FILE_RE = re.compile(r"session_volunteer_(?P<session>\d+)(?P<suffix>_temp|_final)?\.json$")
TIERS = [
    ("sprints", "冲"),
    ("safes", "稳"),
    ("protects", "保"),
]


def classify_file(path):
    match = FILE_RE.match(path.name)
    if not match:
        return "-", "unknown"
    suffix = match.group("suffix") or ""
    if suffix == "_temp":
        kind = "temp"
    elif suffix == "_final":
        kind = "final"
    else:
        kind = "main"
    return match.group("session"), kind


def as_list(value):
    return value if isinstance(value, list) else []


def get_nested(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_schools(data, key):
    direct = data.get(key) if isinstance(data, dict) else None
    if isinstance(direct, list):
        return direct

    detail_list = data.get("detailList") if isinstance(data, dict) else None
    if isinstance(detail_list, list):
        target_tier = {
            "sprints": "冲",
            "safes": "稳",
            "protects": "保",
        }.get(key)
        return [
            item
            for item in detail_list
            if isinstance(item, dict) and normalize_legacy_tier(item.get("volunteerLevel")) == target_tier
        ]

    # Some complete legacy files keep original data below a data/detailList layer.
    for prefix in (("data",), ("data", "volunteerData"), ("volunteerData",)):
        nested = get_nested(data, *prefix, key)
        if isinstance(nested, list):
            return nested
    return []


def extract_majors(school):
    for key in ("majors", "majorList", "majorVOList", "detailList"):
        value = school.get(key) if isinstance(school, dict) else None
        if isinstance(value, list):
            return value
    return []


def boolish(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def is_preferred(school):
    for key in ("is_preferred", "isPreferred", "selectZy", "selected", "selectSchool"):
        if key in school:
            return boolish(school.get(key)), True
    for major in extract_majors(school):
        if isinstance(major, dict) and "selectZy" in major:
            return boolish(major.get("selectZy")), True
    return False, False


def has_school_id(school):
    return bool(school.get("schoolId") or school.get("school_id"))


def has_school_name(school):
    return bool(school.get("school_name") or school.get("schoolName") or school.get("schoolUnitName"))


def has_plan_school_id(school):
    return bool(school.get("planSchoolDataId") or school.get("plan_school_data_id"))


def has_major_identity(major):
    return bool(
        major.get("majorId")
        or major.get("major_id")
        or major.get("planMajorDataId")
        or major.get("plan_major_data_id")
    )


def normalize_legacy_tier(value):
    if isinstance(value, dict):
        code = str(value.get("code") or "").upper()
        desc = str(value.get("desc") or "")
    else:
        code = str(value or "").upper()
        desc = str(value or "")
    if code == "SPRINT" or desc == "冲":
        return "冲"
    if code == "SAFE" or desc == "稳":
        return "稳"
    return "保"


def analyze_plan(data):
    result = {
        "tier_counts": Counter(),
        "preferred_counts": Counter(),
        "candidate_counts": Counter(),
        "major_counts": Counter(),
        "schools_without_preferred_flag": 0,
        "schools_missing_id": 0,
        "schools_missing_name": 0,
        "schools_missing_plan_id": 0,
        "majors_missing_identity": 0,
        "base_need_count": get_nested(data, "baseData", "need_count"),
        "volunteer_model": get_nested(data, "baseData", "volunteerModel"),
    }

    for key, tier in TIERS:
        schools = as_list(extract_schools(data, key))
        result["tier_counts"][tier] += len(schools)
        for school in schools:
            if not isinstance(school, dict):
                continue
            preferred, has_preferred_flag = is_preferred(school)
            if not has_preferred_flag:
                result["schools_without_preferred_flag"] += 1
            if preferred:
                result["preferred_counts"][tier] += 1
            if not has_school_id(school):
                result["schools_missing_id"] += 1
            if not has_school_name(school):
                result["schools_missing_name"] += 1
            if not has_plan_school_id(school):
                result["schools_missing_plan_id"] += 1

            majors = extract_majors(school)
            if majors:
                result["major_counts"][tier] += len(majors)
                result["candidate_counts"][tier] += len(majors)
                for major in majors:
                    if isinstance(major, dict) and not has_major_identity(major):
                        result["majors_missing_identity"] += 1
            else:
                result["major_counts"][tier] += 1 if has_major_identity(school) else 0
                result["candidate_counts"][tier] += 1
                if not has_major_identity(school):
                    result["majors_missing_identity"] += 1
    return result


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def format_tiers(counter):
    return "冲={}/稳={}/保={}".format(
        counter.get("冲", 0),
        counter.get("稳", 0),
        counter.get("保", 0),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_dir", help="directory containing copied session_volunteer_*.json files")
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir)
    if not sample_dir.is_dir():
        print(f"error: sample_dir not found: {sample_dir}", file=sys.stderr)
        return 2

    paths = sorted(sample_dir.glob("session_volunteer_*.json"))
    totals = Counter()
    session_kinds = defaultdict(set)
    failures = []

    print("Legacy plan sample analysis")
    print("===========================")
    print(f"sample_dir={sample_dir}")
    print(f"file_count={len(paths)}")
    print("")
    print(
        "file\tsession\tkind\tbytes\tschools\tcandidates\tpreferred\tmajors\t"
        "missing_pref_flag\tmissing_school_id\tmissing_school_name\tmissing_plan_school_id\tmissing_major_identity"
    )

    for path in paths:
        session_id, kind = classify_file(path)
        session_kinds[session_id].add(kind)
        size = os.path.getsize(path)
        try:
            data = load_json(path)
            analysis = analyze_plan(data)
        except Exception as exc:
            failures.append((path.name, str(exc)))
            print(f"{path.name}\t{session_id}\t{kind}\t{size}\tERROR\t{exc}")
            continue

        school_total = sum(analysis["tier_counts"].values())
        candidate_total = sum(analysis["candidate_counts"].values())
        preferred_total = sum(analysis["preferred_counts"].values())
        major_total = sum(analysis["major_counts"].values())
        totals["files_ok"] += 1
        totals["schools"] += school_total
        totals["candidates"] += candidate_total
        totals["preferred"] += preferred_total
        totals["majors"] += major_total
        totals["missing_pref_flag"] += analysis["schools_without_preferred_flag"]
        totals["missing_school_id"] += analysis["schools_missing_id"]
        totals["missing_school_name"] += analysis["schools_missing_name"]
        totals["missing_plan_school_id"] += analysis["schools_missing_plan_id"]
        totals["missing_major_identity"] += analysis["majors_missing_identity"]

        print(
            f"{path.name}\t{session_id}\t{kind}\t{size}\t"
            f"{format_tiers(analysis['tier_counts'])}\t"
            f"{format_tiers(analysis['candidate_counts'])}\t"
            f"{format_tiers(analysis['preferred_counts'])}\t"
            f"{format_tiers(analysis['major_counts'])}\t"
            f"{analysis['schools_without_preferred_flag']}\t"
            f"{analysis['schools_missing_id']}\t"
            f"{analysis['schools_missing_name']}\t"
            f"{analysis['schools_missing_plan_id']}\t"
            f"{analysis['majors_missing_identity']}"
        )

    print("")
    print("Summary")
    print("=======")
    print(f"sessions={len(session_kinds)}")
    print(f"files_ok={totals['files_ok']}")
    print(f"files_failed={len(failures)}")
    print(f"schools={totals['schools']}")
    print(f"candidates={totals['candidates']}")
    print(f"preferred={totals['preferred']}")
    print(f"majors={totals['majors']}")
    print(f"missing_pref_flag={totals['missing_pref_flag']}")
    print(f"missing_school_id={totals['missing_school_id']}")
    print(f"missing_school_name={totals['missing_school_name']}")
    print(f"missing_plan_school_id={totals['missing_plan_school_id']}")
    print(f"missing_major_identity={totals['missing_major_identity']}")
    print("")
    print("session_file_kinds:")
    for session_id in sorted(session_kinds, key=lambda value: int(value) if value.isdigit() else value):
        print(f"  {session_id}: {','.join(sorted(session_kinds[session_id]))}")

    if failures:
        print("")
        print("failures:")
        for name, reason in failures:
            print(f"  {name}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
