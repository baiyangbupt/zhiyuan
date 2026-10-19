package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPrepareReq;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
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
    void groupPrepareFreezesUnitsAndUnitFactsDigestWithoutChangingPlanState() {
        PlanningStateDTO group = groupInversionFixture();
        row.setDataValue(JSON.toJSONString(group));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = proposalByFindingCode(preview, "probability_inversion");
        assertNotNull(proposal, "group fixture 必须产出 Direct 倒挂提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("unit", proposal.getActions().get(0).getLevel());
        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertEquals(Lists.newArrayList("u-high", "u-mid", "u-low"), frozen.getSelectedEntityIds());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"), frozen.getOrderedEntityIds());
        assertEquals(3, frozen.getWorkingPlan().getUnits().size());
        assertEquals(3, frozen.getOrderedPlan().getUnits().size());
        assertEquals(3, frozen.getOrderedPlan().getItems().size());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"),
                frozen.getOrderedPlan().getUnits().stream()
                        .map(OrderedUnitDTO::getUnitId).collect(java.util.stream.Collectors.toList()));
        assertEquals(Lists.newArrayList("u-low-v", "u-mid-v", "u-high-v"),
                frozen.getOrderedPlan().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId).collect(java.util.stream.Collectors.toList()));
        assertEquals(DirectReviewPreviewPlanner.digestJson(frozen.getSelectedFacts()),
                frozen.getFactsDigest());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group", "digest-group",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        Map<String, Object> action = (Map<String, Object>) ((List) frozenProposal.get("actions")).get(0);
        assertEquals("unit", action.get("level"));
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"), action.get("unitIds"));
        Map<String, Object> frozenMap = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(3, ((List) ((Map) frozenMap.get("workingPlan")).get("units")).size());
        assertEquals(3, ((List) ((Map) frozenMap.get("orderedPlan")).get("units")).size());
        assertEquals(3, ((List) ((Map) frozenMap.get("orderedPlan")).get("items")).size());
        assertNotNull(frozenMap.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void groupPrepareRejectsTamperedPreviewDigest() {
        row.setDataValue(JSON.toJSONString(groupInversionFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(
                proposalByFindingCode(preview, "probability_inversion"), preview.getSourceVersion());
        req.setPreviewDigest("tampered-group-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-group-bad", "digest-group-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    @Test
    void groupCountTargetPrepareFreezesFortySixUnitsAndUnitFacts() {
        PlanningStateDTO group = groupCountTargetFixture();
        row.setDataValue(JSON.toJSONString(group));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = proposalByFindingCode(preview, "count_target");
        assertNotNull(proposal, "group count_target fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("count_target", proposal.getFindingCode());
        assertEquals("unit", proposal.getActions().get(0).getLevel());
        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(46, frozen.getSelectedEntityIds().size());
        assertEquals(46, frozen.getOrderedEntityIds().size());
        assertEquals(46, frozen.getWorkingPlan().getUnits().size());
        assertEquals(46, frozen.getOrderedPlan().getUnits().size());
        assertEquals(92, frozen.getWorkingPlan().getItems().size());
        assertEquals(92, frozen.getOrderedPlan().getItems().size());
        assertEquals(92, frozen.getSelectedFacts().size());
        assertEquals(frozen.getOrderedEntityIds(), frozen.getOrderedPlan().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(java.util.stream.Collectors.toList()));
        assertEquals(DirectReviewPreviewPlanner.digestJson(frozen.getSelectedFacts()),
                frozen.getFactsDigest());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-count", "digest-group-count",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        assertEquals("count_target", ((Map<String, Object>) data.get("frozenProposal")).get("findingCode"));
        Map<String, Object> frozenMap = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(46, ((List) ((Map) frozenMap.get("workingPlan")).get("units")).size());
        assertEquals(46, ((List) ((Map) frozenMap.get("orderedPlan")).get("units")).size());
        assertEquals(92, ((List) ((Map) frozenMap.get("orderedPlan")).get("items")).size());
        assertNotNull(frozenMap.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
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

    @Test
    void freezesCoverageSearchProposalWithoutChangingPlanState() {
        row.setDataValue(JSON.toJSONString(coverageFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = coverageProposal(preview);

        assertNotNull(proposal, "coverage fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("coverage:0", proposal.getFindingCode());
        assertTrue(proposal.getSourceCheckCodes().contains("coverage:0"));
        assertTrue(proposal.getSourceCheckCodes().contains("coverage"));
        assertEquals(80, proposal.getSolverResult().getSelectedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("coverage:0", proposal.getFindingPostcondition().getFindingCode());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-coverage", "digest-coverage",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        assertEquals("coverage:0", frozenProposal.get("findingCode"));
        assertEquals("fill_missing_count", frozenProposal.get("strategy"));
        assertEquals(80, ((List) ((Map) frozenProposal.get("solverResult")).get("selectedEntityIds")).size());
        Map<String, Object> frozen = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(80, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(80, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(80, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(80, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        int zhejiang = 0;
        for (Object fact : (List) frozen.get("selectedFacts")) {
            if (fact instanceof Map && "浙江".equals(((Map) fact).get("provinceName"))) {
                zhejiang++;
            }
        }
        assertTrue(zhejiang >= 20, "冻结事实必须满足浙江覆盖下限");
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void coveragePrepareRejectsTamperedPreviewDigest() {
        row.setDataValue(JSON.toJSONString(coverageFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(coverageProposal(preview), preview.getSourceVersion());
        req.setPreviewDigest("tampered-coverage-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-coverage-bad", "digest-coverage-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    private static FixProposalDTO countTargetProposal(ReviewFixPreviewDTO preview) {
        return proposalByFindingCode(preview, "count_target");
    }

    private static FixProposalDTO coverageProposal(ReviewFixPreviewDTO preview) {
        return proposalByFindingCode(preview, "coverage:0");
    }

    private static FixProposalDTO proposalByFindingCode(ReviewFixPreviewDTO preview, String findingCode) {
        for (FixProposalDTO proposal : preview.getProposals()) {
            if (proposal != null && findingCode.equals(proposal.getFindingCode())) {
                return proposal;
            }
        }
        return null;
    }

    @Test
    void freezesSafetyProposalWithEightyFrozenEntriesAndLocalProtect() {
        row.setDataValue(JSON.toJSONString(safetyFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = safetyProposal(preview);

        assertNotNull(proposal, "safety fixture 必须产出 Safety 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("add_safety_items", proposal.getSourceStrategy());
        assertEquals("safety_guard", proposal.getFindingCode());
        assertEquals("本省保底补齐预览", proposal.getTitle());
        assertEquals(80, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(localProtectCount(proposal.getSolverResult().getSelectedEntityIds()) >= 2);
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("safety_guard", proposal.getFindingPostcondition().getFindingCode());
        assertEquals(80, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedPlan().getItems().size());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-safety", "digest-safety",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        assertEquals("safety_guard", frozenProposal.get("findingCode"));
        assertEquals("fill_missing_count", frozenProposal.get("strategy"));
        assertEquals("add_safety_items", frozenProposal.get("sourceStrategy"));
        assertEquals(80, ((List) ((Map) frozenProposal.get("solverResult")).get("selectedEntityIds")).size());
        Map<String, Object> frozen = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(80, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(80, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(80, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(80, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        int local = 0;
        for (Object fact : (List) frozen.get("selectedFacts")) {
            if (fact instanceof Map && "浙江".equals(((Map) fact).get("provinceName"))) {
                local++;
            }
        }
        assertTrue(local >= 2, "冻结事实必须包含本省保底");
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void safetyPrepareRejectsTamperedPreviewDigest() {
        row.setDataValue(JSON.toJSONString(safetyFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(safetyProposal(preview), preview.getSourceVersion());
        req.setPreviewDigest("tampered-safety-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(TENANT, SESSION, "req-safety-bad", "digest-safety-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    @Test
    void safetyPrepareRejectsStaleSourceVersionGuard() {
        row.setDataValue(JSON.toJSONString(safetyFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(safetyProposal(preview), preview.getSourceVersion());
        req.setSourceVersionGuard(preview.getSourceVersion() - 1);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(TENANT, SESSION, "req-safety-stale", "digest-safety-stale", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    @Test
    void freezesGroupSafetyProposalWithFortyFourUnitsAndTwoLocalProtectUnits() {
        row.setDataValue(JSON.toJSONString(groupSafetyFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = safetyProposal(preview);

        assertNotNull(proposal, "group safety fixture 必须产出 Safety 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("add_safety_items", proposal.getSourceStrategy());
        assertEquals("safety_guard", proposal.getFindingCode());
        assertEquals(44, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(localProtectUnitCount(proposal.getSolverResult().getSelectedEntityIds()) >= 2,
                "组模式 solver 必须选中 2 个江西 protect 专业组");
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals(44, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertEquals(44, proposal.getFrozenReviewPlan().getOrderedEntityIds().size());
        assertEquals(44, proposal.getFrozenReviewPlan().getWorkingPlan().getUnits().size());
        assertEquals(44, proposal.getFrozenReviewPlan().getOrderedPlan().getUnits().size());
        assertEquals(88, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(88, proposal.getFrozenReviewPlan().getOrderedPlan().getItems().size());
        assertEquals(88, proposal.getFrozenReviewPlan().getSelectedFacts().size());
        for (FixProposalActionDTO action : proposal.getActions()) {
            assertEquals("unit", action.getLevel());
        }

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-safety", "digest-group-safety",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        assertEquals("safety_guard", frozenProposal.get("findingCode"));
        assertEquals(44,
                ((List) ((Map) frozenProposal.get("solverResult")).get("selectedEntityIds")).size());
        Map<String, Object> frozen = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(44, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(44, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(44, ((List) ((Map) frozen.get("workingPlan")).get("units")).size());
        assertEquals(44, ((List) ((Map) frozen.get("orderedPlan")).get("units")).size());
        assertEquals(88, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(88, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        assertEquals(88, ((List) frozen.get("selectedFacts")).size());
        List<String> selectedIds = (List<String>) frozen.get("selectedEntityIds");
        assertTrue(localProtectUnitCount(selectedIds) >= 2, "冻结选中集必须含本省保底组");
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void groupSafetyPrepareRejectsTamperedPreviewDigest() {
        row.setDataValue(JSON.toJSONString(groupSafetyFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq req = prepareRequest(safetyProposal(preview), preview.getSourceVersion());
        req.setPreviewDigest("tampered-group-safety-preview");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-group-safety-bad", "digest-group-safety-bad", req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertTrue(upserts.isEmpty());
    }

    private static long localProtectUnitCount(List<String> unitIds) {
        // 单元事实由候选池派生：同一 unit 的任一专业即代表整组。
        List<CandidateItemDTO> pool = groupSafetyFixture().getCandidatePoolState().getItems();
        return unitIds.stream().filter(unitId -> {
            for (CandidateItemDTO candidate : pool) {
                if (unitId.equals(candidate.getPlanSchoolDataId())) {
                    return "protect".equals(candidate.getTier())
                            && "江西".equals(candidate.getProvinceName());
                }
            }
            return false;
        }).count();
    }

    private static FixProposalDTO safetyProposal(ReviewFixPreviewDTO preview) {
        return proposalByFindingCode(preview, "safety_guard");
    }

    @Test
    void freezesRatioProposalWithRebalancedFrozenEntries() {
        row.setDataValue(JSON.toJSONString(ratioFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = ratioProposal(preview);

        assertNotNull(proposal, "ratio fixture 必须产出 Ratio 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("rebalance_tier_ratio", proposal.getSourceStrategy());
        assertEquals("ratio_distribution", proposal.getFindingCode());
        assertEquals("冲稳保配比调整预览", proposal.getTitle());
        assertEquals(80, proposal.getSolverResult().getSelectedEntityIds().size());
        assertEquals(40, tierCount(proposal.getSolverResult().getSelectedEntityIds(), "sprint"));
        assertEquals(20, tierCount(proposal.getSolverResult().getSelectedEntityIds(), "stable"));
        assertEquals(20, tierCount(proposal.getSolverResult().getSelectedEntityIds(), "protect"));
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("ratio_distribution", proposal.getFindingPostcondition().getFindingCode());
        assertEquals(80, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedPlan().getItems().size());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-ratio", "digest-ratio",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        assertEquals("ratio_distribution", frozenProposal.get("findingCode"));
        assertEquals("fill_missing_count", frozenProposal.get("strategy"));
        assertEquals("rebalance_tier_ratio", frozenProposal.get("sourceStrategy"));
        assertEquals(80, ((List) ((Map) frozenProposal.get("solverResult")).get("selectedEntityIds")).size());
        Map<String, Object> frozen = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(80, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(80, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(80, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(80, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void ratioPrepareRejectsTamperedPreviewDigestAndStaleGuard() {
        row.setDataValue(JSON.toJSONString(ratioFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq tampered = prepareRequest(ratioProposal(preview), preview.getSourceVersion());
        tampered.setPreviewDigest("tampered-ratio-preview");

        BusinessException changed = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-ratio-bad", "digest-ratio-bad", tampered));
        assertEquals(409, changed.getStatus());
        assertEquals("review_fix_changed", changed.getMessage());
        assertTrue(upserts.isEmpty());

        ReviewFixPrepareReq stale = prepareRequest(ratioProposal(preview), preview.getSourceVersion());
        stale.setSourceVersionGuard(preview.getSourceVersion() - 1);
        BusinessException outdated = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-ratio-stale", "digest-ratio-stale", stale));
        assertEquals(409, outdated.getStatus());
        assertEquals("review_fix_stale", outdated.getMessage());
        assertTrue(upserts.isEmpty());
    }

    private static FixProposalDTO ratioProposal(ReviewFixPreviewDTO preview) {
        return proposalByFindingCode(preview, "ratio_distribution");
    }

    @Test
    void freezesRiskReplaceProposalWithForcedRemovalAndEightyFrozenEntries() {
        row.setDataValue(JSON.toJSONString(riskReplaceFixture()));
        String baseline = row.getDataValue();

        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = riskProposal(preview);

        assertNotNull(proposal, "risk fixture 必须产出 RiskReplace 提案");
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("replace_risk_items", proposal.getSourceStrategy());
        assertEquals("high_tuition", proposal.getFindingCode());
        assertEquals("风险条目替换预览", proposal.getTitle());
        assertEquals(80, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(proposal.getSolverResult().getRemoveEntityIds().contains("v001"));
        assertFalse(proposal.getSolverResult().getSelectedEntityIds().contains("v001"));
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("high_tuition", proposal.getFindingPostcondition().getFindingCode());
        assertEquals(80, proposal.getFrozenReviewPlan().getSelectedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedEntityIds().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(80, proposal.getFrozenReviewPlan().getOrderedPlan().getItems().size());

        PrepareResultDTO dto = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-risk", "digest-risk",
                prepareRequest(proposal, preview.getSourceVersion()));

        assertEquals("prepared", dto.getStatus());
        assertEquals(1, upserts.size());
        Map<String, Object> data = upserts.get(0).getDataValue();
        Map<String, Object> frozenProposal = (Map<String, Object>) data.get("frozenProposal");
        assertEquals("high_tuition", frozenProposal.get("findingCode"));
        assertEquals("fill_missing_count", frozenProposal.get("strategy"));
        assertEquals("replace_risk_items", frozenProposal.get("sourceStrategy"));
        assertEquals(80, ((List) ((Map) frozenProposal.get("solverResult")).get("selectedEntityIds")).size());
        assertTrue(((List) ((Map) frozenProposal.get("solverResult")).get("removeEntityIds"))
                .contains("v001"));
        Map<String, Object> frozen = (Map<String, Object>) data.get("frozenReviewPlan");
        assertEquals(80, ((List) frozen.get("selectedEntityIds")).size());
        assertEquals(80, ((List) frozen.get("orderedEntityIds")).size());
        assertEquals(80, ((List) ((Map) frozen.get("workingPlan")).get("items")).size());
        assertEquals(80, ((List) ((Map) frozen.get("orderedPlan")).get("items")).size());
        assertFalse(((List) frozen.get("selectedEntityIds")).contains("v001"));
        assertNotNull(frozen.get("factsDigest"));
        assertEquals(baseline, row.getDataValue(), "prepare 只冻结 pending，不写方案状态");
    }

    @Test
    void riskPrepareRejectsTamperedPreviewDigestAndStaleGuard() {
        row.setDataValue(JSON.toJSONString(riskReplaceFixture()));
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        ReviewFixPrepareReq tampered = prepareRequest(riskProposal(preview), preview.getSourceVersion());
        tampered.setPreviewDigest("tampered-risk-preview");

        BusinessException changed = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-risk-bad", "digest-risk-bad", tampered));
        assertEquals(409, changed.getStatus());
        assertEquals("review_fix_changed", changed.getMessage());
        assertTrue(upserts.isEmpty());

        ReviewFixPrepareReq stale = prepareRequest(riskProposal(preview), preview.getSourceVersion());
        stale.setSourceVersionGuard(preview.getSourceVersion() - 1);
        BusinessException outdated = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(
                        TENANT, SESSION, "req-risk-stale", "digest-risk-stale", stale));
        assertEquals(409, outdated.getStatus());
        assertEquals("review_fix_stale", outdated.getMessage());
        assertTrue(upserts.isEmpty());
    }

    private static FixProposalDTO riskProposal(ReviewFixPreviewDTO preview) {
        return proposalByFindingCode(preview, "high_tuition");
    }

    /**
     * 80 条已有志愿、目标 80；v001 学费 3 万/学年（high_tuition fail），
     * 其余 2 万以内，候选池尾部另有 1 条低学费替代。forcedRemove v001 后
     * 等量补入替代，保持 80 条。
     */
    static PlanningStateDTO riskReplaceFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(80);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        // ≥580：本省保底不适用，避免 safety_guard 干扰风险替换后置校验。
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(80);
        for (int index = 1; index <= 81; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(String.format("v%03d", index));
            candidate.setSchoolName("学校" + index);
            candidate.setDisplaySchoolName("学校" + index);
            candidate.setMajorName("专业" + index);
            candidate.setMajorCategory("工学");
            candidate.setTier("protect");
            candidate.setProvinceName("浙江");
            candidate.setTuitionPerYear(index == 1 ? 30000 : 5000);
            candidate.setAdmissionRatio(50D);
            candidate.setSchoolEnrollRatio(50D);
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

    private int tierCount(List<String> ids, String tier) {
        PlanningStateDTO current = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        Map<String, String> tierById = new LinkedHashMap<String, String>();
        for (CandidateItemDTO candidate : current.getCandidatePoolState().getItems()) {
            tierById.put(candidate.getVolunteerId(), candidate.getTier());
        }
        int count = 0;
        for (String id : ids) {
            if (tier.equals(tierById.get(id))) {
                count++;
            }
        }
        return count;
    }

    private long localProtectCount(List<String> ids) {
        PlanningStateDTO current = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        Map<String, String> provinceById = new LinkedHashMap<String, String>();
        Map<String, String> tierById = new LinkedHashMap<String, String>();
        for (CandidateItemDTO candidate : current.getCandidatePoolState().getItems()) {
            provinceById.put(candidate.getVolunteerId(), candidate.getProvinceName());
            tierById.put(candidate.getVolunteerId(), candidate.getTier());
        }
        long count = 0;
        for (String id : ids) {
            if ("浙江".equals(provinceById.get(id)) && "protect".equals(tierById.get(id))) {
                count++;
            }
        }
        return count;
    }

    /**
     * 80 条已有志愿（全部非浙江）、目标 80；本省保底要求浙江 protect ≥ 2，
     * 候选池尾部有 3 条浙江 protect。safety_guard fail → add_safety_items。
     */
    static PlanningStateDTO safetyFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(80);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(80);
        for (int index = 1; index <= 83; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(String.format("v%03d", index));
            candidate.setSchoolName("学校" + index);
            candidate.setDisplaySchoolName("学校" + index);
            candidate.setMajorName("专业" + index);
            candidate.setMajorCategory("工学");
            candidate.setTier("protect");
            candidate.setProvinceName(index <= 80 ? "江苏" : "浙江");
            candidate.setAdmissionRatio(10D + index);
            candidate.setSchoolEnrollRatio(10D + index);
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

    /**
     * 组模式 count_target：44 个专业组（每组 2 个专业）、目标 46 组；
     * 候选池另提供 4 组可补。前 2 组本省 protect 满足安全垫，组内录取率高于
     * 组投档比例；其余候选组同构，硬口径不额外失败。
     */
    static PlanningStateDTO groupCountTargetFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(46);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        // <580 → 本省保底 2 组；前两组浙江 protect 已满足。
        state.getCandidatePoolState().setUserScore(550);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(46);
        for (int unitIndex = 1; unitIndex <= 48; unitIndex++) {
            String unitId = String.format("u%03d", unitIndex);
            boolean current = unitIndex <= 44;
            boolean local = unitIndex <= 2;
            DraftUnitDTO workingUnit = null;
            OrderedUnitDTO orderedUnit = null;
            if (current) {
                workingUnit = new DraftUnitDTO();
                workingUnit.setUnitId(unitId);
                workingUnit.setTier("protect");
                workingUnit.setSchoolName("学校" + unitIndex + "第01组");
                orderedUnit = new OrderedUnitDTO();
                orderedUnit.setUnitId(unitId);
                orderedUnit.setPosition(unitIndex);
                orderedUnit.setTier("protect");
                orderedUnit.setSchoolName("学校" + unitIndex + "第01组");
                orderedUnit.setProvinceName(local ? "浙江" : "江苏");
                orderedUnit.setAdmissionRatio(65D);
                orderedUnit.setSchoolEnrollRatio(60D);
            }
            for (int majorIndex = 1; majorIndex <= 2; majorIndex++) {
                String volunteerId = unitId + "-v" + majorIndex;
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId(volunteerId);
                candidate.setPlanSchoolDataId(unitId);
                candidate.setSchoolId("s" + unitId);
                candidate.setSchoolName("学校" + unitIndex + "第01组");
                candidate.setDisplaySchoolName("学校" + unitIndex + "第01组");
                candidate.setMajorName("专业" + unitIndex + "-" + majorIndex);
                candidate.setMajorCategory("工学");
                candidate.setTier("protect");
                candidate.setProvinceName(local ? "浙江" : "江苏");
                candidate.setAdmissionRatio(65D);
                candidate.setSchoolEnrollRatio(60D);
                candidate.setFinalScore(80D);
                candidate.setIntentScore(40D);
                candidate.setTuitionPerYear(5000);
                state.getCandidatePoolState().getItems().add(candidate);
                RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
                overlay.setVolunteerId(volunteerId);
                state.getRecommendationOverlayState().getItems().add(overlay);
                if (!current) {
                    continue;
                }
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(volunteerId);
                selected.setTier("protect");
                selected.setSchoolName(candidate.getSchoolName());
                selected.setMajorName(candidate.getMajorName());
                state.getWorkingPlanState().getItems().add(selected);

                PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
                workingMajor.setVolunteerId(volunteerId);
                workingMajor.setMajorName(candidate.getMajorName());
                workingMajor.setTier("protect");
                workingUnit.getMajorItems().add(workingMajor);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(volunteerId);
                ordered.setTier("protect");
                ordered.setSchoolName(candidate.getSchoolName());
                ordered.setMajorName(candidate.getMajorName());
                ordered.setPosition(state.getOrderedPlanState().getItems().size() + 1);
                state.getOrderedPlanState().getItems().add(ordered);

                PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
                orderedMajor.setVolunteerId(volunteerId);
                orderedMajor.setMajorName(candidate.getMajorName());
                orderedMajor.setTier("protect");
                orderedUnit.getMajorItems().add(orderedMajor);
            }
            if (current) {
                state.getWorkingPlanState().getUnits().add(workingUnit);
                state.getOrderedPlanState().getUnits().add(orderedUnit);
            }
        }
        return state;
    }

    /**
     * 组模式 safety：44 个专业组全部是外省冲刺（0 个本省保底），目标 44；
     * 候选池另有 2 个江西 protect 专业组。safety_guard fail → add_safety_items，
     * 通过等量替换把 2 组本省保底换进来。
     */
    static PlanningStateDTO groupSafetyFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(44);
        state.getCandidatePoolState().setSourceProvinceName("江西");
        // <580 → 本省保底 2 组；现有 44 组全是外省冲刺，保底为 0。
        state.getCandidatePoolState().setUserScore(550);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(44);
        for (int unitIndex = 1; unitIndex <= 46; unitIndex++) {
            String unitId = String.format("u%03d", unitIndex);
            boolean current = unitIndex <= 44;
            boolean local = unitIndex > 44;
            String tier = local ? "protect" : "sprint";
            String province = local ? "江西" : "江苏";
            String schoolName = "学校" + unitIndex + "第01组";
            DraftUnitDTO workingUnit = null;
            OrderedUnitDTO orderedUnit = null;
            if (current) {
                workingUnit = new DraftUnitDTO();
                workingUnit.setUnitId(unitId);
                workingUnit.setTier(tier);
                workingUnit.setSchoolName(schoolName);
                orderedUnit = new OrderedUnitDTO();
                orderedUnit.setUnitId(unitId);
                orderedUnit.setPosition(unitIndex);
                orderedUnit.setTier(tier);
                orderedUnit.setSchoolName(schoolName);
                orderedUnit.setProvinceName(province);
                orderedUnit.setAdmissionRatio(70D);
                orderedUnit.setSchoolEnrollRatio(60D);
                orderedUnit.setTotalMajorCount(2);
            }
            for (int majorIndex = 1; majorIndex <= 2; majorIndex++) {
                String volunteerId = unitId + "-v" + majorIndex;
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId(volunteerId);
                candidate.setPlanSchoolDataId(unitId);
                candidate.setSchoolId("s" + unitId);
                candidate.setSchoolName(schoolName);
                candidate.setDisplaySchoolName(schoolName);
                candidate.setMajorName("专业" + unitIndex + "-" + majorIndex);
                candidate.setMajorCategory("工学");
                candidate.setTier(tier);
                candidate.setProvinceName(province);
                candidate.setAdmissionRatio(70D);
                candidate.setSchoolEnrollRatio(60D);
                candidate.setFinalScore(80D);
                candidate.setIntentScore(40D);
                candidate.setTuitionPerYear(5000);
                state.getCandidatePoolState().getItems().add(candidate);
                RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
                overlay.setVolunteerId(volunteerId);
                state.getRecommendationOverlayState().getItems().add(overlay);
                if (!current) {
                    continue;
                }
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(volunteerId);
                selected.setTier(tier);
                selected.setSchoolName(schoolName);
                selected.setMajorName(candidate.getMajorName());
                state.getWorkingPlanState().getItems().add(selected);

                PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
                workingMajor.setVolunteerId(volunteerId);
                workingMajor.setMajorName(candidate.getMajorName());
                workingMajor.setTier(tier);
                workingUnit.getMajorItems().add(workingMajor);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(volunteerId);
                ordered.setTier(tier);
                ordered.setSchoolName(schoolName);
                ordered.setMajorName(candidate.getMajorName());
                ordered.setPosition(state.getOrderedPlanState().getItems().size() + 1);
                state.getOrderedPlanState().getItems().add(ordered);

                PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
                orderedMajor.setVolunteerId(volunteerId);
                orderedMajor.setMajorName(candidate.getMajorName());
                orderedMajor.setTier(tier);
                orderedUnit.getMajorItems().add(orderedMajor);
            }
            if (current) {
                state.getWorkingPlanState().getUnits().add(workingUnit);
                state.getOrderedPlanState().getUnits().add(orderedUnit);
            }
        }
        return state;
    }

    /**
     * 80 条已有志愿、目标 80；已确认精确配额 冲40/稳20/保20，但存量全部是冲档。
     * 候选池另有 20 条稳档 + 20 条保档，Ratio 必须移出 40 条冲档并等量补入缺口档位。
     */
    static PlanningStateDTO ratioFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(80);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        // ≥580：本省保底不适用，避免 safety_guard 干扰配比后置校验。
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(80);
        TierQuotaGoalDTO quota = new TierQuotaGoalDTO();
        quota.setType("exact_counts");
        quota.setSprintCount(40);
        quota.setStableCount(20);
        quota.setProtectCount(20);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota);
        for (int index = 1; index <= 120; index++) {
            String tier = index <= 80 ? "sprint" : index <= 100 ? "stable" : "protect";
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(String.format("v%03d", index));
            candidate.setSchoolName("学校" + index);
            candidate.setDisplaySchoolName("学校" + index);
            candidate.setMajorName("专业" + index);
            candidate.setMajorCategory("工学");
            candidate.setTier(tier);
            candidate.setProvinceName("浙江");
            candidate.setAdmissionRatio(90D - index * 0.5D);
            candidate.setSchoolEnrollRatio(90D - index * 0.5D);
            candidate.setFinalScore(80D);
            candidate.setIntentScore(40D);
            state.getCandidatePoolState().getItems().add(candidate);

            RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
            overlay.setVolunteerId(candidate.getVolunteerId());
            state.getRecommendationOverlayState().getItems().add(overlay);
            if (index <= 80) {
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(candidate.getVolunteerId());
                selected.setTier(tier);
                state.getWorkingPlanState().getItems().add(selected);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(candidate.getVolunteerId());
                ordered.setTier(tier);
                ordered.setPosition(index);
                state.getOrderedPlanState().getItems().add(ordered);
            }
        }
        return state;
    }

    /**
     * 80 条已有志愿、目标 80；存量只有 10 条浙江，覆盖要求浙江 ≥ 20（fail）。
     * 候选池尾部另有 20 条浙江，Search 必须等量替换 10 条非浙江而不能改变总数。
     */
    static PlanningStateDTO coverageFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(80);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(80);
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("region");
        requirement.setKey("province");
        requirement.setValues(Lists.newArrayList("浙江"));
        requirement.setMinCount(20);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(requirement);
        for (int index = 1; index <= 100; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(String.format("v%03d", index));
            candidate.setSchoolName("学校" + index);
            candidate.setDisplaySchoolName("学校" + index);
            candidate.setMajorName("专业" + index);
            candidate.setMajorCategory("工学");
            candidate.setTier("protect");
            candidate.setProvinceName(index <= 10 || index > 80 ? "浙江" : "江苏");
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

    /**
     * 组模式倒挂：3 个专业组（unit），录取率 90/60/30 逆序排列；组内专业满足
     * 安全垫（admissionRatio 95 > schoolEnrollRatio 90），硬口径与组内安全垫均通过。
     */
    static PlanningStateDTO groupInversionFixture() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        String[] unitIds = {"u-high", "u-mid", "u-low"};
        double[] ratios = {90D, 60D, 30D};
        for (int index = 0; index < unitIds.length; index++) {
            String volunteerId = unitIds[index] + "-v";
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(volunteerId);
            candidate.setSchoolName("学校" + (index + 1) + "第01组");
            candidate.setDisplaySchoolName("学校" + (index + 1) + "第01组");
            candidate.setMajorName("专业" + (index + 1));
            candidate.setMajorCategory("工学");
            candidate.setTier("protect");
            candidate.setProvinceName("浙江");
            candidate.setAdmissionRatio(95D);
            candidate.setSchoolEnrollRatio(90D);
            candidate.setFinalScore(80D);
            candidate.setIntentScore(40D);
            candidate.setTuitionPerYear(5000);
            state.getCandidatePoolState().getItems().add(candidate);

            RecommendationOverlayStateDTO.Item overlay = new RecommendationOverlayStateDTO.Item();
            overlay.setVolunteerId(volunteerId);
            state.getRecommendationOverlayState().getItems().add(overlay);

            PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
            workingMajor.setVolunteerId(volunteerId);
            workingMajor.setMajorName(candidate.getMajorName());
            workingMajor.setTier("protect");

            DraftUnitDTO workingUnit = new DraftUnitDTO();
            workingUnit.setUnitId(unitIds[index]);
            workingUnit.setTier("protect");
            workingUnit.setSchoolName(candidate.getSchoolName());
            workingUnit.getMajorItems().add(workingMajor);
            state.getWorkingPlanState().getUnits().add(workingUnit);

            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(volunteerId);
            selected.setTier("protect");
            state.getWorkingPlanState().getItems().add(selected);

            PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
            orderedMajor.setVolunteerId(volunteerId);
            orderedMajor.setMajorName(candidate.getMajorName());
            orderedMajor.setTier("protect");

            OrderedUnitDTO orderedUnit = new OrderedUnitDTO();
            orderedUnit.setUnitId(unitIds[index]);
            orderedUnit.setPosition(index + 1);
            orderedUnit.setTier("protect");
            orderedUnit.setSchoolName(candidate.getSchoolName());
            orderedUnit.setProvinceName("浙江");
            orderedUnit.setAdmissionRatio(ratios[index]);
            orderedUnit.setSchoolEnrollRatio(ratios[index]);
            orderedUnit.getMajorItems().add(orderedMajor);
            state.getOrderedPlanState().getUnits().add(orderedUnit);

            OrderedItemDTO ordered = new OrderedItemDTO();
            ordered.setVolunteerId(volunteerId);
            ordered.setTier("protect");
            ordered.setPosition(index + 1);
            state.getOrderedPlanState().getItems().add(ordered);
        }
        return state;
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
