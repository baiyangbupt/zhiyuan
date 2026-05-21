package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.IntegrationSessionRequestMapper;
import com.ytell.zhiyuan.model.dto.integration.ExternalGenerationOptionsDTO;
import com.ytell.zhiyuan.model.dto.integration.ExternalReturnOptionsDTO;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeRes;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.entity.biz.IntegrationSessionRequest;
import com.ytell.zhiyuan.model.vo.ChatSessionVo;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Date;
import java.util.Map;

@Slf4j
@Service
public class IntegrationSessionService {

    private static final String STATUS_PROCESSING = "PROCESSING";
    private static final String STATUS_SUCCESS = "SUCCESS";
    private static final String STATUS_FAILED = "FAILED";

    @Autowired
    private IntegrationSessionRequestMapper integrationSessionRequestMapper;
    @Autowired
    private ChatSessionBizService chatSessionBizService;
    @Autowired
    private PlanningStateService planningStateService;

    public ExternalSessionInitializeRes initializeSession(Long tenantId, ExternalSessionInitializeReq req) {
        validateRequest(req);
        UserBaseData userBaseData = UserInfoThreadLocalUtil.get();
        if (userBaseData == null || userBaseData.getUserId() == null) {
            throw new BusinessException(800, "不合法请求");
        }

        String requestHash = hashRequest(req);
        IntegrationSessionRequest existing = getExisting(tenantId, userBaseData.getUserId(), req.getExternalRequestId());
        if (existing != null) {
            if (!requestHash.equals(existing.getRequestHash())) {
                throw new BusinessException(110, "externalRequestId已被不同请求使用");
            }
            if (STATUS_SUCCESS.equals(existing.getStatus()) && existing.getChatSessionId() != null) {
                return buildResponse(tenantId, req, existing.getChatSessionId(), false,
                        getWorkspaceStateIfAvailable(req, existing.getChatSessionId()));
            }
            if (STATUS_PROCESSING.equals(existing.getStatus())) {
                throw new BusinessException(110, "同一externalRequestId正在处理中");
            }
        }

        IntegrationSessionRequest record = existing == null
                ? createRecord(tenantId, userBaseData, req.getExternalRequestId(), requestHash)
                : resetFailedRecord(existing, requestHash);
        try {
            chatSessionBizService.normalizeCreateSessionDefaults(req.getCreateSession());
            ChatSessionVo session = chatSessionBizService.createChatSession(tenantId, req.getCreateSession());
            Long chatSessionId = session.getId();
            PlanningWorkspaceStateRes workspaceState = generatePlanningState(tenantId, chatSessionId, req.getGenerationOptions());
            markSuccess(record, chatSessionId);
            return buildResponse(tenantId, req, chatSessionId, true, workspaceState);
        } catch (Exception e) {
            markFailed(record, e);
            throw e;
        }
    }

    private void validateRequest(ExternalSessionInitializeReq req) {
        if (req == null) {
            throw new BusinessException(110, "请求不能为空");
        }
        if (Strings.isNullOrEmpty(req.getExternalRequestId())) {
            throw new BusinessException(110, "externalRequestId不能为空");
        }
        if (req.getCreateSession() == null) {
            throw new BusinessException(110, "createSession不能为空");
        }
    }

