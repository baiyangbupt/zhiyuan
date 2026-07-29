#!/usr/bin/env python3
"""Replay production dialogue samples through the local agent and backend.

This is an isolated end-to-end verifier:
- production assets are input fixtures only;
- every case is written to a high-numbered local session id;
- the local agent websocket generates replies/cards;
- confirmation is sent through the normal pendingConfirmation path;
- planningState is read back to evaluate execution effects.

The script intentionally avoids touching existing local test sessions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import shutil
import tarfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import websockets


DEFAULT_ASSET_DIR = Path("assets/production-flow-verification-20260628")
DEFAULT_BACKEND_URL = "http://127.0.0.1:18090"
DEFAULT_AGENT_URL = "ws://127.0.0.1:18091/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_VOLUNTEER_DATA_DIR = Path("data/tmp")
DEFAULT_SESSION_OFFSET = 800000
DEFAULT_USER_ID = "production-flow-local-replay"
DEFAULT_REPLAY_DB_HOST = os.getenv("ZHIYUAN_REPLAY_DB_HOST", "")
DEFAULT_REPLAY_DB_PORT = int(os.getenv("ZHIYUAN_REPLAY_DB_PORT", "3306"))
DEFAULT_REPLAY_DB_NAME = os.getenv("ZHIYUAN_REPLAY_DB_NAME", "")
DEFAULT_REPLAY_DB_USER = os.getenv("ZHIYUAN_REPLAY_DB_USER", "")
DEFAULT_REPLAY_DB_PASSWORD = os.getenv("ZHIYUAN_REPLAY_DB_PASSWORD", "")
DEFAULT_REPLAY_DB_PYTHON = os.getenv("ZHIYUAN_REPLAY_DB_PYTHON", "/usr/bin/python3")


CASE_DEFS: list[dict[str, Any]] = [
    {
        "caseId": "tuition_cap_20000",
        "sourceSessionId": "2633",
        "prompt": "取消学费超过20000元的志愿",
        "expectedActionFamily": "apply_fix_proposal",
        "expectPendingKind": "plan_mutation",
        "negativeReplySubstrings": ["暂时没有匹配", "不需要从方案中移除", "最多只能替换 5"],
        "checks": {"type": "tuition_cap", "maxTuition": 20000},
    },
    {
        "caseId": "exclude_cooperative_by_name",
        "sourceSessionId": "1936",
        "prompt": "中外合作的去掉",
        "expectedActionFamilies": ["apply_fix_proposal", "remove_units"],
        "expectPendingKind": "plan_mutation",
        "negativeReplySubstrings": ["暂不自动执行", "没有找到", "暂时都没有"],
        "checks": {"type": "exclude_name_contains", "keywords": ["中外合作"]},
    },
    {
        "caseId": "only_keep_beijing_shanghai_guangdong",
        "sourceSessionId": "2947",
        "prompt": "去掉非北上广地区的院校",
        "expectedActionFamily": "apply_selected_intents",
        "expectPendingKind": "intent_change",
        "negativeReplySubstrings": ["没有唯一匹配", "点选要移除", "补充更完整"],
        "checks": {"type": "only_keep_regions", "regions": ["北京", "上海", "广东"]},
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
        if not raw:
            return {"status": response.status}
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed.setdefault("_status", response.status)
            return parsed
        return {"_status": response.status, "data": parsed}


def _backend_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + parse.urlencode(params)
    return url


def _write_extra_data(base_url: str, session_id: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "chatSessionId": session_id,
        "dataKey": key,
        "dataType": "JSON_OBJECT",
        "dataValue": value,
        "version": 0,
    }
    return _http_json(
        "POST",
        _backend_url(base_url, "/gaotu-assistant-bot/inner/chat/1/session/add-extra-data"),
        payload,
    )


def _get_extra_data(base_url: str, session_id: str, key: str) -> dict[str, Any]:
    payload = _http_json(
        "GET",
        _backend_url(
            base_url,
            "/gaotu-assistant-bot/inner/chat/1/session/get-extra-data",
            {"chatSessionId": session_id, "keyList": key, "version": 0},
        ),
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _get_planning_state(base_url: str, session_id: str) -> dict[str, Any]:
    payload = _http_json(
        "GET",
        _backend_url(
            base_url,
            "/gaotu-assistant-bot/inner/planning/1/session/state",
            {"chatSessionId": session_id},
        ),
        timeout_seconds=30,
    )
    return _unwrap_data(payload)


def _clear_pending(base_url: str, session_id: str) -> None:
    _write_extra_data(base_url, session_id, "pendingConfirmation", {})
    _write_extra_data(base_url, session_id, "planEditCache", {})


def _ensure_session_record(args: argparse.Namespace, session_id: str) -> dict[str, Any]:
    """Create the minimal ChatSession main row required by backend apply APIs."""
    if not args.ensure_session_record:
        return {"skipped": True}
    if not str(session_id).isdigit() or int(session_id) < int(args.session_offset):
        raise ValueError(f"refuse_to_touch_non_replay_session:{session_id}")
    missing = [
        name
        for name, value in {
            "ZHIYUAN_REPLAY_DB_HOST": args.replay_db_host,
            "ZHIYUAN_REPLAY_DB_NAME": args.replay_db_name,
            "ZHIYUAN_REPLAY_DB_USER": args.replay_db_user,
            "ZHIYUAN_REPLAY_DB_PASSWORD": args.replay_db_password,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise ValueError(f"missing_replay_db_config:{','.join(missing)}")
    script = r"""
