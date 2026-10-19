package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPrepareReq;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPreviewDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.ConversationProposalRequestEntity;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * J5.5b prepare：只读预览 → 冻结 pending。
 *
 * <p>用真实 PlanningStateService（读库、审查、DirectReviewPreviewPlanner 全跑）+
 * 内存假表跑真实 ConversationProposalRequestService 的幂等状态机。被替换的只有存储层，
 * 这样“同一 requestId 重放同 operationId”才是对真实状态机的证据。</p>
 */
class PlanningStateServiceReviewFixPrepareTest {

    private static final long TENANT = 7L;
    private static final long SESSION = 101L;

    private final List<PendingConfirmationUpsertReq> upserts = new ArrayList<>();
    private final Map<String, ConversationProposalRequestEntity> requestTable = new LinkedHashMap<>();
    private final AtomicInteger requestIdSeq = new AtomicInteger();
    private PlanningStateService service;
    private ChatSessionExtraData row;
    private PlanningStateDTO state;

    @BeforeEach
    void setUp() {
        System.setProperty(ReviewFixCommandFlags.PROPERTY, "true");
        state = inversionFixture();
        row = new ChatSessionExtraData();
        row.setDataValue(JSON.toJSONString(state));

        ChatSessionExtraDataSharedService storage = mock(ChatSessionExtraDataSharedService.class);
        when(storage.getBySessionIdAndDataKey(anyLong(), anyString())).thenAnswer(invocation ->
                ChatSessionExtraDataConstants.PLANNING_STATE_KEY.equals(invocation.getArgument(1))
                        ? row : null);

        PendingConfirmationBizService pending = mock(PendingConfirmationBizService.class);
        when(pending.upsert(anyLong(), any(PendingConfirmationUpsertReq.class))).thenAnswer(invocation -> {
            PendingConfirmationUpsertReq req = invocation.getArgument(1);
            upserts.add(req);
            PendingConfirmationRes res = new PendingConfirmationRes();
            res.setPendingId(req.getPendingId());
            res.setRevision(1L);
            res.setStatus("active");
            res.setDataValue(req.getDataValue());
            return res;
        });

        service = new PlanningStateService();
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", storage);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pending);
        ReflectionTestUtils.setField(service, "conversationProposalRequestService", inMemoryPrepareService());
    }

    @AfterEach
    void tearDown() {
        System.clearProperty(ReviewFixCommandFlags.PROPERTY);
    }

    @Test
    void freezesProposalAndAllDigestsIntoPendingWith32HexOperationId() {
        ReviewFixPrepareReq req = prepareRequest();

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-1", "digest-1", req);

        assertEquals("prepared", dto.getStatus());
        assertNotNull(dto.getPendingId());
        assertNotNull(dto.getOperationId());
        assertEquals(32, dto.getOperationId().length());
        assertFalse(dto.getOperationId().contains("-"));
        assertEquals(1, upserts.size());

        PendingConfirmationUpsertReq upsert = upserts.get(0);
        assertEquals("plan_change_proposal", upsert.getKind());
        assertEquals("apply_plan_change_proposal", upsert.getActionFamily());
        assertEquals(Long.valueOf(0L), upsert.getExpectedRevision());
        assertEquals(dto.getPendingId(), upsert.getPendingId());

        Map<String, Object> data = upsert.getDataValue();
        assertEquals(dto.getOperationId(), data.get("operationId"));
        assertEquals("review_check", data.get("proposalSource"));
        assertEquals(req.getProposalId(), data.get("proposalId"));
        assertEquals(7, data.get("sourceVersion"));
        assertEquals(req.getEvaluationVersion(), data.get("evaluationVersion"));
        assertEquals(req.getCommandDigest(), data.get("commandDigest"));
        assertEquals(req.getPreviewDigest(), data.get("previewDigest"));
        assertNotNull(data.get("planContentDigest"));
        assertNotNull(data.get("canonicalObjectiveDigest"));
        assertEquals(Boolean.TRUE, data.get("regenerateOrderedPlan"));
        assertEquals(Boolean.TRUE, data.get("rerunReview"));
        assertEquals(64, String.valueOf(data.get("frozenRequestDigest")).length());
        assertTrue(data.get("frozenProposal") instanceof Map);
        assertTrue(data.get("frozenReviewPlan") instanceof Map);
        Map frozen = (Map) data.get("frozenReviewPlan");
        assertEquals(Lists.newArrayList("low", "mid", "high"), frozen.get("orderedEntityIds"));
        assertNotNull(frozen.get("factsDigest"));
    }

