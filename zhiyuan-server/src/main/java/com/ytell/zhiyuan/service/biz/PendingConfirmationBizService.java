package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationResolveReq;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import org.springframework.beans.factory.annotation.Autowired;
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

    @Autowired
    private PendingConfirmationSharedService pendingConfirmationSharedService;

    public PendingConfirmationRes getCurrent(Long tenantId, Long chatSessionId) {
        requirePositive(tenantId, "tenantId");
        requirePositive(chatSessionId, "chatSessionId");
        return toResponse(pendingConfirmationSharedService.getCurrent(tenantId, chatSessionId), false);
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