import argparse
import json

import mysql.connector

parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True)
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--database", required=True)
parser.add_argument("--user", required=True)
parser.add_argument("--password", required=True)
parser.add_argument("--session-id", type=int, required=True)
parser.add_argument("--user-name", required=True)
opts = parser.parse_args()

conn = mysql.connector.connect(
    host=opts.host,
    port=opts.port,
    user=opts.user,
    password=opts.password,
    database=opts.database,
    connection_timeout=8,
)
try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, session_status AS sessionStatus FROM assistant_chat_session WHERE id = %s",
        (opts.session_id,),
    )
    existing = cur.fetchone()
    if existing is None:
        cur.execute(
            "INSERT INTO assistant_chat_session "
            "(id, tenant_id, bot_id, user_id, user_name, session_status, start_time, create_time, update_time) "
            "VALUES (%s, 1, 1, %s, %s, 1, NOW(), NOW(), NOW())",
            (opts.session_id, opts.session_id, opts.user_name),
        )
        action = "inserted"
    else:
        cur.execute(
            "UPDATE assistant_chat_session "
            "SET tenant_id = 1, "
            "bot_id = 1, "
            "user_id = COALESCE(user_id, %s), "
            "user_name = COALESCE(user_name, %s), "
            "session_status = 1, "
            "start_time = COALESCE(start_time, NOW()), "
            "update_time = NOW() "
            "WHERE id = %s",
            (opts.session_id, opts.user_name, opts.session_id),
        )
        action = "updated"
    conn.commit()
    cur.execute(
        "SELECT id, tenant_id AS tenantId, bot_id AS botId, user_id AS userId, user_name AS userName, session_status AS sessionStatus FROM assistant_chat_session WHERE id = %s",
        (opts.session_id,),
    )
    row = cur.fetchone()
    print(json.dumps({"action": action, "row": row}, ensure_ascii=True, default=str))
finally:
    conn.close()
"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [
            str(args.replay_db_python),
            "-c",
            script,
            "--host",
            str(args.replay_db_host),
            "--port",
            str(args.replay_db_port),
            "--database",
            str(args.replay_db_name),
            "--user",
            str(args.replay_db_user),
            "--password",
            str(args.replay_db_password),
            "--session-id",
            str(session_id),
            "--user-name",
            "production-flow-replay",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    return json.loads(proc.stdout)


def _normalize_session_id(state: dict[str, Any], target_session_id: str) -> dict[str, Any]:
    cloned = deepcopy(state)
    cloned["sessionId"] = int(target_session_id) if str(target_session_id).isdigit() else target_session_id
    return cloned


def _subject_code(name: str) -> str:
    mapping = {
        "物理": "01",
        "历史": "02",
        "政治": "03",
        "地理": "04",
        "化学": "05",
        "生物": "06",
        "技术": "07",
        "语文": "08",
        "数学": "10",
        "外语": "11",
    }
    return mapping.get(str(name or "").strip(), "")