    @Test
    void replayingTheSameRequestIdReturnsTheSameOperationIdWithoutASecondUpsert() {
        ReviewFixPrepareReq req = prepareRequest();
        PrepareResultDTO first = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-replay", "digest-replay", req);
        PrepareResultDTO replay = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-replay", "digest-replay", req);

        assertEquals(first.getOperationId(), replay.getOperationId());
        assertEquals(first.getPendingId(), replay.getPendingId());
        assertEquals(1, upserts.size(), "幂等重放不得再物化第二个 pending");
    }

    @Test
    void mismatchedPreviewDigestIsRejectedAsChanged() {
        ReviewFixPrepareReq req = prepareRequest();
        req.setPreviewDigest("tampered-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(TENANT, SESSION, "req-bad", "digest-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty(), "校验失败不得留下 pending");
    }

    @Test
    void staleSourceVersionGuardIsRejectedAsStale() {
        ReviewFixPrepareReq req = prepareRequest();
        req.setSourceVersionGuard(6);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(TENANT, SESSION, "req-stale", "digest-stale", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    @Test
    void disabledFlagRejectsPrepareBeforeAnyWork() {
        System.clearProperty(ReviewFixCommandFlags.PROPERTY);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-off", "digest-off", prepareRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_command_disabled", ex.getMessage());
        assertTrue(upserts.isEmpty());
        assertTrue(requestTable.isEmpty());
    }

    private ReviewFixPrepareReq prepareRequest() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        assertNotNull(preview.getReview());
        assertEquals("completed", preview.getReview().getEvaluationStatus());
        assertFalse(preview.getProposals().isEmpty(), "fixture 必须产出一份倒挂修复预览");
        FixProposalDTO proposal = preview.getProposals().get(0);
        return prepareRequest(proposal, preview.getSourceVersion());
    }

    private ReviewFixPrepareReq prepareRequest(FixProposalDTO proposal, Integer sourceVersion) {
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(sourceVersion);
        return req;
    }

