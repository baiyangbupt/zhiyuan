#!/usr/bin/env python3
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = Path(os.getenv("ZHIYUAN_SESSION_FILE", str(ROOT / "data" / "tmp" / "session_volunteer_18.json")))
LOG_DIR = ROOT / "logs"
SESSION_ID = int(os.getenv("ZHIYUAN_SESSION_ID", "18"))
TARGET_SCHOOL = os.getenv("ZHIYUAN_TARGET_SCHOOL", "广东药科大学")


def load_session_json():
    if not SESSION_FILE.exists():
        raise SystemExit(f"missing session file: {SESSION_FILE}. Set ZHIYUAN_SESSION_FILE to an external sample path.")
    return json.loads(SESSION_FILE.read_text())


def flatten_raw_candidates(payload):
    rows = []
    for school in payload.get("detailList", []):
        school_name = school.get("schoolUnitName") or school.get("schoolName") or ""
        plan_school_data_id = school.get("planSchoolDataId") or ""
        province = ((school.get("area") or {}).get("data")) or ""
        city = ((school.get("city") or {}).get("data")) or ""
        school_ratio = school.get("enrollRatio")
        school_level = ((school.get("volunteerLevel") or {}).get("desc")) or ""
        majors = school.get("majorVOList") or []
        if not majors:
            rows.append(
                {
                    "planSchoolDataId": plan_school_data_id,
                    "schoolName": school_name,
                    "province": province,
                    "city": city,
                    "schoolEnrollRatio": to_float(school_ratio),
                    "majorName": "",
                    "majorId": "",
                    "majorEnrollRatio": to_float(school_ratio),
                    "tier": school_level,
                    "score": school.get("score"),
                    "pos": school.get("schoolPos"),
                }
            )
            continue
        for major in majors:
            rows.append(
                {
                    "planSchoolDataId": plan_school_data_id,
                    "schoolName": school_name,
                    "province": province,
                    "city": city,
                    "schoolEnrollRatio": to_float(school_ratio),
                    "majorName": major.get("majorName") or major.get("unitName") or "",
                    "majorId": major.get("majorId") or "",
                    "majorEnrollRatio": to_float(major.get("enrollRatio")),
                    "tier": ((major.get("volunteerLevel") or {}).get("desc")) or school_level,
                    "score": major.get("score"),
                    "pos": major.get("pos"),
                }
            )
    return rows