def _subject_type(subjects: list[str]) -> dict[str, str]:
    names = [str(item or "").strip() for item in subjects if str(item or "").strip()]
    if "物理" in names:
        return {"code": "WL", "desc": "物理"}
    if "历史" in names:
        return {"code": "LS", "desc": "历史"}
    return {"code": "N", "desc": "综合"}


def _province_code(name: str) -> str:
    mapping = {
        "北京": "110000",
        "天津": "120000",
        "河北": "130000",
        "山西": "140000",
        "内蒙古": "150000",
        "辽宁": "210000",
        "吉林": "220000",
        "黑龙江": "230000",
        "上海": "310000",
        "江苏": "320000",
        "浙江": "330000",
        "安徽": "340000",
        "福建": "350000",
        "江西": "360000",
        "山东": "370000",
        "河南": "410000",
        "湖北": "420000",
        "湖南": "430000",
        "广东": "440000",
        "广西": "450000",
        "海南": "460000",
        "重庆": "500000",
        "四川": "510000",
        "贵州": "520000",
        "云南": "530000",
        "西藏": "540000",
        "陕西": "610000",
        "甘肃": "620000",
        "青海": "630000",
        "宁夏": "640000",
        "新疆": "650000",
    }
    return mapping.get(str(name or "").strip(), "")


def _batch_level(batch_name: str | None) -> str:
    text = str(batch_name or "")
    if "专科" in text:
        return "专科"
    if "提前" in text:
        return "本科"
    return "本科"


def _extract_student_summary(state: dict[str, Any]) -> dict[str, Any]:
    summary = state.get("studentSummary")
    if isinstance(summary, dict):
        return summary
    return {}


def _build_user_score_detail(state: dict[str, Any]) -> dict[str, Any]:
    student = _extract_student_summary(state)
    candidate_state = state.get("candidatePoolState") if isinstance(state.get("candidatePoolState"), dict) else {}
    freshness = state.get("dataFreshnessState") if isinstance(state.get("dataFreshnessState"), dict) else {}
    profile = state.get("profileState") if isinstance(state.get("profileState"), dict) else {}
    explicit = profile.get("explicitProfile") if isinstance(profile.get("explicitProfile"), dict) else {}
    physical = profile.get("physicalConstraints") if isinstance(profile.get("physicalConstraints"), dict) else {}

    province_name = (
        student.get("provinceName")
        or freshness.get("province")
        or candidate_state.get("sourceProvinceName")
        or ""
    )
    batch_name = student.get("batchName") or freshness.get("batch") or "本科批"
    batch_score = student.get("batchScore") or candidate_state.get("batchScore")
    score = student.get("score") or candidate_state.get("userScore")
    subjects = student.get("subjects") if isinstance(student.get("subjects"), list) else []
    subject_items = [
        {
            "isFirst": 1 if index == 0 else 0,
            "subjectType": "",
            "value": _subject_code(str(name)),
            "name": str(name),
        }
        for index, name in enumerate(subjects)
        if str(name or "").strip()
    ]
    subject_score_list = [
        {
            "subject": _subject_code(str(name)),
            "subjectName": str(name),
            "score": None,
        }
        for name in subjects
        if str(name or "").strip() and _subject_code(str(name))
    ]
    strength_subjects = student.get("strengthSubjects")
    if not isinstance(strength_subjects, list):
        strength_subjects = explicit.get("strengthSubjects") if isinstance(explicit.get("strengthSubjects"), list) else []
    strength_subject_list = [
        {"subject": _subject_code(str(name)), "subjectName": str(name), "score": None}
        for name in strength_subjects
        if str(name or "").strip() and _subject_code(str(name))
    ]

    preferred_majors = [
        {"majorSubId": "", "majorSubName": str(name)}
        for name in (explicit.get("positiveMajors") or [])
        if str(name or "").strip()
    ]
    unacceptable_majors = [
        {"majorId": "", "majorName": str(name)}
        for name in (explicit.get("negativeMajors") or [])
        if str(name or "").strip()
    ]
    preferred_regions = [
        {"provinceId": "", "provinceName": str(name)}
        for name in (explicit.get("positiveRegions") or [])
        if str(name or "").strip()
    ]
    volunteer_model = str(candidate_state.get("volunteerModel") or state.get("volunteerModel") or "majorGroup").strip()
    volunteer_count = {
        "schoolCount": candidate_state.get("requiredUnitCount") or candidate_state.get("requiredCount") or 45,
        "majorCount": candidate_state.get("requiredMajorCount") or 6,
    }
    special_limits = physical.get("specialLimits") if isinstance(physical.get("specialLimits"), list) else []
    accept_foreign_school = None
    if any("不接受中外合作" in str(item) for item in special_limits):
        accept_foreign_school = False

    return {
        "botId": 1,
        "userName": "生产样本回放",
        "province": {"code": _province_code(str(province_name)), "name": province_name},
        "examYear": int(freshness.get("examYear") or 2026),
        "sex": {
            "code": "male" if str(student.get("sex") or "") == "男" else "female",
            "name": str(student.get("sex") or "女"),
        },
        "subjectList": subject_items,
        "subjectType": _subject_type([str(item) for item in subjects]),
        "prepareType": {"code": str(freshness.get("prepareType") or "VOLUNTEER"), "desc": "智能填报"},
        "filterType": "2",
        "specialPlan": None,
        "minority": None,
        "colorBlindness": None,
        "bonusPolicy": False,
        "bonusScore": 0,
        "totalScore": score,
        "batch": {
            "code": "14",
            "name": batch_name,
            "score": float(batch_score) if batch_score is not None else None,
            "level": _batch_level(batch_name),
            "pos": None,
        },
        "subjectScoreList": subject_score_list,
        "targetType": None,
        "volunteerCount": volunteer_count,
        "totalScorePos": student.get("rank"),
        "volunteerModel": volunteer_model,
        "volunteerDetailModel": volunteer_model,
        "strengthSubjectList": strength_subject_list,
        "height": None,
        "colorSituation": physical.get("colorVision") if isinstance(physical.get("colorVision"), list) else [],
        "visionAbility": physical.get("vision") if isinstance(physical.get("vision"), dict) else None,
        "ethnicity": None,
        "politicalStatus": None,
        "preferredMajors": preferred_majors,
        "unacceptableMajors": unacceptable_majors,
        "acceptForeignSchool": accept_foreign_school,
        "preferredRegions": preferred_regions,
        "strategyType": {"code": "cautious", "name": "稳妥型"},
        "tuitionRange": {"min": 0, "max": 100000},
    }


