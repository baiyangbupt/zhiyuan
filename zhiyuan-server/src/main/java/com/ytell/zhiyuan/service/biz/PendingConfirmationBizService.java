package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationResolveReq;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.inner.PendingReconcileRes;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Date;

@Service
public class PendingConfirmationBizService {

    public static final int CAS_CONFLICT_CODE = 40901;
    public static final int PENDING_MISMATCH_CODE = 40902;
    public static final int INVALID_PENDING_REQUEST_CODE = 40001;
    private static final long CLAIM_LEASE_MILLIS = 5L * 60L * 1000L;

    private static final String KIND_CAREER_UPDATE = "career_update";
    private static final String ACTION_FAMILY_UPDATE_CAREER = "update_career_types";
    private static final String RECONCILE_RESOLVED_ACTION = "reconcile";

    @Autowired
    private PendingConfirmationSharedService pendingConfirmationSharedService;

    @Autowired
    private PlanningPendingCommandSharedService pendingCommandSharedService;

    /** 命令 running 且租约过期后，再等多久才判结果未知（默认 10 分钟）。 */
    @Value("${planning.pending.reconcile.operation-stale-ms:600000}")
    private long operationStaleMillis = 600000L;

    /** 无 operation 行时可判“未送出”的证明窗口（默认 24 小时，远小于 retention 30 天）。 */
    @Value("${planning.pending.reconcile.no-operation-proof-window-ms:86400000}")
    private long noOperationProofWindowMillis = 86400000L;

    public PendingConfirmationRes getCurrent(Long tenantId, Long chatSessionId) {
        requirePositive(tenantId, "tenantId");
        requirePositive(chatSessionId, "chatSessionId");
        return toResponse(pendingConfirmationSharedService.getCurrent(tenantId, chatSessionId), false);
    }

    /** J1 旅程只读：只返回 active/applying（无则 null），不动 getCurrent 的写路径语义。 */
    public PendingConfirmationRes getActiveOrApplying(Long tenantId, Long chatSessionId) {
        requirePositive(tenantId, "tenantId");
        requirePositive(chatSessionId, "chatSessionId");
        return toResponse(pendingConfirmationSharedService.getActiveOrApplying(tenantId, chatSessionId), false);
    }

    @Transactional(rollbackFor = Exception.class)
    public PendingConfirmationRes upsert(Long tenantId, PendingConfirmationUpsertReq req) {
        validateUpsert(tenantId, req);
        long expectedRevision = req.getExpectedRevision() == null ? 0L : req.getExpectedRevision();
        PendingConfirmationEntity current = pendingConfirmationSharedService.getCurrent(tenantId, req.getChatSessionId());
        String serialized = JSONObject.toJSONString(req.getDataValue());
        if (current == null) {
            if (expectedRevision != 0L) {
                throw conflict("pending revision conflict: current=0 expected=" + expectedRevision);
            }
            PendingConfirmationEntity created = buildActiveEntity(tenantId, req, serialized, 1L);
            try {
                pendingConfirmationSharedService.save(created);
            } catch (DuplicateKeyException ex) {
                throw conflict("pending was created concurrently");
            }
            return toResponse(created, true);
        }
        if (isSameActiveSnapshot(current, req, serialized)) {
            return toResponse(current, false);
        }
        // J1：applying 的最终保护在 Java 写入口。快照检查只能提前反馈；另一请求
        // 可以在取快照后 claim，而发展方向路径会重新读取最新 revision——若这里
        // 只比 revision，CAS 会把 applying 行覆盖成新的 active。
        if ("applying".equals(current.getStatus())) {
            throw new BusinessException(409, "pending_applying");
        }
        if (current.getRevision() == null || current.getRevision() != expectedRevision) {
            throw conflict("pending revision conflict: current=" + current.getRevision() + " expected=" + expectedRevision);
        }
        PendingConfirmationEntity next = buildActiveEntity(
                tenantId, req, serialized, current.getRevision() + 1L);
        next.setId(current.getId());
        boolean updated = pendingConfirmationSharedService.compareAndSet(
                next, expectedRevision, current.getPendingId(), current.getStatus());
        if (!updated) {
            throw conflict("pending changed concurrently");
        }
        return toResponse(next, true);
    }

