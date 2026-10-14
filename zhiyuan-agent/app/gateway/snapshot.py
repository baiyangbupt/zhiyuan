from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.admission.facts import AdmissionFactError, canonical_admission_mode
from app.domain.career_slots import normalize_career_labels
from app.gateway.contracts import ConversationTurnSnapshot, StatePatch

# `turn-snapshot` 的 `scoreContext` 用 `strengthSubjects` ✓，投影出的用 `subjects` ✓——
# 别名不对上，真载荷的选科会整个丢掉 ✗（补缺那条路会变成"补进来但没人认得" ✗）。
_SCORE_CONTEXT_ALIASES = {"strengthSubjects": "subjects"}


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def build_snapshot(workspace: Mapping[str, Any]) -> ConversationTurnSnapshot:
    """Project backend workspace state into a bounded model-facing snapshot."""
    if not isinstance(workspace, Mapping):
        raise ValueError("workspace payload must be an object")
    session_id = _first(workspace, "sessionId", "session_id")
    if session_id in (None, ""):
        raise ValueError("workspace sessionId is required")

    candidate_pool = workspace.get("candidatePoolState") or {}
    raw_mode = _first(
        workspace,
        "admissionMode",
        "admission_mode",
        default=_first(candidate_pool, "volunteerModel", "volunteer_model", default="major"),
    )
    try:
        admission_mode = canonical_admission_mode(raw_mode)
    except AdmissionFactError as exc:
        raise ValueError(exc.code) from exc

    summary = workspace.get("studentSummary") or {}
    profile = workspace.get("profileState") or {}
    constraints = workspace.get("constraintState") or {}
    explicit = profile.get("explicitProfile") or {}
    hard = constraints.get("hardConstraints") or {}
    soft = constraints.get("softPreferences") or {}
    # 发展方向（career v1）：存在 `latentProfile.futureDevelopment.careerTypes`（**中文规范
    # 标签**）。turn-snapshot 的投影 DTO 里**没有** latentProfile（Java 侧未暴露）——
    # 数据由组合层**agent 侧直读**补进 workspace 形状（`server.py` 的 snapshot_loader
    # 包装，见 `_attach_career_directions`），这里只负责把它摆到模型面前。
    latent = profile.get("latentProfile") or {}
    future_development = latent.get("futureDevelopment") or {}
    career_types = []
    if isinstance(future_development, Mapping):
        raw_career = future_development.get("careerTypes")
        if isinstance(raw_career, list):
            # 落库已归一（中文标签）；这里再归一一次是**旧数据护栏**（历史上可能写过槽位名）。
            career_types = normalize_career_labels([str(item) for item in raw_career])

    score_context = {
        key: value
        for key, value in {
            "province": _first(summary, "provinceName", "province"),
            "examYear": _first(summary, "examYear", "year"),
            "score": _first(summary, "score"),
            "rank": _first(summary, "rank", "position"),
            "batch": _first(summary, "batchName", "batch"),
            "subjects": _first(summary, "subjects", default=[]),
        }.items()
        if value not in (None, "")
    }
    # `turn-snapshot` **已经把成绩上下文算好了** ✓（Java 权威 ✓：真载荷含 `batch`/`batchScore`/
    # `strengthSubjects` ✓），而 `studentSummary` 里**没有 `batch`** ✗（真栈实测 ✓）。
    # 口径：**派生值优先** ✓（别处依赖它的形状 ✓），这里只**补缺** ✗——
    # 缺 `batch` 会让网关解析专业 ID 时拿不到学历层次 ✗ → 目录返回 `multi` ✗ →
    # 安全阀不取 ID ✓ →"专业 ID 优先"在真栈上等于没接（报告第三十四轮 ✓）。
    authoritative = workspace.get("scoreContext") or workspace.get("score_context")
    if isinstance(authoritative, Mapping):
        for key, value in authoritative.items():
            target = _SCORE_CONTEXT_ALIASES.get(str(key), str(key))
            # **空值也算缺** ✓：派生出的 `subjects` 在没有 summary 时是 `[]` ✓，
            # 只判"键在不在"会把它当成已有值 ✗，权威的选科就永远补不进来 ✗。
            if value not in (None, "") and score_context.get(target) in (None, "", [], {}):
                score_context[target] = value
    confirmed_constraints = {
        key: value
        for key, value in {
            "hard": hard,
            "excludedMajors": _first(explicit, "negativeMajors", default=[]),
            "excludedSchools": _first(explicit, "negativeSchools", default=[]),
            "excludedRegions": _first(explicit, "negativeRegions", default=[]),
            "exclusions": _first(
                explicit,
                "unacceptableMajors",
                "excludedMajors",
                "negativeMajors",
                default=[],
            ),
        }.items()
        if value not in (None, {}, [])
    }
    preferences = {
        key: value
        for key, value in {
            "major": _first(explicit, "majorPreferences", "positiveMajors", default={}),
            "school": _first(explicit, "schoolPreferences", "positiveSchools", default={}),
            "region": _first(explicit, "regionPreferences", "positiveRegions", default={}),
            "soft": soft,
            # career v1：**弱偏好**——只进推荐理由/排序/解释与方案方向覆盖核对，
            # **不做硬筛**（不排除院校/专业）。只摆中文规范标签，与落库同一形式。
            "careerTypes": career_types,
        }.items()
        if value not in (None, {}, [])
    }

    missing = list(workspace.get("missingFacts") or [])
    if "score" not in score_context and "score" not in missing:
        missing.append("score")
    if "rank" not in score_context and "rank" not in missing:
        missing.append("rank")

    allowed = list(workspace.get("allowedCapabilities") or [])
    if not allowed:
        allowed = ["catalog_read", "admission_read"]
    allowed = [capability for capability in allowed if capability not in {"plan_apply", "write", "shell"}]

    return ConversationTurnSnapshot(
        snapshot_version=int(_first(workspace, "version", "snapshotVersion", default=0) or 0),
        session_id=str(session_id),
        admission_mode=admission_mode,
        planning_stage=str(_first(workspace, "phase", "planningStage", default="")),
        score_context=score_context,
        confirmed_constraints=confirmed_constraints,
        preferences=preferences,
        active_proposal=workspace.get("activeProposal"),
        missing_facts=missing,
        allowed_capabilities=allowed,
        evidence=list(workspace.get("evidence") or []),
        admission_facts=list(workspace.get("admissionFacts") or workspace.get("admission_facts") or []),
    )