def _build_user_profile(state: dict[str, Any]) -> dict[str, Any]:
    profile_state = state.get("profileState") if isinstance(state.get("profileState"), dict) else {}
    explicit = profile_state.get("explicitProfile") if isinstance(profile_state.get("explicitProfile"), dict) else {}
    physical = profile_state.get("physicalConstraints") if isinstance(profile_state.get("physicalConstraints"), dict) else {}
    return {
        "major_intent": {
            "level1": [],
            "level2": list(explicit.get("positiveMajors") or []),
            "level3": [],
            "level1_emotion": [],
            "level2_emotion": ["正向"] * len(list(explicit.get("positiveMajors") or [])),
            "level3_emotion": [],
        },
        "negative_major_intent": {
            "level1": [],
            "level2": [],
            "level3": list(explicit.get("negativeMajors") or []),
            "level1_emotion": [],
            "level2_emotion": [],
            "level3_emotion": ["负向"] * len(list(explicit.get("negativeMajors") or [])),
        },
        "college_info": {"values": list(explicit.get("positiveSchools") or []), "values_emotion": []},
        "negative_college_info": {"values": list(explicit.get("negativeSchools") or []), "values_emotion": []},
        "city_info": {
            "province": list(explicit.get("positiveRegions") or []),
            "province_emotion": ["正向"] * len(list(explicit.get("positiveRegions") or [])),
            "city": [],
            "city_emotion": [],
            "area": [],
        },
        "negative_city_info": {
            "province": list(explicit.get("negativeRegions") or []),
            "province_emotion": ["负向"] * len(list(explicit.get("negativeRegions") or [])),
            "city": [],
            "city_emotion": [],
            "area": [],
        },
        "physical_limits": physical,
    }