    @Transactional(rollbackFor = Exception.class)
    public PendingConfirmationRes resolve(Long tenantId, PendingConfirmationResolveReq req) {
        validateResolve(tenantId, req);
        PendingConfirmationEntity current = pendingConfirmationSharedService.getCurrent(tenantId, req.getChatSessionId());
        if (current == null || !req.getPendingId().equals(current.getPendingId())) {
            throw new BusinessException(PENDING_MISMATCH_CODE, "pending snapshot mismatch");
        }
        String action = normalize(req.getAction());
        String status = normalize(current.getStatus());
        validateClaimOwnership(action, current, req);
        Transition transition = resolveTransition(action, status, current, req);
        if (transition.idempotent) {
            return toResponse(current, false);
        }
        long expectedRevision = req.getExpectedRevision() == null ? -1L : req.getExpectedRevision();
        if (current.getRevision() == null || current.getRevision() != expectedRevision) {
            throw conflict("pending revision conflict: current=" + current.getRevision() + " expected=" + expectedRevision);
        }
        PendingConfirmationEntity next = copyForTransition(current, req, transition.targetStatus);
        boolean updated = pendingConfirmationSharedService.compareAndSet(
                next, expectedRevision, current.getPendingId(), transition.sourceStatus);
        if (!updated) {
            throw conflict("pending changed concurrently");
        }
        return toResponse(next, true);
    }

    private Transition resolveTransition(String action, String status,
                                         PendingConfirmationEntity current,
                                         PendingConfirmationResolveReq req) {
        if ("confirm".equals(action)) {
            if ("active".equals(status)) return new Transition("active", "applying", false);
            if ("applying".equals(status)) {
                if (req.getClaimToken().equals(current.getClaimToken()) || !isClaimExpired(current)) {
                    return new Transition(status, status, true);
                }
                return new Transition("applying", "applying", false);
            }
            if ("applied".equals(status)) return new Transition(status, status, true);
        } else if ("cancel".equals(action)) {
            if ("active".equals(status)) return new Transition("active", "cancelled", false);
            if ("cancelled".equals(status)) return new Transition(status, status, true);
        } else if ("complete".equals(action)) {
            if ("applying".equals(status)) return new Transition("applying", "applied", false);
            if ("applied".equals(status)) return new Transition(status, status, true);
        } else if ("fail".equals(action)) {
            if ("applying".equals(status)) return new Transition("applying", "expired", false);
            if ("expired".equals(status)) return new Transition(status, status, true);
        } else if ("expire".equals(action)) {
            if ("active".equals(status) || "applying".equals(status)) return new Transition(status, "expired", false);
            if ("expired".equals(status)) return new Transition(status, status, true);
        }
        throw new BusinessException(PENDING_MISMATCH_CODE,
                "pending transition mismatch: action=" + action + " status=" + status);
    }

    private void validateClaimOwnership(String action, PendingConfirmationEntity current,
                                        PendingConfirmationResolveReq req) {
        if ("confirm".equals(action)) {
            requireText(req.getClaimToken(), "claimToken");
            return;
        }
        if (("complete".equals(action) || "fail".equals(action))
                && !safeEquals(current.getClaimToken(), req.getClaimToken())) {
            throw new BusinessException(PENDING_MISMATCH_CODE, "pending claim ownership mismatch");
        }
    }

    private boolean isClaimExpired(PendingConfirmationEntity current) {
        return current.getClaimExpiresAt() == null
                || current.getClaimExpiresAt().getTime() <= System.currentTimeMillis();
    }

