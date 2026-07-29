#!/usr/bin/env python3
"""Verify production dialogue/plan flow capabilities without mutating production.

This script reads assets collected by collect_production_flow_assets.py and
optionally calls production read-only proposal-generation endpoints through SSH.
It never calls apply endpoints unless --allow-apply is explicitly added. The
default mode is suitable for production inspection.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_HOST = os.getenv("ZHIYUAN_PRODUCTION_ASSET_HOST", "")
DEFAULT_BASE_URL = os.getenv("ZHIYUAN_PRODUCTION_ASSET_BASE_URL", "http://127.0.0.1:8090")
DEFAULT_TENANT_ID = os.getenv("ZHIYUAN_PRODUCTION_ASSET_TENANT_ID", "1")


def _run_ssh_json_post(host: str, url: str, payload: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    raw_payload = json.dumps(payload, ensure_ascii=False)
    remote = (
        "curl -s --max-time 20 -X POST "
        "-H 'Content-Type: application/json' "
        "-H 'Accept: application/json' "
        "--data-binary "
        + json.dumps(raw_payload)
        + " "
        + json.dumps(url)
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, remote],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return {"code": -1, "msg": proc.stderr.strip(), "data": None}
    try:
        parsed = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"code": -1, "msg": f"non-json response: {proc.stdout[:200]}", "data": None}
    return parsed if isinstance(parsed, dict) else {"code": 0, "data": parsed}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_ready_proposal(data: dict[str, Any]) -> dict[str, Any] | None:
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    proposals = body.get("proposals") if isinstance(body.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        if str(proposal.get("status") or "").strip() == "ready":
            return proposal
    return proposals[0] if proposals and isinstance(proposals[0], dict) else None


def _proposal_summary(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    proposal = _first_ready_proposal(response)
    actions = proposal.get("actions") if isinstance(proposal, dict) and isinstance(proposal.get("actions"), list) else []
    return {
        "code": response.get("code"),
        "msg": response.get("msg"),
        "stateStatus": data.get("status"),
        "total": data.get("total"),
        "sourceVersionGuard": data.get("sourceVersionGuard"),
        "proposalId": proposal.get("proposalId") if isinstance(proposal, dict) else None,
        "proposalStatus": proposal.get("status") if isinstance(proposal, dict) else None,
        "strategy": proposal.get("strategy") if isinstance(proposal, dict) else None,
        "title": proposal.get("title") if isinstance(proposal, dict) else None,
        "summary": proposal.get("summary") if isinstance(proposal, dict) else None,
        "impact": proposal.get("impact") if isinstance(proposal, dict) else None,
        "actionCount": len(actions),
        "actions": [
            {
                "type": action.get("actionType") or action.get("type"),
                "summary": action.get("summary"),
                "detail": action.get("detail"),
                "volunteerCount": len(action.get("volunteerIds") or []),
                "unitCount": len(action.get("unitIds") or []),
                "replacementCount": len(action.get("replacementPairs") or []),
            }
            for action in actions
            if isinstance(action, dict)
        ],
    }


def _historical_execution_evidence(session_dir: Path) -> dict[str, Any]:
    messages = _load_json(session_dir / "messages.json")
    rows = messages.get("data") if isinstance(messages.get("data"), list) else []
    card_count = 0
    pending_cards: list[dict[str, Any]] = []
    applied_texts: list[str] = []
    workspace_actions = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        content_text = row.get("content")
        content = content_text
        if isinstance(content_text, str) and content_text.strip().startswith("{"):
            try:
                content = json.loads(content_text)
            except Exception:
                content = content_text
        if isinstance(content, dict):
            if content.get("type") == "pendingConfirmationCard":
                card_count += 1
                pending_cards.append(
                    {
                        "pendingId": content.get("pendingId"),
                        "kind": content.get("kind"),
                        "actionFamily": content.get("actionFamily"),
                        "title": content.get("title"),
                        "summary": _compact_text(content.get("summary") or content.get("content"), 300),
                        "status": content.get("status"),
                    }
                )
            if content.get("type") == "planningWorkspaceAction":
                workspace_actions += 1
        text = content_text if isinstance(content_text, str) else json.dumps(content_text, ensure_ascii=False)
        if any(token in text for token in ("已从当前方案", "已按", "已刷新排序方案", "已移除", "已补入", "已更新")):
            applied_texts.append(text[:500].replace("\n", " "))
    return {
        "pendingCardCount": card_count,
        "pendingCards": pending_cards[-5:],
        "workspaceActionCount": workspace_actions,
        "appliedEvidenceCount": len(applied_texts),
        "appliedEvidence": applied_texts[-3:],
    }


def _compact_text(value: Any, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").strip()[:limit]


def _sum_action_count(proposal_summary: dict[str, Any] | None, action_summary: str) -> int:
    total = 0
    for action in (proposal_summary or {}).get("actions") or []:
        if not isinstance(action, dict):
            continue
        summary = str(action.get("summary") or "")
        if action_summary in summary:
            total += int(action.get("volunteerCount") or 0)
    return total


def _audit_case(case: dict[str, Any],
                historical: dict[str, Any],
                proposal_summary: dict[str, Any] | None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    case_id = case.get("caseId")
    cards = historical.get("pendingCards") if isinstance(historical.get("pendingCards"), list) else []
    applied_text = "\n".join(str(item) for item in historical.get("appliedEvidence") or [])
    proposal_summary_text = str((proposal_summary or {}).get("summary") or "")
    proposal_impact_text = str((proposal_summary or {}).get("impact") or "")

    if case_id == "only_keep_clinical":
        if any(str(card.get("actionFamily") or "") == "remove_units" for card in cards) and "临床医学" in applied_text:
            findings.append({
                "severity": "P0",
                "code": "historical_only_keep_reversed_to_remove",
                "message": "历史线上卡片把“严格只保留临床医学”发成 remove_units，并在执行文本里移出了临床医学志愿，属于语义反向执行。",
            })
        if (proposal_summary or {}).get("proposalStatus") == "blocked":
            findings.append({
                "severity": "info",
                "code": "current_state_after_bad_execution_not_decisive",
                "message": "该 session 的当前生产状态已经被历史错误执行改写，当前 blocked 不能用来判断修复后 only_keep 能力。",
            })

    if case_id == "tuition_cap_20000":
        if "本次能替换 5 条" in proposal_summary_text and "暂时没有合适补位" in proposal_impact_text:
            findings.append({
                "severity": "P1",
                "code": "production_candidate_limit_affects_execution",
                "message": "当前生产提案仍表现为最多替换 5 条，剩余超预算项被误判无补位，符合 PREVIEW_CANDIDATE_LIMIT 截断候选池的旧问题。",
            })

    if case_id == "exclude_cooperative":
        if (proposal_summary or {}).get("proposalStatus") == "blocked" and "没有对应到明确范围" in proposal_summary_text:
            findings.append({
                "severity": "P1",
                "code": "production_special_limit_scope_not_mapped",
                "message": "当前生产对 entityType=special_limit 的“中外合作”仍走澄清 blocked，没有进入名字匹配和可执行调整预览。",
            })

    if case_id == "only_keep_beishangguang":
        remove_count = _sum_action_count(proposal_summary, "不在保留范围内")
        if remove_count >= 30:
            findings.append({
                "severity": "P2",
                "code": "large_scope_only_keep_requires_strong_confirmation",
                "message": f"当前生产可生成 only_keep 地域调整，但预计移出 {remove_count} 条，属于大范围改动，卡片文案和确认边界必须非常明确。",
            })

    if case_id in {"exclude_medicine", "exclude_school"} and (proposal_summary or {}).get("proposalStatus") == "ready":
        findings.append({
            "severity": "pass",
            "code": "proposal_ready",
            "message": "当前生产可生成 ready 方案调整预览；仍需结合执行确认链路验证。",
        })

    return findings


def _request_for_case(case: dict[str, Any], version: int) -> dict[str, Any]:
    request = {
        "proposalSource": "user_goal",
        "goalType": case["goalType"],
        "userOriginalText": case["prompt"],
        "confidence": "high",
        "sourceVersionGuard": version,
    }
    if "negativeScopes" in case:
        request["negativeScopes"] = case["negativeScopes"]
    if "targetScopes" in case:
        request["targetScopes"] = case["targetScopes"]
    if "context" in case:
        request["context"] = case["context"]
    if "sourceReviewIssueCodes" in case:
        request["sourceReviewIssueCodes"] = case["sourceReviewIssueCodes"]
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify production flow capabilities.")
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--output", default="")
    parser.add_argument("--skip-production-proposal", action="store_true")
    args = parser.parse_args()
    if not args.skip_production_proposal and not str(args.host or "").strip():
        raise SystemExit("missing --host or ZHIYUAN_PRODUCTION_ASSET_HOST")

    asset_dir = Path(args.asset_dir)
    manifest = _load_json(asset_dir / "manifest.json")
    sessions = {str(item.get("sessionId")): item for item in manifest.get("sessions", []) if isinstance(item, dict)}

    cases = [
        {
            "caseId": "only_keep_clinical",
            "sessionId": "2752",
            "prompt": "严格只保留临床医学",
            "goalType": "only_keep_scope",
            "targetScopes": [{"entityType": "major", "normalizedName": "临床医学", "name": "临床医学", "scopeLevel": "level3"}],
        },
        {
            "caseId": "exclude_medicine",
            "sessionId": "2811",
            "prompt": "不要医学类的",
            "goalType": "exclude_scope",
            "negativeScopes": [{"entityType": "major", "normalizedName": "医学", "name": "医学", "scopeLevel": "level1"}],
        },
        {
            "caseId": "tuition_cap_20000",
            "sessionId": "2633",
            "prompt": "取消学费超过20000元的志愿",
            "goalType": "tuition_budget_scope",
            "context": {"maxTuitionPerYear": 20000},
            "targetScopes": [
                {
                    "entityType": "budget",
                    "normalizedName": "学费不超过20000元/年",
                    "name": "学费不超过20000元/年",
                    "evidence": {"maxTuitionPerYear": 20000},
                }
            ],
        },
        {
            "caseId": "exclude_cooperative",
            "sessionId": "1936",
            "prompt": "中外合作的去掉",
            "goalType": "exclude_scope",
            "negativeScopes": [{"entityType": "special_limit", "normalizedName": "中外合作", "name": "中外合作"}],
            "sourceReviewIssueCodes": ["cooperative_program"],
        },
        {
            "caseId": "only_keep_beishangguang",
            "sessionId": "2947",
            "prompt": "去掉非北上广地区的院校",
            "goalType": "only_keep_scope",
            "targetScopes": [
                {"entityType": "region", "normalizedName": "北京", "name": "北京", "scopeLevel": "city"},
                {"entityType": "region", "normalizedName": "上海", "name": "上海", "scopeLevel": "city"},
                {"entityType": "region", "normalizedName": "广州", "name": "广州", "scopeLevel": "city"},
                {"entityType": "region", "normalizedName": "深圳", "name": "深圳", "scopeLevel": "city"},
            ],
        },
        {
            "caseId": "exclude_school",
            "sessionId": "2784",
            "prompt": "南京理工不要",
            "goalType": "exclude_scope",
            "negativeScopes": [{"entityType": "school", "normalizedName": "南京理工大学", "name": "南京理工大学"}],
        },
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        session_id = case["sessionId"]
        session_manifest = sessions.get(session_id) or {}
        workspace = session_manifest.get("workspace") if isinstance(session_manifest.get("workspace"), dict) else {}
        version = int(workspace.get("version") or 0)
        session_dir = asset_dir / "sessions" / session_id
        request_payload = _request_for_case(case, version)
        response: dict[str, Any] | None = None
        if not args.skip_production_proposal:
            response = _run_ssh_json_post(
                args.host,
                (
                    f"{args.base_url.rstrip()}/gaotu-assistant-bot/inner/planning/"
                    f"{args.tenant_id}/session/fix-proposals/user-goal/generate?chatSessionId={session_id}"
                ),
                request_payload,
            )
        historical = _historical_execution_evidence(session_dir)
        proposal_summary = _proposal_summary(response or {}) if response is not None else None
        result = {
            "caseId": case["caseId"],
            "sessionId": session_id,
            "prompt": case["prompt"],
            "goalType": case["goalType"],
            "workspace": workspace,
            "historicalExecution": historical,
            "proposalRequest": request_payload,
            "proposalSummary": proposal_summary,
            "auditFindings": _audit_case(case, historical, proposal_summary),
        }
        results.append(result)

    overall_findings = [
        {
            "caseId": result["caseId"],
            "sessionId": result["sessionId"],
            **finding,
        }
        for result in results
        for finding in result.get("auditFindings", [])
        if finding.get("severity") != "pass"
    ]
    output = {
        "assetDir": str(asset_dir),
        "productionProposalChecked": not args.skip_production_proposal,
        "results": results,
        "overallFindings": overall_findings,
    }
    out_path = Path(args.output or asset_dir / "flow-capability-report.json")
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out_path), "cases": len(results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