    @Test
    void freezesCountTargetSearchProposalWithEightyTwoFrozenEntries() {
        row.setDataValue(JSON.toJSONString(countTargetFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = countTargetProposal(preview);

        assertNotNull(proposal, "count_target fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("count_target", proposal.getFindingCode());
        assertEquals(82, proposal.getSolverResult().getSelectedEntityIds().size());
        assertEquals(82, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertEquals(82, proposal.getFrozenReviewPlan().getOrderedEntityIds().size());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-count", "digest-count",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        assertEquals("count_target", ((Map) data.get("frozenProposal")).get("findingCode"));
        assertEquals("fill_missing_count", ((Map) data.get("frozenProposal")).get("strategy"));
        assertEquals(82, ((List) ((Map) ((Map) data.get("frozenProposal"))
                .get("solverResult")).get("selectedEntityIds")).size());
        Map frozen = (Map) data.get("frozenReviewPlan");
        assertEquals(82, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(82, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(82, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(82, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void countTargetPrepareRejectsTamperedPreviewDigest() {
        row.setDataValue(JSON.toJSONString(countTargetFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(countTargetProposal(preview), preview.getSourceVersion());
        req.setPreviewDigest("tampered-count-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(TENANT, SESSION, "req-count-bad", "digest-count-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    private static FixProposalDTO countTargetProposal(ReviewFixPreviewDTO preview) {
        for (FixProposalDTO proposal : preview.getProposals()) {
            if (proposal != null && "count_target".equals(proposal.getFindingCode())) {
                return proposal;
            }
        }
        return null;
    }

    /**
     * 80 条已有志愿、目标 82：count_target fail，Search 从候选池补 2 条。
     * 硬口径（官方 82）与软口径（目标 82）都要求补齐后才能通过后置校验。
     */
    static PlanningStateDTO countTargetFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(82);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(82);
        for (int index = 1; index <= 84; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(String.format("v%03d", index));
            candidate.setSchoolName("学校" + index);
            candidate.setDisplaySchoolName("学校" + index);
            candidate.setMajorName("专业" + index);
            candidate.setMajorCategory("工学");
            candidate.setTier("protect");
            candidate.setProvinceName("浙江");
            candidate.setAdmissionRatio(40D + index);
            candidate.setSchoolEnrollRatio(40D + index);
            candidate.setFinalScore(80D);
            candidate.setIntentScore(40D);
            state.getCandidatePoolState().getItems().add(candidate);

            RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
            overlay.setVolunteerId(candidate.getVolunteerId());
            state.getRecommendationOverlayState().getItems().add(overlay);
            if (index <= 80) {
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(candidate.getVolunteerId());
                selected.setTier("protect");
                state.getWorkingPlanState().getItems().add(selected);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(candidate.getVolunteerId());
                ordered.setTier("protect");
                ordered.setPosition(index);
                state.getOrderedPlanState().getItems().add(ordered);
            }
        }
        return state;
    }

    /** 假表 + 真实状态机：与 ConversationProposalRequestServiceTest 同一套替身。 */
    private ConversationProposalRequestService inMemoryPrepareService() {
        ConversationProposalRequestService prepareService = new ConversationProposalRequestService() {
            @Override
            public ConversationProposalRequestEntity find(Long tenantId, Long chatSessionId, String requestId) {
                return requestTable.get(key(tenantId, chatSessionId, requestId));
            }

            @Override
            protected int supersedeSiblings(Long tenantId, Long chatSessionId, String requestId) {
                int affected = 0;
                for (ConversationProposalRequestEntity candidate : requestTable.values()) {
                    if (candidate.getTenantId().equals(tenantId)
                            && candidate.getChatSessionId().equals(chatSessionId)
                            && !candidate.getRequestId().equals(requestId)
                            && ConversationProposalRequestService.STATUS_PREPARED.equals(candidate.getStatus())) {
                        candidate.setStatus(ConversationProposalRequestService.STATUS_SUPERSEDED);
                        affected++;
                    }
                }
                return affected;
            }
        };
        ConversationProposalRequestMapper mapper = mock(ConversationProposalRequestMapper.class);
        when(mapper.insert(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity entity = invocation.getArgument(0);
            String key = key(entity.getTenantId(), entity.getChatSessionId(), entity.getRequestId());
            if (requestTable.containsKey(key)) {
                throw new DuplicateKeyException("uk_conversation_proposal_request");
            }
            entity.setId((long) requestIdSeq.incrementAndGet());
            requestTable.put(key, entity);
            return 1;
        });
        when(mapper.updateById(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity entity = invocation.getArgument(0);
            requestTable.put(key(entity.getTenantId(), entity.getChatSessionId(), entity.getRequestId()), entity);
            return 1;
        });
        when(mapper.deleteById(any(java.io.Serializable.class))).thenAnswer(invocation -> {
            requestTable.values().removeIf(entity -> entity.getId()
                    .equals(((Number) invocation.getArgument(0)).longValue()));
            return 1;
        });
        ReflectionTestUtils.setField(prepareService, "requestMapper", mapper);
        return prepareService;
    }

    private static String key(Long tenantId, Long chatSessionId, String requestId) {
        return tenantId + ":" + chatSessionId + ":" + requestId;
    }

    static PlanningStateDTO inversionFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        String[] identities = {"high", "mid", "low"};
        double[] ratios = {90D, 60D, 30D};
        for (int index = 0; index < identities.length; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(identities[index]);
            candidate.setAdmissionRatio(ratios[index]);
            candidate.setSchoolEnrollRatio(ratios[index]);
            candidate.setTier("protect");
            candidate.setProvinceName("浙江");
            state.getCandidatePoolState().getItems().add(candidate);

            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(identities[index]);
            selected.setTier("protect");
            state.getWorkingPlanState().getItems().add(selected);

            OrderedItemDTO ordered = new OrderedItemDTO();
            ordered.setVolunteerId(identities[index]);
            ordered.setTier("protect");
            ordered.setPosition(index + 1);
            state.getOrderedPlanState().getItems().add(ordered);

            RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
            overlay.setVolunteerId(identities[index]);
            state.getRecommendationOverlayState().getItems().add(overlay);
        }
        return state;
    }
}