def _extract_volunteer_files(asset_session_dir: Path, source_session_id: str, target_session_id: str, target_dir: Path) -> list[str]:
    tar_path = asset_session_dir / "volunteer-files.tar.gz"
    copied: list[str] = []
    if not tar_path.exists():
        return copied
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if not name.startswith(f"session_volunteer_{source_session_id}"):
                continue
            suffix = name[len(f"session_volunteer_{source_session_id}") :]
            if not suffix.endswith(".json"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target_path = target_dir / f"session_volunteer_{target_session_id}{suffix}"
            with target_path.open("wb") as handle:
                shutil.copyfileobj(extracted, handle)
            copied.append(str(target_path))
    return copied


async def _ws_exchange(
    url: str,
    *,
    session_id: str,
    user_id: str,
    content: str,
    input_type: str = "text",
    response_timeout: float = 180,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "content": content,
        "inputType": input_type,
    }
    started = time.perf_counter()
    messages: list[dict[str, Any]] = []
    async with websockets.connect(url, max_size=2**24, open_timeout=30) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=response_timeout)
            message = json.loads(raw)
            messages.append(message)
            if message.get("end") is True:
                break
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            messages.append(json.loads(raw))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    primary: list[dict[str, Any]] = []
    followups: list[dict[str, Any]] = []
    primary_done = False
    for message in messages:
        message_type = str(message.get("type") or "")
        if not primary_done:
            primary.append(message)
            if message.get("end") is True:
                primary_done = True
            continue
        followups.append(message)
    return primary, followups, elapsed_ms


def _text_from_messages(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(item.get("content") or "") for item in messages if item.get("type") in {"text", "reply"}).strip()


def _content_dict(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _pending_cards(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in messages:
        if str(item.get("type") or "") != "pendingConfirmationCard":
            continue
        cards.append(_content_dict(item))
    return cards


def _ordered_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = state.get("orderedPlanState") if isinstance(state.get("orderedPlanState"), dict) else {}
    items = ordered.get("items")
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict)]
    units = ordered.get("units")
    flattened: list[dict[str, Any]] = []
    for unit in units if isinstance(units, list) else []:
        if not isinstance(unit, dict):
            continue
        unit_fields = {
            "unitId": unit.get("unitId"),
            "schoolName": unit.get("schoolName"),
            "tier": unit.get("tier"),
            "locked": unit.get("locked"),
        }
        for major in unit.get("majorItems") or []:
            if not isinstance(major, dict):
                continue
            merged = dict(unit_fields)
            merged.update({key: value for key, value in major.items() if value is not None})
            flattened.append(merged)
    return flattened


def _candidate_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidate_state = state.get("candidatePoolState") if isinstance(state.get("candidatePoolState"), dict) else {}
    items = candidate_state.get("items")
    result: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id:
            result[volunteer_id] = item
    return result


def _ordered_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = _candidate_by_id(state)
    result: list[dict[str, Any]] = []
    for item in _ordered_items(state):
        volunteer_id = str(item.get("volunteerId") or "").strip()
        candidate = by_id.get(volunteer_id)
        if candidate:
            merged = dict(candidate)
            merged.update({k: v for k, v in item.items() if v is not None})
            result.append(merged)
        else:
            result.append(item)
    return result