    private String hashRequest(ExternalSessionInitializeReq req) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] encoded = digest.digest(JSONObject.toJSONString(req).getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (byte b : encoded) {
                builder.append(String.format("%02x", b));
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 not available", e);
        }
    }

    private IntegrationSessionRequest getExisting(Long tenantId, Long userId, String externalRequestId) {
        QueryWrapper<IntegrationSessionRequest> queryWrapper = new QueryWrapper<IntegrationSessionRequest>();
        queryWrapper.lambda()
                .eq(IntegrationSessionRequest::getTenantId, tenantId)
                .eq(IntegrationSessionRequest::getUserId, userId)
                .eq(IntegrationSessionRequest::getExternalRequestId, externalRequestId);
        return integrationSessionRequestMapper.selectOne(queryWrapper);
    }

    private IntegrationSessionRequest createRecord(Long tenantId,
                                                   UserBaseData userBaseData,
                                                   String externalRequestId,
                                                   String requestHash) {
        IntegrationSessionRequest record = new IntegrationSessionRequest();
        record.setTenantId(tenantId);
        record.setUserId(userBaseData.getUserId());
        record.setPlatform(userBaseData.getAuthType() == null ? null : userBaseData.getAuthType().name());
        record.setExternalRequestId(externalRequestId);
        record.setRequestHash(requestHash);
        record.setStatus(STATUS_PROCESSING);
        record.setCreateTime(new Date());
        integrationSessionRequestMapper.insert(record);
        return record;
    }

    private IntegrationSessionRequest resetFailedRecord(IntegrationSessionRequest record, String requestHash) {
        record.setRequestHash(requestHash);
        record.setStatus(STATUS_PROCESSING);
        record.setErrorMessage(null);
        record.setUpdateTime(new Date());
        integrationSessionRequestMapper.updateById(record);
        return record;
    }

    private PlanningWorkspaceStateRes generatePlanningState(Long tenantId,
                                                            Long chatSessionId,
                                                            ExternalGenerationOptionsDTO options) {
        ExternalGenerationOptionsDTO safeOptions = options == null ? new ExternalGenerationOptionsDTO() : options;
        boolean forceRegenerate = Boolean.TRUE.equals(safeOptions.getForceRegenerate());
        if (Boolean.TRUE.equals(safeOptions.getGenerateCandidatePool())) {
            CandidatePoolGenerateReq generateReq = new CandidatePoolGenerateReq();
            generateReq.setForceRegenerate(forceRegenerate);
            planningStateService.generateCandidatePool(tenantId, chatSessionId, generateReq);
        }
        if (Boolean.TRUE.equals(safeOptions.getGenerateInitialPlan())) {
            InitialPlanGenerateReq generateReq = new InitialPlanGenerateReq();
            generateReq.setForceRegenerate(forceRegenerate);
            generateReq.setOverwriteExistingDraft(forceRegenerate);
            planningStateService.generateInitialPlan(tenantId, chatSessionId, generateReq);
        }
        if (Boolean.TRUE.equals(safeOptions.getGenerateOrderedPlan())) {
            OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
            generateReq.setForceRegenerate(forceRegenerate);
            generateReq.setRegroupByTier(true);
            planningStateService.generateOrderedPlan(tenantId, chatSessionId, generateReq);
        }
        if (Boolean.FALSE.equals(safeOptions.getReturnWorkspaceState())) {
            return null;
        }
        return planningStateService.getPlanningWorkspaceState(chatSessionId);
    }

    private PlanningWorkspaceStateRes getWorkspaceStateIfAvailable(ExternalSessionInitializeReq req, Long chatSessionId) {
        if (req != null && req.getGenerationOptions() != null
                && Boolean.FALSE.equals(req.getGenerationOptions().getReturnWorkspaceState())) {
            return null;
        }
        return planningStateService.getPlanningWorkspaceState(chatSessionId);
    }

    private void markSuccess(IntegrationSessionRequest record, Long chatSessionId) {
        record.setChatSessionId(chatSessionId);
        record.setStatus(STATUS_SUCCESS);
        record.setErrorMessage(null);
        record.setUpdateTime(new Date());
        integrationSessionRequestMapper.updateById(record);
    }

    private void markFailed(IntegrationSessionRequest record, Exception e) {
        record.setStatus(STATUS_FAILED);
        record.setErrorMessage(e.getMessage());
        record.setUpdateTime(new Date());
        integrationSessionRequestMapper.updateById(record);
    }

    private ExternalSessionInitializeRes buildResponse(Long tenantId,
                                                       ExternalSessionInitializeReq req,
                                                       Long chatSessionId,
                                                       boolean created,
                                                       PlanningWorkspaceStateRes workspaceState) {
        ExternalSessionInitializeRes res = new ExternalSessionInitializeRes();
        res.setTenantId(tenantId);
        res.setChatSessionId(chatSessionId);
        res.setExternalRequestId(req.getExternalRequestId());
        res.setStudentName(normalizeStudentName(req));
        res.setCreated(created);
        res.setSessionUrl(buildSessionUrl(req.getReturnOptions(), "/sessionDetailV2", chatSessionId));
        res.setLegacySessionUrl(buildSessionUrl(req.getReturnOptions(), "/sessionDetailLegacy", chatSessionId));
        res.getApis().put("workspaceState", "/gaotu-assistant-bot/inner/planning/" + tenantId
                + "/session/workspace-state?chatSessionId=" + chatSessionId);
        res.getApis().put("orderedPlan", "/gaotu-assistant-bot/inner/planning/" + tenantId
                + "/session/ordered-plan?chatSessionId=" + chatSessionId);
        res.getApis().put("export", "/gaotu-assistant-bot/inner/chat/" + tenantId
                + "/volunteer/export?chatSessionId=" + chatSessionId);
        fillPlanningSummary(res, workspaceState);
        return res;
    }

    private String normalizeStudentName(ExternalSessionInitializeReq req) {
        if (req == null || req.getCreateSession() == null
                || Strings.isNullOrEmpty(req.getCreateSession().getUserName())) {
            return null;
        }
        String studentName = req.getCreateSession().getUserName().trim();
        return Strings.isNullOrEmpty(studentName) ? null : studentName;
    }

    private String buildSessionUrl(ExternalReturnOptionsDTO options, String path, Long chatSessionId) {
        ExternalReturnOptionsDTO safeOptions = options == null ? new ExternalReturnOptionsDTO() : options;
        StringBuilder builder = new StringBuilder();
        if (!Strings.isNullOrEmpty(safeOptions.getWebBaseUrl())) {
            builder.append(trimTrailingSlash(safeOptions.getWebBaseUrl()));
        }
        if ("assistant-pc".equals(safeOptions.getPathMode())) {
            builder.append("/assistant-pc");
        }
        builder.append(path).append("?chatSessionId=").append(chatSessionId);
        return builder.toString();
    }

    private String trimTrailingSlash(String value) {
        if (value.endsWith("/")) {
            return value.substring(0, value.length() - 1);
        }
        return value;
    }

    private void fillPlanningSummary(ExternalSessionInitializeRes res, PlanningWorkspaceStateRes workspaceState) {
        if (workspaceState == null) {
            return;
        }
        res.getPlanning().setPhase(workspaceState.getPhase());
        res.getPlanning().setVersion(workspaceState.getVersion());
        CandidatePoolStateDTO candidatePoolState = workspaceState.getCandidatePoolState();
        if (candidatePoolState != null && candidatePoolState.getSummary() != null) {
            res.getPlanning().setCandidateTotal(candidatePoolState.getSummary().getUnitTotal());
        }
        if (workspaceState.getDraftPlanState() != null && workspaceState.getDraftPlanState().getSummary() != null) {
            res.getPlanning().setDraftTotal(workspaceState.getDraftPlanState().getSummary().getUnitTotal());
        }
        OrderedPlanStateDTO orderedPlanState = workspaceState.getOrderedPlanState();
        if (orderedPlanState != null && orderedPlanState.getSummary() != null) {
            res.getPlanning().setOrderedTotal(orderedPlanState.getSummary().getUnitTotal());
            Map<String, Integer> tierCounts = orderedPlanState.getSummary().getUnitTierCounts();
            if (tierCounts == null || tierCounts.isEmpty()) {
                tierCounts = orderedPlanState.getSummary().getTierCounts();
            }
            res.getPlanning().setTierCounts(tierCounts);
        }
    }
}
