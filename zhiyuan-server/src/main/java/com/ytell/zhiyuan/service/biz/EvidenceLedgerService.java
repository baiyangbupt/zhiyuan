package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.common.util.EvidenceParamsDigest;
import com.ytell.zhiyuan.common.util.Ulid;
import com.ytell.zhiyuan.mapper.EvidenceLedgerMapper;
import com.ytell.zhiyuan.mapper.EvidenceSourceVersionMapper;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceScope;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceSignRequest;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyItemDTO;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyReq;
import com.ytell.zhiyuan.model.dto.evidence.EvidenceVerifyRes;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.entity.biz.EvidenceLedgerEntity;
import com.ytell.zhiyuan.model.entity.biz.EvidenceSourceVersionEntity;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * 权威证据台账：签发与核验。
 *
 * <p>权威性来自签发者，不来自标签。证据 ID 由 Java 生成且不可预测，核验必须回到 Java。
 * 不做密码学签名——权威性靠「回 Java 查得到」建立。</p>
 */
@Slf4j
@Service
public class EvidenceLedgerService {

    /** 权威级别标签，只允许由本服务写入。 */
    public static final String SOURCE_LEVEL_AUTHORITATIVE = "authoritative";

    /** 取数来源标识，失效判定按来源分别比对上游版本。 */
    public static final String SOURCE_GAOTU_SCHOOL_MAJOR_SCORE_LINE = "gaotu.schoolMajorScoreLine";
    public static final String SOURCE_GAOTU_BATCH_LIST = "gaotu.batchList";
    public static final String SOURCE_GAOTU_PROGRAM_BY_LIMIT_NUM = "gaotu.programByLimitNum";

    public static final String STATUS_VALID = "valid";
    public static final String STATUS_STALE = "stale";
    public static final String STATUS_EXPIRED = "expired";
    public static final String STATUS_UNKNOWN = "unknown";

    private static final String EVIDENCE_ID_PREFIX = "ev_";

    @Autowired
    private EvidenceLedgerMapper evidenceLedgerMapper;

    @Autowired
    private EvidenceSourceVersionMapper evidenceSourceVersionMapper;

    /**
     * 证据保留窗口。志愿填报是一个季度内完成的业务，30 天覆盖单次咨询周期。
     * 该值需要产品侧确认，见设计文档 4.2。
     */
    @Value("${evidence.ledger.ttl-days:30}")
    private int ttlDays = 30;

    /**
     * 签发证据并写入台账。
     *
     * <p>必须与取数在同一次读取内调用，否则 dataVersion 和 observedAt 就是编的。</p>
     *
     * @return 签发结果；来源、上游版本或归属范围缺失时返回 {@code null}（不签发）
     */
    public ConversationEvidenceDTO sign(EvidenceSignRequest request) {
        if (request == null || isBlank(request.getSourceSystem())) {
            return null;
        }
        if (isBlank(request.getDataVersion())) {
            // 拿不到上游版本就不签发，让调用方走已有的 dataVersion_missing 降级路径
            return null;
        }
        EvidenceScope scope = request.getScope();
        if (scope == null || !scope.isComplete()) {
            return null;
        }
        Date observedAt = new Date();
        Date expiresAt = new Date(observedAt.getTime() + TimeUnit.DAYS.toMillis(Math.max(1, ttlDays)));
        String paramsDigest = EvidenceParamsDigest.digest(request.getParams());
        String evidenceId = EVIDENCE_ID_PREFIX + Ulid.next();

        EvidenceLedgerEntity entity = new EvidenceLedgerEntity();
        entity.setEvidenceId(evidenceId);
        entity.setTenantId(scope.getTenantId());
        entity.setChatSessionId(scope.getChatSessionId());
        entity.setThreadId(trimToNull(scope.getThreadId()));
        entity.setSourceSystem(request.getSourceSystem());
        entity.setParamsDigest(paramsDigest);
        entity.setDataVersion(request.getDataVersion());
        entity.setAlgorithmVersion(trimToNull(request.getAlgorithmVersion()));
        entity.setAdmissionMode(trimToNull(request.getAdmissionMode()));
        entity.setAdmissionUnitId(trimToNull(request.getAdmissionUnitId()));
        entity.setGroupCode(trimToNull(request.getGroupCode()));
        entity.setStateVersion(request.getStateVersion());
        entity.setScopeJson(JSON.toJSONString(scopePayload(scope)));
        entity.setLimitationsJson(JSON.toJSONString(
                request.getLimitations() == null ? new ArrayList<String>() : request.getLimitations()));
        entity.setObservedAt(observedAt);
        entity.setExpiresAt(expiresAt);

        try {
            evidenceLedgerMapper.insert(entity);
            evidenceSourceVersionMapper.upsert(request.getSourceSystem(), request.getDataVersion(), observedAt);
        } catch (RuntimeException e) {
            // 台账写不进去就不签发：调用方拿不到证据，必须按"证据不可用"降级。
            // 这里不抛出，避免把一次取证失败放大成取数失败。
            log.error("证据签发失败, sourceSystem={}, evidenceId={}", request.getSourceSystem(), evidenceId, e);
            return null;
        }
        log.info("证据已签发, evidenceId={}, sourceSystem={}, chatSessionId={}, paramsDigest={}, dataVersion={}",
                evidenceId, request.getSourceSystem(), scope.getChatSessionId(), paramsDigest, request.getDataVersion());
        return toEvidenceDTO(entity);
    }