def _count_check_matches(state: dict[str, Any], check: dict[str, Any]) -> int:
    kind = str(check.get("type") or "")
    rows = _ordered_candidates(state)
    if kind == "tuition_cap":
        max_tuition = int(check.get("maxTuition") or 0)
        return sum(1 for item in rows if (item.get("tuitionPerYear") or 0) > max_tuition)
    if kind == "exclude_name_contains":
        keywords = [str(item) for item in check.get("keywords") or []]
        return sum(
            1
            for item in rows
            if any(keyword in str(item.get("majorName") or "") or keyword in str(item.get("schoolName") or "") for keyword in keywords)
        )
    if kind == "exclude_major_contains":
        keywords = [str(item) for item in check.get("keywords") or []]
        return sum(1 for item in rows if any(keyword in str(item.get("majorName") or "") for keyword in keywords))
    if kind == "exclude_school_contains":
        keywords = [str(item) for item in check.get("keywords") or []]
        return sum(
            1
            for item in rows
            if any(
                keyword in str(item.get("schoolName") or "")
                or keyword in str(item.get("displaySchoolName") or "")
                for keyword in keywords
            )
        )
    if kind == "exclude_school_major_contains":
        school_keywords = [str(item) for item in check.get("schoolKeywords") or check.get("school_keywords") or []]
        major_keywords = [str(item) for item in check.get("majorKeywords") or check.get("major_keywords") or []]
        return sum(
            1
            for item in rows
            if (
                not school_keywords
                or any(
                    keyword in str(item.get("schoolName") or "")
                    or keyword in str(item.get("displaySchoolName") or "")
                    for keyword in school_keywords
                )
            )
            and (
                not major_keywords
                or any(keyword in str(item.get("majorName") or "") for keyword in major_keywords)
            )
        )
    if kind == "exclude_school_nature":
        values = {str(item) for item in check.get("values") or []}
        return sum(1 for item in rows if str(item.get("schoolNature") or "") in values)
    if kind == "exclude_region":
        regions = {str(item) for item in check.get("regions") or []}
        return sum(
            1
            for item in rows
            if str(item.get("provinceName") or "") in regions
            or str(item.get("cityName") or "") in regions
        )
    if kind == "admission_ratio_lte":
        max_ratio = float(check.get("maxRatio") or 0)
        return sum(1 for item in rows if float(item.get("admissionRatio") or 0) <= max_ratio)
    if kind == "only_keep_regions":
        regions = {str(item) for item in check.get("regions") or []}
        return sum(
            1
            for item in rows
            if str(item.get("provinceName") or "") not in regions
            and str(item.get("cityName") or "") not in regions
        )
    if kind == "only_keep_major_contains":
        keywords = [str(item) for item in check.get("keywords") or []]
        return sum(1 for item in rows if not any(keyword in str(item.get("majorName") or "") for keyword in keywords))
    return 0


def _summarize_ordered(state: dict[str, Any]) -> dict[str, Any]:
    ordered = state.get("orderedPlanState") if isinstance(state.get("orderedPlanState"), dict) else {}
    summary = ordered.get("summary") if isinstance(ordered.get("summary"), dict) else {}
    return {
        "version": state.get("version"),
        "phase": state.get("phase"),
        "orderedCount": summary.get("unitTotal") or summary.get("total") or len(_ordered_items(state)),
        "summary": summary,
    }


def _target_session_id(args: argparse.Namespace, case: dict[str, Any], case_index: int) -> str:
    explicit = str(case.get("targetSessionId") or "").strip()
    if explicit:
        return explicit
    source_session_id = str(case["sourceSessionId"])
    base = int(source_session_id) + int(args.session_offset)
    if getattr(args, "unique_session_ids", False):
        base += int(case_index) * int(args.session_stride)
    return str(base)


