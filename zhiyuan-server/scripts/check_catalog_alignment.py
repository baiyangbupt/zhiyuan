#!/usr/bin/env python3
"""Check catalog alignment across backend, agent and rank static data."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND_BIZDATA = ROOT / "gaotu-assistant-backend" / "src" / "main" / "resources" / "bizdata"
AGENT_OPTION = ROOT / "gaotu-zy-agent-v3" / "data" / "option"
RANK_DATA = ROOT / "gaokao-volunteer-rank-service" / "services" / "data"
RANK_DICT = ROOT / "gaokao-volunteer-rank-service" / "services" / "dict"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_csv_dict(path: Path, key_field: str, value_field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get(key_field) or "").strip()
            value = (row.get(value_field) or "").strip()
            if key and value:
                result[key] = value
    return result


def flatten_major_hierarchy(data: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    level1: dict[str, str] = {}
    level2: dict[str, dict[str, str]] = {}
    level3: dict[str, dict[str, str]] = {}
    for item1 in data:
        level1[item1["id"]] = item1["label"]
        for item2 in item1.get("children", []):
            level2[item2["id"]] = {"label": item2["label"], "parentId": item2["parentId"]}
            for item3 in item2.get("children", []):
                level3[item3["id"]] = {
                    "label": item3["label"],
                    "parentId": item3["parentId"],
                    "majorCode": item3.get("majorCode", ""),
                }
    return {"level1": level1, "level2": level2, "level3": level3}


def compare_major_json(file_name: str) -> dict[str, Any]:
    backend = flatten_major_hierarchy(load_json(BACKEND_BIZDATA / file_name)["data"])
    agent = flatten_major_hierarchy(load_json(AGENT_OPTION / file_name)["data"])
    return {
        "file": file_name,
        "backend_counts": {key: len(value) for key, value in backend.items()},
        "agent_counts": {key: len(value) for key, value in agent.items()},
        "level1_equal": backend["level1"] == agent["level1"],
        "level2_equal": backend["level2"] == agent["level2"],
        "level3_equal": backend["level3"] == agent["level3"],
    }


def compare_province_city() -> dict[str, Any]:
    backend = load_json(BACKEND_BIZDATA / "province_city.json")
    agent = load_json(AGENT_OPTION / "province_city.json")
    return {
        "equal": backend == agent,
        "backend_nodes": len(backend.get("data", [])),
        "agent_nodes": len(agent.get("data", [])),
    }


def compare_school_catalog() -> dict[str, Any]:
    backend = load_csv_dict(BACKEND_BIZDATA / "school_info.csv", "school_id", "school_name")
    agent_bachelor = load_csv_dict(AGENT_OPTION / "school_bachelor.csv", "标准院校id", "标准院校名称")
    agent_associate = load_csv_dict(AGENT_OPTION / "school_associate.csv", "标准院校id", "标准院校名称")
    agent_union = dict(agent_bachelor)
    agent_union.update(agent_associate)
    backend_only = sorted(set(backend) - set(agent_union))
    agent_only = sorted(set(agent_union) - set(backend))
    same_id_diff_name = [
        {"schoolId": school_id, "backend": backend[school_id], "agent": agent_union[school_id]}
        for school_id in sorted(set(backend) & set(agent_union))
        if backend[school_id] != agent_union[school_id]
    ]
    return {
        "backend_count": len(backend),
        "agent_bachelor_count": len(agent_bachelor),
        "agent_associate_count": len(agent_associate),
        "agent_union_count": len(agent_union),
        "backend_only_count": len(backend_only),
        "agent_only_count": len(agent_only),
        "same_id_diff_name_count": len(same_id_diff_name),
        "agent_only_sample": agent_only[:20],
        "same_id_diff_name_sample": same_id_diff_name[:20],
    }


def load_backend_major_sets() -> dict[str, set[str]]:
    category_ids: set[str] = set()
    sub_category_ids: set[str] = set()
    major_ids: set[str] = set()
    for file_name in ("major_bachelor.json", "major_associate.json"):
        data = load_json(BACKEND_BIZDATA / file_name)["data"]
        for item1 in data:
            category_ids.add(item1["id"])
            for item2 in item1.get("children", []):
                sub_category_ids.add(item2["id"])
                for item3 in item2.get("children", []):
                    major_ids.add(item3["id"])
    return {
        "categoryIds": category_ids,
        "subCategoryIds": sub_category_ids,
        "majorIds": major_ids,
    }


def load_backend_school_ids() -> set[str]:
    return set(load_csv_dict(BACKEND_BIZDATA / "school_info.csv", "school_id", "school_name"))


def check_rank_references() -> dict[str, Any]:
    backend_school_ids = load_backend_school_ids()
    backend_major_sets = load_backend_major_sets()
    result: dict[str, Any] = {
        "rank_dict_files": sorted(path.name for path in RANK_DICT.iterdir() if path.is_file()),
        "datasets": {},
    }
    for file_name in ("volunteerinfo_major.json", "volunteerinfo_majorgroup.json"):
        data = load_json(RANK_DATA / file_name)
        school_ids: set[str] = set()
        major_ids: set[str] = set()
        category_ids: set[str] = set()
        sub_category_ids: set[str] = set()
        zero_major_count = 0
        for school in data:
            school_id = str(school.get("schoolId") or "").strip()
            if school_id:
                school_ids.add(school_id)
            for major in school.get("majorList") or []:
                major_id = str(major.get("majorId") or "").strip()
                category_id = str(major.get("categoryId") or "").strip()
                sub_category_id = str(major.get("subCategoryId") or "").strip()
                if major_id == "0":
                    zero_major_count += 1
                elif major_id:
                    major_ids.add(major_id)
                if category_id:
                    category_ids.add(category_id)
                if sub_category_id:
                    sub_category_ids.add(sub_category_id)
        missing_school_ids = sorted(school_ids - backend_school_ids)
        missing_major_ids = sorted(major_ids - backend_major_sets["majorIds"])
        missing_category_ids = sorted(category_ids - backend_major_sets["categoryIds"])
        missing_sub_category_ids = sorted(sub_category_ids - backend_major_sets["subCategoryIds"])
        result["datasets"][file_name] = {
            "school_count": len(school_ids),
            "major_count": len(major_ids),
            "category_count": len(category_ids),
            "sub_category_count": len(sub_category_ids),
            "zero_major_count": zero_major_count,
            "missing_school_id_count": len(missing_school_ids),
            "missing_major_id_count": len(missing_major_ids),
            "missing_category_id_count": len(missing_category_ids),
            "missing_sub_category_id_count": len(missing_sub_category_ids),
            "missing_school_ids": missing_school_ids[:20],
            "missing_major_ids": missing_major_ids[:20],
            "missing_category_ids": missing_category_ids[:20],
            "missing_sub_category_ids": missing_sub_category_ids[:20],
        }
    return result


def main() -> None:
    report = {
        "major_catalogs": [
            compare_major_json("major_bachelor.json"),
            compare_major_json("major_associate.json"),
        ],
        "province_city": compare_province_city(),
        "school_catalog": compare_school_catalog(),
        "rank_references": check_rank_references(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