    private boolean safeEquals(String left, String right) {
        return left != null && left.equals(right);
    }

    private PendingConfirmationEntity copyForTransition(PendingConfirmationEntity current,
                                                        PendingConfirmationResolveReq req,
                                                        String targetStatus) {
        PendingConfirmationEntity next = new PendingConfirmationEntity();
        next.setId(current.getId());
        next.setTenantId(current.getTenantId());
        next.setChatSessionId(current.getChatSessionId());
        next.setPendingId(current.getPendingId());
        next.setRevision(current.getRevision() + 1L);
        next.setKind(current.getKind());
        next.setActionFamily(current.getActionFamily());
        next.setStatus(targetStatus);
        if ("applying".equals(targetStatus)) {
            next.setClaimToken(req.getClaimToken().trim());
            next.setClaimExpiresAt(new Date(System.currentTimeMillis() + CLAIM_LEASE_MILLIS));
        } else {
            next.setClaimToken(current.getClaimToken());
            next.setClaimExpiresAt(null);
        }
        Map<String, Object> payload = req.getDataValue();
        if (payload == null || payload.isEmpty()) {
            payload = parsePayload(current.getDataValue());
        }
        removeTransportMetadata(payload);
        payload.put("status", targetStatus);
        payload.put("revision", next.getRevision());
        next.setDataValue(JSONObject.toJSONString(payload));
        next.setResultCode(req.getResultCode());
        next.setResolvedAction(normalize(req.getAction()));
        return next;
    }

    private PendingConfirmationEntity buildActiveEntity(Long tenantId, PendingConfirmationUpsertReq req,
                                                        String serialized, Long revision) {
        PendingConfirmationEntity entity = new PendingConfirmationEntity();
        entity.setTenantId(tenantId);
        entity.setChatSessionId(req.getChatSessionId());
        entity.setPendingId(req.getPendingId().trim());
        entity.setRevision(revision);
        entity.setKind(req.getKind().trim());
        entity.setActionFamily(req.getActionFamily().trim());
        entity.setStatus("active");
        entity.setClaimToken(null);
        entity.setClaimExpiresAt(null);
        Map<String, Object> payload = parsePayload(serialized);
        removeTransportMetadata(payload);
        payload.put("status", "active");
        payload.put("revision", revision);
        entity.setDataValue(JSONObject.toJSONString(payload));
        entity.setResultCode(null);
        entity.setResolvedAction(null);
        return entity;
    }

    private boolean isSameActiveSnapshot(PendingConfirmationEntity current,
                                         PendingConfirmationUpsertReq req, String serialized) {
        if (!"active".equals(current.getStatus())
                || !req.getPendingId().equals(current.getPendingId())
                || !req.getKind().equals(current.getKind())
                || !req.getActionFamily().equals(current.getActionFamily())) {
            return false;
        }
        Map<String, Object> existing = parsePayload(current.getDataValue());
        existing.remove("revision");
        Map<String, Object> incoming = parsePayload(serialized);
        incoming.remove("revision");
        incoming.put("status", "active");
        return existing.equals(incoming);
    }