async def _run_case(args: argparse.Namespace, case: dict[str, Any], case_index: int = 0) -> dict[str, Any]:
    source_session_id = str(case["sourceSessionId"])
    target_session_id = _target_session_id(args, case, case_index)
    asset_session_dir = Path(args.asset_dir) / "sessions" / source_session_id
    result: dict[str, Any] = {
        "caseId": case["caseId"],
        "sourceSessionId": source_session_id,
        "sessionId": target_session_id,
        "prompt": case["prompt"],
        "status": "unknown",
        "setup": {},
        "observations": {},
        "checks": {},
        "blockers": [],
        "failures": [],
        "warnings": [],
    }

    planning_payload = _read_json(asset_session_dir / "planning-state.json")
    planning_state = _normalize_session_id(_unwrap_data(planning_payload), target_session_id)
    user_score_detail = _build_user_score_detail(planning_state)
    user_profile = _build_user_profile(planning_state)

    try:
        result["setup"]["sessionRecord"] = _ensure_session_record(args, target_session_id)
        copied_files = _extract_volunteer_files(
            asset_session_dir,
            source_session_id,
            target_session_id,
            Path(args.volunteer_data_dir),
        )
        result["setup"]["copiedVolunteerFiles"] = copied_files
        result["setup"]["planningStateWrite"] = _write_extra_data(args.backend_url, target_session_id, "planningState", planning_state)
        result["setup"]["userScoreDetailWrite"] = _write_extra_data(args.backend_url, target_session_id, "userScoreDetail", user_score_detail)
        result["setup"]["userProfileWrite"] = _write_extra_data(args.backend_url, target_session_id, "userprofile", user_profile)
        result["setup"]["userInitProfileWrite"] = _write_extra_data(args.backend_url, target_session_id, "userInitProfile", user_profile)
        _clear_pending(args.backend_url, target_session_id)
        read_back = _get_extra_data(args.backend_url, target_session_id, "planningState")
        if not read_back:
            result["blockers"].append("planningState_write_readback_empty")
            result["status"] = "blocked"
            return result
        before_state = _get_planning_state(args.backend_url, target_session_id)
        result["before"] = _summarize_ordered(before_state)
        before_match_count = _count_check_matches(before_state, case.get("checks") or {})
        result["checks"]["beforeMatchCount"] = before_match_count
        if (case.get("requireBeforeMatch") or (case.get("checks") or {}).get("requireBeforeMatch")) and before_match_count <= 0:
            result["failures"].append("no_initial_check_matches")
    except (OSError, subprocess.CalledProcessError, error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        detail = f"setup_failed:{type(exc).__name__}:{exc}"
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = str(exc.stderr or "").strip()
            stdout = str(exc.stdout or "").strip()
            if stderr:
                detail += f":stderr={stderr[:1000]}"
            if stdout:
                detail += f":stdout={stdout[:1000]}"
        result["blockers"].append(detail)
        result["status"] = "blocked"
        return result

    try:
        primary, followups, elapsed_ms = await _ws_exchange(
            args.agent_url,
            session_id=target_session_id,
            user_id=args.user_id,
            content=str(case["prompt"]),
            input_type="text",
            response_timeout=args.response_timeout,
        )
        all_first_turn_messages = primary + followups
        response_text = _text_from_messages(primary)
        cards = _pending_cards(all_first_turn_messages)
        result["observations"]["firstTurnElapsedMs"] = elapsed_ms
        result["observations"]["firstTurnText"] = response_text
        result["observations"]["firstTurnTypes"] = [str(item.get("type") or "") for item in all_first_turn_messages]
        result["observations"]["pendingCards"] = cards
        for forbidden in case.get("negativeReplySubstrings") or []:
            if str(forbidden).lower() in response_text.lower():
                result["failures"].append(f"reply_contains_forbidden:{forbidden}")
        if not cards:
            result["failures"].append("no_pending_confirmation_card")
            result["status"] = "failed"
            return result
        first_card = cards[0]
        if case.get("expectPendingKind") and first_card.get("kind") != case.get("expectPendingKind"):
            result["failures"].append(f"pending_kind_mismatch:{first_card.get('kind')}")
        expected_actions = [str(item) for item in (case.get("expectedActionFamilies") or []) if str(item)]
        expected_action = str(case.get("expectedActionFamily") or "")
        if expected_action:
            expected_actions.append(expected_action)
        actual_action = str(first_card.get("actionFamily") or "")
        if expected_actions and actual_action not in expected_actions:
            result["failures"].append(f"pending_action_family_mismatch:{actual_action}")
        pending_id = str(first_card.get("pendingId") or "")
        if not pending_id:
            result["failures"].append("pending_card_missing_pending_id")
            result["status"] = "failed"
            return result
    except (OSError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as exc:
        result["blockers"].append(f"first_turn_failed:{type(exc).__name__}:{exc}")
        result["status"] = "blocked"
        return result

    try:
        confirm_content = json.dumps(
            {
                "action": "confirm",
                "kind": first_card.get("kind") or "plan_mutation",
                "pendingId": pending_id,
                "message_id": first_card.get("message_id"),
            },
            ensure_ascii=False,
        )
        confirm_primary, confirm_followups, confirm_elapsed_ms = await _ws_exchange(
            args.agent_url,
            session_id=target_session_id,
            user_id=args.user_id,
            content=confirm_content,
            input_type="pendingConfirmation",
            response_timeout=args.response_timeout,
        )
        confirm_text = _text_from_messages(confirm_primary)
        result["observations"]["confirmElapsedMs"] = confirm_elapsed_ms
        result["observations"]["confirmText"] = confirm_text
        result["observations"]["confirmTypes"] = [str(item.get("type") or "") for item in confirm_primary + confirm_followups]
        after_state = _get_planning_state(args.backend_url, target_session_id)
        result["after"] = _summarize_ordered(after_state)
        after_match_count = _count_check_matches(after_state, case.get("checks") or {})
        result["checks"]["afterMatchCount"] = after_match_count
        pending_state = _get_extra_data(args.backend_url, target_session_id, "pendingConfirmation")
        result["observations"]["pendingStatusAfterConfirm"] = pending_state.get("status")
        if pending_state.get("status") != "applied":
            result["failures"].append(f"pending_not_applied:{pending_state.get('status')}")
        if after_match_count >= before_match_count and before_match_count > 0:
            result["failures"].append(
                f"plan_match_count_not_reduced:before={before_match_count},after={after_match_count}"
            )
        if "失效" in confirm_text or "没有执行成功" in confirm_text or "缺少" in confirm_text:
            result["failures"].append("confirm_reply_indicates_failure")
    except (OSError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as exc:
        result["blockers"].append(f"confirm_turn_failed:{type(exc).__name__}:{exc}")
        result["status"] = "blocked"
        return result

    result["status"] = "failed" if result["failures"] else "passed"
    return result


def _load_case_defs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.case_file:
        return list(CASE_DEFS)
    payload = json.loads(Path(args.case_file).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("case_file must be a JSON list or an object with a cases list")
    cases = [case for case in raw_cases if isinstance(case, dict)]
    if len(cases) != len(raw_cases):
        raise ValueError("case_file contains non-object case entries")
    return cases


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    selected = set(args.case_id or [])
    cases = [case for case in _load_case_defs(args) if not selected or case["caseId"] in selected]
    semaphore = asyncio.Semaphore(max(1, int(args.parallelism)))

    async def run_one(index: int, case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await _run_case(args, case, index)

    records = await asyncio.gather(*(run_one(index, case) for index, case in enumerate(cases)))
    summary: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return {
        "backendUrl": args.backend_url,
        "agentUrl": args.agent_url,
        "assetDir": args.asset_dir,
        "caseFile": args.case_file,
        "parallelism": args.parallelism,
        "sessionOffset": args.session_offset,
        "records": records,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay production dialogue samples through local agent/backend.")
    parser.add_argument("--asset-dir", default=str(DEFAULT_ASSET_DIR))
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--agent-url", default=DEFAULT_AGENT_URL)
    parser.add_argument("--volunteer-data-dir", default=str(DEFAULT_VOLUNTEER_DATA_DIR))
    parser.add_argument("--session-offset", type=int, default=DEFAULT_SESSION_OFFSET)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--case-file", default="", help="JSON list or object with a cases list")
    parser.add_argument("--case-id", action="append", help="run only the named case; can be repeated")
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--unique-session-ids", action="store_true")
    parser.add_argument("--session-stride", type=int, default=10000)
    parser.add_argument("--response-timeout", type=float, default=180)
    parser.add_argument("--ensure-session-record", action="store_true")
    parser.add_argument("--replay-db-host", default=DEFAULT_REPLAY_DB_HOST)
    parser.add_argument("--replay-db-port", type=int, default=DEFAULT_REPLAY_DB_PORT)
    parser.add_argument("--replay-db-name", default=DEFAULT_REPLAY_DB_NAME)
    parser.add_argument("--replay-db-user", default=DEFAULT_REPLAY_DB_USER)
    parser.add_argument("--replay-db-password", default=DEFAULT_REPLAY_DB_PASSWORD)
    parser.add_argument("--replay-db-python", default=DEFAULT_REPLAY_DB_PYTHON)
    parser.add_argument("--output", default="assets/production-flow-verification-20260628/local-dialog-flow-replay.json")
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": result["summary"]}, ensure_ascii=False, indent=2))
    for record in result["records"]:
        print(
            json.dumps(
                {
                    "caseId": record.get("caseId"),
                    "sessionId": record.get("sessionId"),
                    "status": record.get("status"),
                    "beforeMatchCount": (record.get("checks") or {}).get("beforeMatchCount"),
                    "afterMatchCount": (record.get("checks") or {}).get("afterMatchCount"),
                    "blockers": record.get("blockers"),
                    "failures": record.get("failures"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