def diff_snapshots(
    before: ConversationTurnSnapshot, after: ConversationTurnSnapshot
) -> StatePatch:
    if after.snapshot_version != before.snapshot_version + 1:
        raise ValueError("snapshot versions must be adjacent")
    before_payload = before.model_dump(by_alias=True)
    after_payload = after.model_dump(by_alias=True)
    allowed = {
        "scoreContext",
        "confirmedConstraints",
        "preferences",
        "planningStage",
        "activeProposal",
        "missingFacts",
        "allowedCapabilities",
        "admissionMode",
    }
    changes = [
        {"path": path, "oldValue": before_payload[path], "newValue": after_payload[path]}
        for path in allowed
        if before_payload[path] != after_payload[path]
    ]
    invalidations: list[dict[str, Any]] = []
    before_stale = set(before.missing_facts)
    after_stale = set(after.missing_facts)
    for fact in sorted(after_stale - before_stale):
        invalidations.append({"path": "missingFacts", "fact": fact})
    if before.admission_mode != after.admission_mode:
        invalidations.extend(
            {"kind": kind, "reason": "mode_changed"}
            for kind in ("admission_mode", "evidence", "candidate", "review", "artifact", "proposal")
        )
    return StatePatch(
        base_version=before.snapshot_version,
        target_version=after.snapshot_version,
        changes=changes,
        invalidations=invalidations,
    )