    /**
     * 批量核验。一个回合一次调用——逐条调用会把 Java 往返次数放大到与事实条数同阶。
     *
     * <p>四态：{@code valid} 记录存在 + 未过期 + 上游当前版本一致；
     * {@code stale} 版本不一致（当时正确，现已失效，必须重查）；
     * {@code expired} 已过 expiresAt（新鲜度未知，必须重查）；
     * {@code unknown} 查不到记录（从未成立）。</p>
     *
     * <p>范围不匹配（别的租户/会话/线程）一律返回 {@code unknown}，不向调用方透露其他会话的台账。</p>
     */
    public EvidenceVerifyRes verify(EvidenceVerifyReq request) {
        EvidenceVerifyRes response = new EvidenceVerifyRes();
        if (request == null || request.getEvidenceIds() == null) {
            return response;
        }
        boolean scoped = request.getTenantId() != null && request.getChatSessionId() != null;
        Date now = new Date();
        Map<String, String> currentVersions = new LinkedHashMap<String, String>();
        for (String evidenceId : request.getEvidenceIds()) {
            if (isBlank(evidenceId)) {
                response.getResults().put(evidenceId == null ? "" : evidenceId, EvidenceVerifyItemDTO.of(STATUS_UNKNOWN));
                continue;
            }
            if (!scoped) {
                response.getResults().put(evidenceId, EvidenceVerifyItemDTO.of(STATUS_UNKNOWN));
                continue;
            }
            response.getResults().put(evidenceId, verifyOne(evidenceId, request, now, currentVersions));
        }
        return response;
    }

    private EvidenceVerifyItemDTO verifyOne(String evidenceId, EvidenceVerifyReq request, Date now,
                                            Map<String, String> currentVersions) {
        EvidenceLedgerEntity entity = evidenceLedgerMapper.selectById(evidenceId);
        if (entity == null) {
            return EvidenceVerifyItemDTO.of(STATUS_UNKNOWN);
        }
        if (!entity.getTenantId().equals(request.getTenantId())
                || !entity.getChatSessionId().equals(request.getChatSessionId())) {
            return EvidenceVerifyItemDTO.of(STATUS_UNKNOWN);
        }
        if (!isBlank(entity.getThreadId()) && !isBlank(request.getThreadId())
                && !entity.getThreadId().equals(request.getThreadId())) {
            return EvidenceVerifyItemDTO.of(STATUS_UNKNOWN);
        }
        EvidenceVerifyItemDTO item = new EvidenceVerifyItemDTO();
        item.setSourceSystem(entity.getSourceSystem());
        item.setParamsDigest(entity.getParamsDigest());
        item.setDataVersion(entity.getDataVersion());
        item.setObservedAt(toIso(entity.getObservedAt()));
        item.setExpiresAt(toIso(entity.getExpiresAt()));
        if (entity.getExpiresAt() != null && entity.getExpiresAt().before(now)) {
            item.setStatus(STATUS_EXPIRED);
            return item;
        }
        String current = currentVersions.get(entity.getSourceSystem());
        if (current == null) {
            current = currentDataVersion(entity.getSourceSystem());
            currentVersions.put(entity.getSourceSystem(), current);
        }
        item.setStatus(current.equals(entity.getDataVersion()) ? STATUS_VALID : STATUS_STALE);
        return item;
    }

    private ConversationEvidenceDTO toEvidenceDTO(EvidenceLedgerEntity entity) {
        ConversationEvidenceDTO evidence = new ConversationEvidenceDTO();
        evidence.setEvidenceId(entity.getEvidenceId());
        evidence.setSourceLevel(SOURCE_LEVEL_AUTHORITATIVE);
        evidence.setSourceSystem(entity.getSourceSystem());
        evidence.setParamsDigest(entity.getParamsDigest());
        evidence.setDataVersion(entity.getDataVersion());
        evidence.setAlgorithmVersion(entity.getAlgorithmVersion());
        evidence.setAdmissionMode(entity.getAdmissionMode());
        evidence.setAdmissionUnitId(entity.getAdmissionUnitId());
        evidence.setGroupCode(entity.getGroupCode());
        evidence.setStateVersion(entity.getStateVersion());
        Map<String, Object> scope = new LinkedHashMap<String, Object>();
        scope.put("tenantId", entity.getTenantId());
        scope.put("chatSessionId", entity.getChatSessionId());
        scope.put("threadId", entity.getThreadId());
        evidence.setScope(scope);
        evidence.setObservedAt(toIso(entity.getObservedAt()));
        evidence.setExpiresAt(toIso(entity.getExpiresAt()));
        if (!isBlank(entity.getLimitationsJson())) {
            evidence.setLimitations(JSON.parseArray(entity.getLimitationsJson(), String.class));
        }
        return evidence;
    }

    /**
     * 该来源最近一次观察到的上游数据版本。没有观察记录时返回空串，
     * 于是台账记录永远比不中，核验落到 {@code stale} 而不是 {@code valid}。
     */
    private String currentDataVersion(String sourceSystem) {
        EvidenceSourceVersionEntity current = evidenceSourceVersionMapper.selectById(sourceSystem);
        if (current == null || isBlank(current.getDataVersion())) {
            return "";
        }
        return current.getDataVersion();
    }

    private static Map<String, Object> scopePayload(EvidenceScope scope) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("tenantId", scope.getTenantId());
        payload.put("chatSessionId", scope.getChatSessionId());
        payload.put("threadId", trimToNull(scope.getThreadId()));
        return payload;
    }

    private static String toIso(Date date) {
        if (date == null) {
            return null;
        }
        return DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(date.toInstant().atZone(ZoneId.systemDefault()));
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
