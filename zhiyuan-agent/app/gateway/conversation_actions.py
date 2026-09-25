"""将模型表达的会话动作桥接到后端 Pending/CAS 接口。

本模块不解析自然语言，也不决定模型是否应该确认；它只消费已经通过
Gateway 合约校验的结构化 ConversationAction。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping
import logging
import uuid

from app.gateway.contracts import ConversationAction, ConversationTurnSnapshot
from app.util.internal_client import execute_pending_planning_command, resolve_pending_confirmation

logger = logging.getLogger(__name__)


# 写闭环的命令类型：与 Java `PendingPlanningCommandBizService` 的常量分支一致。
APPLY_PLAN_CHANGE_PROPOSAL = "apply_plan_change_proposal"
# 范围类目标（加/删学校、只看省内、学费上限）走的是**另一条**命令 ✗→✓：
# `apply_plan_change_proposal` 的 user-goal 分支只认计数/排序两种（fill_to_count /
# prioritize_within_tier），范围类会被 40001 `unsupported plan change goalType` 拒 ✗
# （2026-09-24 真栈实测）。legacy 链一直用 `apply_constraint_and_regenerate` + 一个
# `constraintUpdate` 做这件事 ✓（`app/zhiyuan_agent/tools.py` 的参照调用 ✓），
# 第十一轮把同一个映射补进新链 ✓。
APPLY_CONSTRAINT_AND_REGENERATE = "apply_constraint_and_regenerate"
PLAN_CHANGE_GOALS = frozenset({"fill_to_count", "prioritize_within_tier"})
SCOPE_GOALS = frozenset({"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"})
# 目标里的范围种类 → `constraintUpdate` 的三个偏好束（与 legacy 的分组一致 ✓）。
_SCOPE_BUNDLES = {
    "school": "schoolPreferences",
    "college": "schoolPreferences",
    "university": "schoolPreferences",
    "major": "majorPreferences",
    "province": "regionPreferences",
    "city": "regionPreferences",
    "area": "regionPreferences",
    "region": "regionPreferences",
}


@dataclass(frozen=True)
class ConversationActionResult:
    action_status: str
    proposal_ref: str | None = None
    new_state_version: int | None = None
    actual_changes: list[dict[str, Any]] = field(default_factory=list)
    code: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "actionStatus": self.action_status,
            "proposalRef": self.proposal_ref,
            "newStateVersion": self.new_state_version,
            "actualChanges": self.actual_changes,
            "code": self.code,
            "message": self.message,
        }


def _data(response: Mapping[str, Any]) -> Mapping[str, Any]:
    value = response.get("data")
    return value if isinstance(value, Mapping) else {}


def _status(response: Mapping[str, Any]) -> str:
    value = str(response.get("status") or _data(response).get("status") or "").strip().lower()
    raw_code = response.get("code")
    code = str(raw_code).strip().lower() if raw_code is not None else ""
    # Java PendingConfirmation.resolve(confirm) first claims an active
    # snapshot and returns ``applying``.  That is an acknowledged in-progress
    # transition, not proof that the planning command has completed.
    if value in {"stale", "stale_state", "conflict", "version_conflict"}:
        return "stale_state"
    if value in {"expired", "binding_expired"}:
        return "expired"
    if code not in {"", "0", "200"}:
        return "failed"
    if value in {"applying", "in_progress", "processing"}:
        return "applying"
    if value in {"cancelled", "canceled"}:
        return "cancelled"
    if value in {"applied", "completed"}:
        return "applied"
    # A successful HTTP/business response alone does not prove execution.
    return "failed"


async def execute_conversation_action(
    *,
    tenant_id: str | int = 1,
    session_id: str,
    action: ConversationAction | Mapping[str, Any],
    snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    resolver: Callable[..., Awaitable[Mapping[str, Any]]] | None = None,
    executor: Callable[..., Awaitable[Mapping[str, Any]]] | None = None,
) -> ConversationActionResult:
    """执行已校验的确认/取消动作；其它动作只返回不可执行结果。

    confirm 是**两段式**（P2）：先 claim（`pending/resolve(confirm)`，拿到 `applying`
    ——那只是"执行权已认领"，**不是执行完成**），再 execute（`pending-command/execute`）。
    以前只做到 claim 就返回，于是"用户确认了"与"方案真的落库了"之间没有桥 ✗。
    """
    parsed_action = action if isinstance(action, ConversationAction) else ConversationAction.model_validate(action)
    parsed_snapshot = snapshot if isinstance(snapshot, ConversationTurnSnapshot) else ConversationTurnSnapshot.model_validate(snapshot)
    active = parsed_snapshot.active_proposal or {}
    proposal_ref = parsed_action.proposal_ref
    active_ref = active.get("proposalRef") or active.get("proposalId") or active.get("pendingId")
    if parsed_action.action_type not in {"confirm_proposal", "cancel_proposal"}:
        return ConversationActionResult("not_executable", proposal_ref, code="action_not_executable")
    if not proposal_ref or str(proposal_ref) != str(active_ref or ""):
        return ConversationActionResult("stale_state", proposal_ref, code="proposal_reference_mismatch")
    active_data = active.get("data") if isinstance(active.get("data"), Mapping) else {}
    source_version = next(
        (value for value in (
            active.get("sourceVersion", active.get("source_version")),
            active_data.get("sourceVersion", active_data.get("source_version")),
            active_data.get("sourceBackendVersion", active_data.get("source_backend_version")),
        ) if value is not None),
        None,
    )
    if parsed_action.expected_source_version is not None:
        if source_version is None:
            return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_missing")
        try:
            if int(parsed_action.expected_source_version) != int(source_version):
                return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_mismatch")
        except (TypeError, ValueError):
            return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_invalid")
    pending_id = str(active.get("pendingId") or proposal_ref)
    raw_revision = (
        active.get("revision")
        or active.get("pendingRevision")
        or active_data.get("revision")
        or active_data.get("pendingRevision")
    )
    try:
        expected_revision = int(raw_revision or 0)
    except (TypeError, ValueError):
        expected_revision = 0
    if expected_revision <= 0:
        return ConversationActionResult("stale_state", proposal_ref, code="pending_revision_missing")
    resolve_action = "confirm" if parsed_action.action_type == "confirm_proposal" else "cancel"
    claim_token = uuid.uuid4().hex if resolve_action == "confirm" else ""
    resolve_kwargs: dict[str, Any] = {
        "tenant_id": tenant_id,
        "pending_id": pending_id,
        "expected_revision": expected_revision,
        "action": resolve_action,
    }
    if claim_token:
        # Java requires a claim token for the active -> applying transition.
        # The token is deliberately generated per request and is never model
        # supplied or persisted by the Gateway. **同一个 token 必须复用到 execute**
        # ——新生成一个 Java 会拒（P2 任务书点名"最容易错的一点"）。
        resolve_kwargs["claim_token"] = claim_token
    response = await (resolver or resolve_pending_confirmation)(
        session_id,
        **resolve_kwargs,
    )
    status = _status(response)
    data = _data(response)
    if resolve_action == "confirm" and status == "applying":
        # 认领成功 ≠ 执行完成：把第二段（execute）走完，用户确认才算落地。
        return await _execute_claimed_command(
            tenant_id=tenant_id,
            session_id=session_id,
            proposal_ref=proposal_ref,
            active=active,
            active_data=active_data,
            pending_id=pending_id,
            claim_token=claim_token,
            source_version=source_version,
            executor=executor,
            resolver=resolver,
            expected_revision=_first_int(data.get("revision")),
        )
    # Pending revision is a separate CAS counter, not the conversation version.
    new_version = data.get("stateVersion")
    try:
        new_version = int(new_version) if new_version is not None else None
    except (TypeError, ValueError):
        new_version = None
    changes = data.get("actualChanges", data.get("changes", []))
    return ConversationActionResult(
        status, proposal_ref, new_version,
        list(changes) if isinstance(changes, list) else [],
        str(response.get("code")) if response.get("code") is not None else None,
        str(response.get("msg") or response.get("message")) if response.get("msg") or response.get("message") else None,
    )


def _first_int(*values: Any) -> int | None:
    for value in values:
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _proposal_apply_payload(
    active: Mapping[str, Any], active_data: Mapping[str, Any], *, proposal_ref: str, source_version: Any
) -> dict[str, Any]:
    """扁平 `FixProposalApplyReq`（**不照抄 legacy 的 `executionPayload` 包装层**）。

    legacy 往 pending 里写 `executionPayload` 那一层包装（`app/service.py:819-847`），
    而 Java 的 execute 要的是扁平形状——两条链对同一个键各写各的，新链路按生产者的来。
    pending 里已经带了 `proposalApply` 就原样用（生产者权威），没带才用最小必需字段兜底。
    """
    stored = active_data.get("proposalApply", active_data.get("proposal_apply"))
    if isinstance(stored, Mapping):
        return dict(stored)
    guard = _first_int(active.get("sourceVersion"), active_data.get("sourceVersion"), source_version, 0)
    payload = {
        "proposalId": str(active_data.get("proposalId") or proposal_ref),
        "proposalSource": str(active_data.get("proposalSource") or "user_goal"),
        "sourceVersionGuard": int(guard or 0),
        # 两个开关取 true：Java **要求**它们为 true（`PendingPlanningCommandBizService`：
        # "plan change apply requires regenerateOrderedPlan and rerunReview"），
        # 而 legacy 客户端的默认也一直是 true ✓。曾经按"保守取 false"写，真栈上直接被 40001 拒 ✗
        # （2026-09-24 实测）——"保守"在没有依据时就是猜，这里依据在生产者侧。
        "regenerateOrderedPlan": bool(active_data.get("regenerateOrderedPlan", True)),
        "rerunReview": bool(active_data.get("rerunReview", True)),
    }
    # `user_goal` 来源的提案还要求带上原始目标（"user_goal proposal requires userGoalRequest"）：
    # 由 prepare 落进 pending 的 dataValue（见 Java 侧），这里原样透传。
    user_goal_request = active_data.get("userGoalRequest", active_data.get("user_goal_request"))
    if isinstance(user_goal_request, Mapping):
        payload["userGoalRequest"] = dict(user_goal_request)
    return payload


def _constraint_update_from_goal(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    """把 user-goal 的范围翻译成 `constraintUpdate`（形状照 legacy 的 `_intent_constraint_payloads` ✓）。

    每个偏好束 = `{"positive": [...], "negative": [...]}` ✓（名字级 ✓，与 legacy 一致 ✓）。
    **范围种类不认识的，抛错拒绝执行** ✗：静默丢掉一条排除，用户看不见地在方案里留着一所
    他要去掉的学校——那比整轮失败糟得多 ✓。
    """
    bundles: dict[str, dict[str, list[str]]] = {}

    def add(scope: Any, *, negative: bool) -> None:
        if not isinstance(scope, Mapping):
            return
        name = str(scope.get("name") or scope.get("value") or "").strip()
        scope_type = str(scope.get("scopeType") or scope.get("scope_type") or "").strip().lower()
        bundle = _SCOPE_BUNDLES.get(scope_type)
        if not name or bundle is None:
            raise ValueError(f"unmappable_goal_scope: {scope_type or '(missing)'}")
        target = bundles.setdefault(bundle, {"positive": [], "negative": []})
        target["negative" if negative else "positive"].append(name)

    for scope in goal.get("targetScopes") or goal.get("target_scopes") or []:
        add(scope, negative=False)
    for scope in goal.get("negativeScopes") or goal.get("negative_scopes") or []:
        add(scope, negative=True)
    if not bundles:
        return None
    return {"intentMode": "constraint", **bundles}


def _tuition_bounds(goal: Mapping[str, Any]) -> tuple[int | None, int | None]:
    context = goal.get("context") if isinstance(goal.get("context"), Mapping) else {}
    return (
        _first_int(context.get("minTuitionPerYear"), context.get("min_tuition_per_year")),
        _first_int(context.get("maxTuitionPerYear"), context.get("max_tuition_per_year")),
    )


def _command_for_goal(
    active_data: Mapping[str, Any], *, proposal_apply: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """按目标类型选命令并装配附加输入（第十一轮：scope 类目标的映射 ✓）。

    - 计数/排序类（`fill_to_count` / `prioritize_within_tier`）→ `apply_plan_change_proposal`
      + 扁平 `proposalApply` ✓（原路径，行为不变 ✓）；
    - 范围类（`only_keep_scope` / `must_include_scope` / `exclude_scope` / `tuition_budget_scope`）
      → `apply_constraint_and_regenerate` + `constraintUpdate`（或学费上下限）✓✓；
    - 没有目标 / 类型不认识 → 保持原行为（由 Java 去判 ✓，错误码在那边更准 ✓）。
    """
    goal = active_data.get("userGoalRequest") or active_data.get("user_goal_request")
    if not isinstance(goal, Mapping):
        return APPLY_PLAN_CHANGE_PROPOSAL, {"proposal_apply": proposal_apply}
    goal_type = str(goal.get("goalType") or goal.get("goal_type") or "").strip()
    if goal_type not in SCOPE_GOALS:
        return APPLY_PLAN_CHANGE_PROPOSAL, {"proposal_apply": proposal_apply}
    constraint_update = _constraint_update_from_goal(goal)
    min_tuition, max_tuition = _tuition_bounds(goal)
    if constraint_update is None and min_tuition is None and max_tuition is None:
        raise ValueError("goal_scope_empty: scope goal carries nothing to apply")
    kwargs: dict[str, Any] = {
        # 约束变了就得重排 ✓（legacy 那条路同样如此 ✓）。
        "regenerate_ordered_plan": True,
    }
    if constraint_update is not None:
        kwargs["constraint_update"] = constraint_update
    if min_tuition is not None:
        kwargs["min_tuition_per_year"] = min_tuition
    if max_tuition is not None:
        kwargs["max_tuition_per_year"] = max_tuition
    return APPLY_CONSTRAINT_AND_REGENERATE, kwargs


async def _execute_claimed_command(
    *,
    tenant_id: str | int,
    session_id: str,
    proposal_ref: str | None,
    active: Mapping[str, Any],
    active_data: Mapping[str, Any],
    pending_id: str,
    claim_token: str,
    source_version: Any,
    executor: Callable[..., Awaitable[Mapping[str, Any]]] | None,
    resolver: Callable[..., Awaitable[Mapping[str, Any]]] | None = None,
    expected_revision: int | None = None,
) -> ConversationActionResult:
    """claim 之后的第二段：`pending-command/execute`。

    **operationId 是 Java 编译时产出的**（`ConversationProposalRequestService.PrepareOutcome`
    的 `pendingId + operationId`），网关只负责复用、不自己算——legacy 用 `uuid5` 自算那一套
    是旧链路的约定 ✗。pending 里没有它时**拒绝执行**：自铸一个会让 Java 的幂等键认不出
    这是同一次操作，"重复确认不双写"的依据就没了。
    """
    operation_id = str(active_data.get("operationId") or active.get("operationId") or "").strip()
    if not operation_id:
        return ConversationActionResult(
            "failed", proposal_ref, code="operation_id_missing",
            message="待确认内容里没有 Java 产出的 operationId，拒绝执行（不自铸幂等键）。",
        )
    expected_plan_version = _first_int(
        active.get("sourceVersion"), active_data.get("sourceVersion"), source_version
    )
    try:
        command_type, extra_kwargs = _command_for_goal(
            active_data,
            proposal_apply=_proposal_apply_payload(
                active, active_data, proposal_ref=str(proposal_ref or pending_id), source_version=source_version
            ),
        )
    except ValueError as exc:
        # 范围种类不认识、或范围目标里什么都没有：**拒绝执行** ✓
        # （静默丢掉一条排除，用户看不见地在方案里留着一所他要去掉的学校——那更糟 ✓）。
        code, _, detail = str(exc).partition(":")
        return ConversationActionResult(
            "failed", proposal_ref, code=code.strip(), message=detail.strip() or None
        )
    response = await (executor or execute_pending_planning_command)(
        tenant_id,
        session_id,
        operation_id=operation_id,
        pending_id=pending_id,
        claim_token=claim_token,
        expected_plan_version=int(expected_plan_version or 0),
        command_type=command_type,
        **extra_kwargs,
    )
    status = _status(response)
    data = _data(response)
    # **执行失败不许读成 completed**：`_status` 对拿不准的响应一律 `failed` ✓
    # （"HTTP 成功不等于执行成功"那条注释在它上面）。
    #
    # 链路的最后一段：把结果**回写**给 pending（`complete` / `fail`）。
    # 不回写的后果是 pending 永远停在 `applying` ✗——而 `applying` 正是"重复确认"的
    # 判定依据：第二次确认会走 claim 的"applying 且未过期 → 同状态返回"分支，
    # 看起来像没事，实际什么都没落地 ✗（2026-09-24 真栈实测）。
    # `complete`/`fail` 会校验 claim 归属 → **必须复用同一个 claim token** ✓。
    if status in {"applied", "failed"} and expected_revision and expected_revision > 0:
        report_action = "complete" if status == "applied" else "fail"
        try:
            await (resolver or resolve_pending_confirmation)(
                session_id,
                tenant_id=tenant_id,
                pending_id=pending_id,
                expected_revision=int(expected_revision),
                action=report_action,
                claim_token=claim_token,
                result_code=str(response.get("code") or ""),
            )
        except Exception as exc:  # noqa: BLE001 —— 回写失败不改写执行结果，但必须留痕
            logger.warning("pending outcome report failed (%s, pending=%s): %s", report_action, pending_id, exc)
    elif status == "applying":
        logger.warning(
            "pending command still applying after execute (pending=%s); not reporting complete/fail",
            pending_id,
        )
    changes = data.get("actualChanges", data.get("changes", []))
    return ConversationActionResult(
        status, proposal_ref, _first_int(data.get("stateVersion")),
        list(changes) if isinstance(changes, list) else [],
        str(response.get("code")) if response.get("code") is not None else None,
        str(response.get("msg") or response.get("message")) if response.get("msg") or response.get("message") else None,
    )