    /**
     * J1：applying 的受信对账。只读台账 + CAS 迁移状态；绝不调用 execute/重发命令。
     *
     * <p>为什么需要它：claim 后 Agent 重启、执行成功但 complete 回写失败、租约过期，
     * 都会让 pending 永远停在 applying。超时不等于未执行，所以这里先查 operation
     * 台账，再决定 applied / expired / still_applying。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public PendingReconcileRes reconcile(Long tenantId, Long chatSessionId) {
        requirePositive(tenantId, "tenantId");
        requirePositive(chatSessionId, "chatSessionId");
        PendingConfirmationEntity current =
                pendingConfirmationSharedService.lockCurrent(tenantId, chatSessionId);
        if (current == null) {
            PendingReconcileRes response = reconcileResponse(null);
            response.setOutcome(PendingReconcileRes.OUTCOME_NO_PENDING);
            return response;
        }
        PendingReconcileRes response = reconcileResponse(current);
        if (!"applying".equals(current.getStatus())) {
            response.setOutcome(PendingReconcileRes.OUTCOME_NOT_APPLYING);
            return response;
        }
        if (current.getRevision() == null) {
            return stillApplying(response, "applying",
                    "pending revision is missing; cannot reconcile");
        }

        boolean claimExpired = isClaimExpired(current);
        if (isGatewayExecutedKind(current)) {
            // 发展方向由网关执行，不写 Java command 台账；无论有没有行都不能判 applied，
            // 也不能判“没送出”。只能等待或结果未知。
            return claimExpired
                    ? expire(response, current,
                    PendingReconcileRes.RESULT_OPERATION_UNKNOWN,
                    "该变更由网关执行，无法用 operation 台账证明结果，请刷新方案核对版本。")
                    : stillApplying(response, "unknown", null);
        }

        String operationId = operationId(current);
        PlanningPendingCommandEntity command = operationId == null
                ? null : pendingCommandSharedService.getByOperationId(operationId);
        String operationStatus = command == null ? "missing" : command.getStatus();

        if (command != null && !commandMatches(current, command)) {
            return expire(response, current,
                    PendingReconcileRes.RESULT_OPERATION_UNKNOWN,
                    "operation 台账与当前 pending 不匹配，结果未知，请刷新方案核对版本。");
        }

        if (command == null) {
            if (!claimExpired) {
                return stillApplying(response, operationStatus, null);
            }
            if (withinNoOperationProofWindow(current)) {
                return expire(response, current,
                        PendingReconcileRes.RESULT_NO_OPERATION_SUBMITTED,
                        "没有找到 operation 记录，且仍在可证明窗口内：命令未送出。");
            }
            return expire(response, current,
                    PendingReconcileRes.RESULT_OPERATION_UNKNOWN,
                    "operation 台账可能已清理，无法证明命令是否送出，请刷新方案核对版本。");
        }

        if ("succeeded".equals(command.getStatus())) {
            PendingReconcileRes applied = reconcileResponse(current);
            applied.setOutcome(PendingReconcileRes.OUTCOME_APPLIED);
            applied.setOperationStatus("succeeded");
            applied.setResultPlanVersion(resultPlanVersion(command));
            applied.setReceiptAvailable(!Strings.isNullOrEmpty(command.getResultJson()));
            boolean updated = pendingConfirmationSharedService.compareAndSet(
                    copyForReconcile(current, "applied", null),
                    current.getRevision(), current.getPendingId(), "applying");
            if (!updated) {
                return latestAfterReconcile(tenantId, chatSessionId);
            }
            applied.setPendingStatus("applied");
            applied.setRevision(current.getRevision() + 1L);
            return applied;
        }

        if ("running".equals(command.getStatus())) {
            if (!claimExpired) {
                return stillApplying(response, operationStatus, null);
            }
            if (commandStale(command)) {
                return expire(response, current,
                        PendingReconcileRes.RESULT_OPERATION_UNKNOWN,
                        "命令仍在运行且已超过宽限，结果未知；请刷新方案核对版本，不自动重试。");
            }
            return stillApplying(response, operationStatus, null);
        }

        return expire(response, current,
                PendingReconcileRes.RESULT_OPERATION_UNKNOWN,
                "未知的 operation 状态，请刷新方案核对版本。");
    }

    private PendingReconcileRes stillApplying(PendingReconcileRes response, String operationStatus,
                                              String message) {
        response.setOutcome(PendingReconcileRes.OUTCOME_STILL_APPLYING);
        response.setOperationStatus(operationStatus);
        response.setMessage(message);
        return response;
    }

    private PendingReconcileRes expire(PendingReconcileRes response, PendingConfirmationEntity current,
                                       String resultCode, String message) {
        PendingConfirmationEntity next = copyForReconcile(current, "expired", resultCode);
        boolean updated = pendingConfirmationSharedService.compareAndSet(
                next, current.getRevision(), current.getPendingId(), "applying");
        if (!updated) {
            PendingReconcileRes latest = latestAfterReconcile(
                    current.getTenantId(), current.getChatSessionId());
            if (latest.getMessage() == null) {
                latest.setMessage(message);
            }
            return latest;
        }
        response.setOutcome(PendingReconcileRes.OUTCOME_EXPIRED);
        response.setPendingStatus("expired");
        response.setResultCode(resultCode);
        response.setRevision(current.getRevision() + 1L);
        response.setMessage(message);
        return response;
    }

    private PendingReconcileRes latestAfterReconcile(Long tenantId, Long chatSessionId) {
        PendingConfirmationEntity latest =
                pendingConfirmationSharedService.getCurrent(tenantId, chatSessionId);
        PendingReconcileRes response = reconcileResponse(latest);
        response.setOutcome(latest == null
                ? PendingReconcileRes.OUTCOME_NO_PENDING
                : PendingReconcileRes.OUTCOME_NOT_APPLYING);
        return response;
    }

    private PendingReconcileRes reconcileResponse(PendingConfirmationEntity entity) {
        PendingReconcileRes response = new PendingReconcileRes();
        if (entity == null) {
            return response;
        }
        response.setPendingId(entity.getPendingId());
        response.setRevision(entity.getRevision());
        response.setPendingStatus(entity.getStatus());
        response.setClaimExpiresAt(entity.getClaimExpiresAt());
        return response;
    }

    private PendingConfirmationEntity copyForReconcile(PendingConfirmationEntity current,
                                                       String targetStatus, String resultCode) {
        PendingConfirmationEntity next = new PendingConfirmationEntity();
        next.setId(current.getId());
        next.setTenantId(current.getTenantId());
        next.setChatSessionId(current.getChatSessionId());
        next.setPendingId(current.getPendingId());
        next.setRevision(current.getRevision() + 1L);
        next.setKind(current.getKind());
        next.setActionFamily(current.getActionFamily());
        next.setStatus(targetStatus);
        next.setClaimToken(current.getClaimToken());
        next.setClaimExpiresAt(null);
        next.setDataValue(current.getDataValue());
        next.setResultCode(resultCode);
        next.setResolvedAction(RECONCILE_RESOLVED_ACTION);
        return next;
    }

    private String operationId(PendingConfirmationEntity current) {
        Map<String, Object> data = parsePayload(current.getDataValue());
        Object value = data.get("operationId");
        return value == null ? null : String.valueOf(value).trim();
    }

    private boolean isGatewayExecutedKind(PendingConfirmationEntity current) {
        return KIND_CAREER_UPDATE.equalsIgnoreCase(current.getKind())
                || ACTION_FAMILY_UPDATE_CAREER.equalsIgnoreCase(current.getActionFamily());
    }

    private boolean commandMatches(PendingConfirmationEntity pending,
                                   PlanningPendingCommandEntity command) {
        return pending.getPendingId() != null
                && pending.getPendingId().equals(command.getPendingId())
                && pending.getTenantId() != null
                && pending.getTenantId().equals(command.getTenantId())
                && pending.getChatSessionId() != null
                && pending.getChatSessionId().equals(command.getChatSessionId());
    }

    private boolean withinNoOperationProofWindow(PendingConfirmationEntity current) {
        if (current.getCreateTime() == null) {
            return false;
        }
        return System.currentTimeMillis() - current.getCreateTime().getTime()
                <= noOperationProofWindowMillis;
    }

    private boolean commandStale(PlanningPendingCommandEntity command) {
        if (command.getUpdateTime() == null) {
            return true;
        }
        return System.currentTimeMillis() - command.getUpdateTime().getTime()
                > operationStaleMillis;
    }

    private Integer resultPlanVersion(PlanningPendingCommandEntity command) {
        if (Strings.isNullOrEmpty(command.getResultJson())) {
            return null;
        }
        try {
            PendingPlanningCommandRes result = JSONObject.parseObject(
                    command.getResultJson(), PendingPlanningCommandRes.class);
            return result == null ? null : result.getResultPlanVersion();
        } catch (Exception ex) {
            return null;
        }
    }

    private PendingConfirmationRes toResponse(PendingConfirmationEntity entity, boolean transitionApplied) {
        if (entity == null) return null;
        PendingConfirmationRes response = new PendingConfirmationRes();
        response.setChatSessionId(entity.getChatSessionId());
        response.setPendingId(entity.getPendingId());
        response.setRevision(entity.getRevision());
        response.setKind(entity.getKind());
        response.setActionFamily(entity.getActionFamily());
        response.setStatus(entity.getStatus());
        response.setClaimToken(entity.getClaimToken());
        response.setClaimExpiresAt(entity.getClaimExpiresAt());
        response.setResultCode(entity.getResultCode());
        response.setResolvedAction(entity.getResolvedAction());
        response.setDataValue(parsePayload(entity.getDataValue()));
        response.setTransitionApplied(transitionApplied);
        return response;
    }

    private Map<String, Object> parsePayload(String json) {
        if (Strings.isNullOrEmpty(json)) return new java.util.LinkedHashMap<String, Object>();
        Map<String, Object> parsed = JSONObject.parseObject(json, Map.class);
        return parsed == null ? new java.util.LinkedHashMap<String, Object>() : parsed;
    }

    private void removeTransportMetadata(Map<String, Object> payload) {
        payload.remove("_pendingRevision");
        payload.remove("_extraDataVersion");
        payload.remove("dataVersion");
        payload.remove("_pendingClaimToken");
        payload.remove("_pendingClaimExpiresAt");
    }

    private void validateUpsert(Long tenantId, PendingConfirmationUpsertReq req) {
        requirePositive(tenantId, "tenantId");
        if (req == null) invalid("request is required");
        requirePositive(req.getChatSessionId(), "chatSessionId");
        requireText(req.getPendingId(), "pendingId");
        requireText(req.getKind(), "kind");
        requireText(req.getActionFamily(), "actionFamily");
        if (req.getExpectedRevision() != null && req.getExpectedRevision() < 0L) invalid("expectedRevision must be >= 0");
        if (req.getDataValue() == null || req.getDataValue().isEmpty()) invalid("dataValue is required");
    }

    private void validateResolve(Long tenantId, PendingConfirmationResolveReq req) {
        requirePositive(tenantId, "tenantId");
        if (req == null) invalid("request is required");
        requirePositive(req.getChatSessionId(), "chatSessionId");
        requireText(req.getPendingId(), "pendingId");
        requireText(req.getAction(), "action");
        if (req.getExpectedRevision() == null || req.getExpectedRevision() <= 0L) {
            invalid("expectedRevision must be > 0");
        }
    }

    private void requirePositive(Long value, String field) {
        if (value == null || value <= 0L) invalid(field + " must be > 0");
    }

    private void requireText(String value, String field) {
        if (Strings.isNullOrEmpty(value) || Strings.isNullOrEmpty(value.trim())) invalid(field + " is required");
    }

    private void invalid(String message) {
        throw new BusinessException(INVALID_PENDING_REQUEST_CODE, message);
    }

    private BusinessException conflict(String message) {
        return new BusinessException(CAS_CONFLICT_CODE, message);
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase();
    }

    private static class Transition {
        private final String sourceStatus;
        private final String targetStatus;
        private final boolean idempotent;

        private Transition(String sourceStatus, String targetStatus, boolean idempotent) {
            this.sourceStatus = sourceStatus;
            this.targetStatus = targetStatus;
            this.idempotent = idempotent;
        }
    }
}