def to_float(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def extract_latest_planning_state():
    candidates = sorted(LOG_DIR.glob("app_name_IS_UNDEFINED.log*"))
    pattern = re.compile(r"Parameters:\s*18\(Long\), planningState\(String\), 0\(Integer\), \d+\(Integer\), (\{.*\})\(String\),")
    latest = None
    latest_file = None
    for path in candidates:
        try:
            for line in path.read_text(errors="ignore").splitlines():
                if '"sessionId":18' not in line or "planningState(String)" not in line:
                    continue
                match = pattern.search(line)
                if match:
                    latest = json.loads(match.group(1))
                    latest_file = path
        except Exception:
            continue
    return latest, latest_file


def summarize_raw(rows):
    unit_map = defaultdict(list)
    for row in rows:
        unit_map[row["planSchoolDataId"]].append(row)
    tier_unit_counts = Counter()
    tier_entry_counts = Counter()
    for row in rows:
        tier_entry_counts[row["tier"]] += 1
    for unit_rows in unit_map.values():
        tier = unit_rows[0]["tier"]
        tier_unit_counts[tier] += 1
    return {
        "entry_total": len(rows),
        "unit_total": len(unit_map),
        "tier_entry_counts": dict(tier_entry_counts),
        "tier_unit_counts": dict(tier_unit_counts),
        "unit_map": unit_map,
    }


def print_ratio_bucket(rows, lo=13.0, hi=15.0, limit=30):
    bucket = [
        row for row in rows
        if row["majorEnrollRatio"] is not None and lo <= row["majorEnrollRatio"] <= hi
    ]
    bucket.sort(key=lambda row: (row["majorEnrollRatio"], row["schoolName"], row["majorName"]))
    print(f"\n[录取率 {lo:.1f}% ~ {hi:.1f}% 的原始候选，共 {len(bucket)} 条]")
    for row in bucket[:limit]:
        print(
            f"- {row['schoolName']} | {row['majorName']} | 省份={row['province']} | "
            f"专业录取率={row['majorEnrollRatio']:.1f}% | 组录取率={fmt(row['schoolEnrollRatio'])} | tier={row['tier']}"
        )
    if len(bucket) > limit:
        print(f"... 其余 {len(bucket) - limit} 条省略")


def fmt(value):
    return "-" if value is None else f"{value:.1f}%"


def analyze_target(raw_summary, planning_state):
    target_units = [
        (unit_id, rows)
        for unit_id, rows in raw_summary["unit_map"].items()
        if TARGET_SCHOOL in rows[0]["schoolName"]
    ]
    print(f"\n[{TARGET_SCHOOL} 原始供给]")
    if not target_units:
        print("未在 session_volunteer_18.json 中找到该院校。")
        return
    for unit_id, rows in target_units:
        print(f"- unit={unit_id} school={rows[0]['schoolName']} province={rows[0]['province']} majors={len(rows)} schoolEnrollRatio={fmt(rows[0]['schoolEnrollRatio'])}")
        for row in rows:
            print(f"  - {row['majorName']} | majorRatio={fmt(row['majorEnrollRatio'])}")

    if not planning_state:
        print("\n未解析到 planningState，无法继续判断是否进入初始方案。")
        return

    profile = (((planning_state.get("profileState") or {}).get("explicitProfile")) or {})
    positive_regions = profile.get("positiveRegions") or []
    negative_regions = profile.get("negativeRegions") or []
    ordered_items = (((planning_state.get("orderedPlanState") or {}).get("items")) or [])
    candidate_items = (((planning_state.get("candidatePoolState") or {}).get("items")) or [])
    candidate_map = {item.get("volunteerId"): item for item in candidate_items if item.get("volunteerId")}
    target_selected = []
    for item in ordered_items:
        candidate = candidate_map.get(item.get("volunteerId"))
        if candidate and TARGET_SCHOOL in (candidate.get("schoolName") or ""):
            target_selected.append((item, candidate))

    print("\n[画像地域偏好]")
    print(f"- positiveRegions={positive_regions}")
    print(f"- negativeRegions={negative_regions}")

    print(f"\n[{TARGET_SCHOOL} 是否进入当前方案]")
    if not target_selected:
        print("未在 orderedPlanState.items 中找到该院校。")
        return

    for ordered_item, candidate in target_selected:
        print(
            f"- position={ordered_item.get('position')} tier={ordered_item.get('tier')} "
            f"school={candidate.get('schoolName')} major={candidate.get('majorName')} "
            f"province={candidate.get('provinceName')} finalScore={candidate.get('finalScore'):.4f} "
            f"intentScore={candidate.get('intentScore'):.4f} baseScore={candidate.get('baseScore'):.4f} "
            f"admissionRatio={fmt(candidate.get('admissionRatio'))} schoolEnrollRatio={fmt(candidate.get('schoolEnrollRatio'))} "
            f"preferred={candidate.get('preferred')}"
        )
        print(f"  reasonCodes={candidate.get('reasonCodes')}")

    selected = []
    for ordered_item in ordered_items:
        candidate = candidate_map.get(ordered_item.get("volunteerId"))
        if not candidate:
            continue
        ratio = candidate.get("admissionRatio")
        if ratio is None or not (10 <= ratio <= 20):
            continue
        selected.append((ordered_item, candidate))
    selected.sort(key=lambda pair: pair[0].get("position") or 999)
    print("\n[当前方案中录取率 10%~20% 的条目]")
    for ordered_item, candidate in selected:
        print(
            f"- pos={ordered_item.get('position')} {candidate.get('schoolName')} | {candidate.get('majorName')} | "
            f"province={candidate.get('provinceName')} | ratio={fmt(candidate.get('admissionRatio'))} | "
            f"finalScore={candidate.get('finalScore'):.4f} | preferred={candidate.get('preferred')}"
        )


def main():
    payload = load_session_json()
    rows = flatten_raw_candidates(payload)
    summary = summarize_raw(rows)
    print("[session_volunteer_18.json 原始统计]")
    print(f"- 专业条目总数: {summary['entry_total']}")
    print(f"- 专业组总数: {summary['unit_total']}")
    print(f"- 条目冲稳保: {summary['tier_entry_counts']}")
    print(f"- 专业组冲稳保: {summary['tier_unit_counts']}")
    planning_state, source = extract_latest_planning_state()
    if source:
        print(f"- 最新 planningState 日志来源: {source}")
    else:
        print("- 未找到可解析的 planningState 日志")
    print_ratio_bucket(rows, 13.0, 15.0)
    analyze_target(summary, planning_state)


if __name__ == "__main__":
    main()
