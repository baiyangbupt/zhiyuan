package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.ConversationProposalRequestMapper;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
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

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * J5.5b apply：prepare 冻结 → 冻结回放 → 原探针后置校验。
 *
 * <p>覆盖：冻结顺序原样落盘、摘要篡改 409、方案漂移 409、事实漂移 409、
 * 后置条件失败不落盘（回滚）、没有冻结 pending 时拒绝直接 apply。</p>
 */
class PlanningStateServiceReviewFixApplyTest {

    private static final long TENANT = 7L;
    private static final long SESSION = 101L;

    private final Map<String, ConversationProposalRequestEntity> requestTable = new LinkedHashMap<>();
    private final AtomicInteger requestIdSeq = new AtomicInteger();
    private PlanningStateService service;
    private ChatSessionExtraData row;
    private PendingConfirmationRes activePending;

    @BeforeEach
    void setUp() {
        System.setProperty(ReviewFixCommandFlags.PROPERTY, "true");
        System.setProperty(ReviewFixSearchFlags.PROPERTY, "true");
        row = new ChatSessionExtraData();
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.inversionFixture()));

        ChatSessionExtraDataSharedService storage = mock(ChatSessionExtraDataSharedService.class);
        when(storage.getBySessionIdAndDataKey(anyLong(), anyString())).thenAnswer(invocation ->
                ChatSessionExtraDataConstants.PLANNING_STATE_KEY.equals(invocation.getArgument(1))
                        ? row : null);
        when(storage.updateDataValueIfUnchanged(any(ChatSessionExtraData.class), any(), anyString()))
                .thenAnswer(invocation -> {
                    ChatSessionExtraData entity = invocation.getArgument(0);
                    entity.setDataValue(invocation.getArgument(2));
                    return true;
                });

        PendingConfirmationBizService pending = mock(PendingConfirmationBizService.class);
        when(pending.upsert(anyLong(), any(PendingConfirmationUpsertReq.class))).thenAnswer(invocation -> {
            PendingConfirmationUpsertReq req = invocation.getArgument(1);
            PendingConfirmationRes res = new PendingConfirmationRes();
            res.setPendingId(req.getPendingId());
            res.setRevision(1L);
            res.setStatus("active");
            res.setDataValue(req.getDataValue());
            activePending = res;
            return res;
        });
        when(pending.getActiveOrApplying(anyLong(), anyLong())).thenAnswer(invocation -> activePending);

        service = new PlanningStateService();
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", storage);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pending);
        ReflectionTestUtils.setField(service, "conversationProposalRequestService", inMemoryPrepareService());
    }

    @AfterEach
    void tearDown() {
        System.clearProperty(ReviewFixCommandFlags.PROPERTY);
        System.clearProperty(ReviewFixSearchFlags.PROPERTY);
        System.clearProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY);
    }

    @Test
    void appliesTheFrozenOrderExactlyWithoutReSortingOrRegenerating() {
        prepare();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        assertNotNull(res.getProposal());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals("ordered", applied.getPhase());
        assertEquals(Lists.newArrayList("low", "mid", "high"), orderedIds(applied));
        for (int index = 0; index < 3; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        // 冻结的工作草案副本也必须原样写回（倒挂修复只改顺序）。
        assertEquals(Lists.newArrayList("high", "mid", "low"), applied.getWorkingPlanState().getItems()
                .stream().map(item -> item.getVolunteerId()).collect(Collectors.toList()));
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Lists.newArrayList("low", "mid", "high"), orderedIds(saved));
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void appliesTheFrozenGroupUnitOrderExactlyAndReplaysUnitsAndItems() {
        useGroupFixture();
        prepareGroup();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"), orderedUnitIds(applied));
        assertEquals(Lists.newArrayList("u-low-v", "u-mid-v", "u-high-v"), orderedIds(applied));
        for (int index = 0; index < 3; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        // 工作草案按冻结副本原样回放：倒挂修复只改排序态。
        assertEquals(Lists.newArrayList("u-high", "u-mid", "u-low"),
                applied.getWorkingPlanState().getUnits().stream()
                        .map(DraftUnitDTO::getUnitId).collect(Collectors.toList()));
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"), orderedUnitIds(saved));
        assertEquals(Lists.newArrayList("u-low-v", "u-mid-v", "u-high-v"), orderedIds(saved));
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void groupTamperedPreviewDigestIsRejectedBeforeAnyWrite() {
        useGroupFixture();
        prepareGroup();
        FixProposalApplyReq req = applyRequest();
        req.setPreviewDigest("tampered-group");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupPlanDriftAfterPrepareIsRejectedAsStale() {
        useGroupFixture();
        prepareGroup();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getUnits().get(0).setUnitId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupCandidateFactDriftIsRejectedAsFactsChanged() {
        useGroupFixture();
        prepareGroup();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getCandidatePoolState().getItems().get(0).setAdmissionRatio(85D);
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_facts_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupPostconditionFailureRollsBackWithoutWriting() {
        useGroupFixture();
        prepareGroup();
        // 保持 unit 身份与顺序不变（事实摘要仍一致），只把单元录取率改回倒挂：
        // 重放后 probability_inversion 仍 fail，写前校验必须回滚。
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        JSONArray units = frozen.getJSONObject("orderedPlan").getJSONArray("units");
        double[] invertedByPosition = {90D, 60D, 30D};
        for (int index = 0; index < units.size(); index++) {
            JSONObject unit = units.getJSONObject(index);
            unit.put("admissionRatio", invertedByPosition[index]);
            unit.put("schoolEnrollRatio", invertedByPosition[index]);
        }
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    @Test
    void appliesFrozenGroupCountTargetFillAndReplaysFortySixUnits() {
        useGroupCountTargetFixture();
        prepareGroupCountTarget();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(46, applied.getOrderedPlanState().getUnits().size());
        assertEquals(92, applied.getOrderedPlanState().getItems().size());
        assertEquals(46, applied.getWorkingPlanState().getUnits().size());
        assertEquals(92, applied.getWorkingPlanState().getItems().size());
        for (int index = 0; index < 46; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
        }
        for (int index = 0; index < 92; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(46, saved.getOrderedPlanState().getUnits().size());
        assertEquals(92, saved.getOrderedPlanState().getItems().size());
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void groupCountTargetTamperedPreviewDigestIsRejectedBeforeAnyWrite() {
        useGroupCountTargetFixture();
        prepareGroupCountTarget();
        FixProposalApplyReq req = applyRequest();
        req.setPreviewDigest("tampered-group-count");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupCountTargetPlanDriftAfterPrepareIsRejectedAsStale() {
        useGroupCountTargetFixture();
        prepareGroupCountTarget();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getUnits().get(0).setUnitId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    private void useGroupCountTargetFixture() {
        row.setDataValue(JSON.toJSONString(
                PlanningStateServiceReviewFixPrepareTest.groupCountTargetFixture()));
    }

    private void prepareGroupCountTarget() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "count_target".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group count_target fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-count-apply", "digest-group-count-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private void useGroupFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.groupInversionFixture()));
    }

    private void prepareGroup() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "probability_inversion".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group fixture 必须产出 Direct 倒挂提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-apply", "digest-group-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    @Test
    void tamperedPreviewDigestIsRejectedBeforeAnyWrite() {
        prepare();
        FixProposalApplyReq req = applyRequest();
        req.setPreviewDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void planDriftAfterPrepareIsRejectedAsStale() {
        prepare();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
    }

    @Test
    void candidateFactDriftIsRejectedAsFactsChanged() {
        prepare();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getCandidatePoolState().getItems().get(0).setAdmissionRatio(12D);
        row.setDataValue(JSON.toJSONString(drifted));

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_facts_changed", ex.getMessage());
    }

    @Test
    void failedOriginalProbePostconditionRollsBackWithoutWriting() {
        prepare();
        // 把冻结顺序改回倒挂顺序（摘要仍与 pending/当前方案一致），后置校验必须失败。
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        JSONArray items = frozen.getJSONObject("orderedPlan").getJSONArray("items");
        JSONArray inverted = new JSONArray();
        for (String identity : Lists.newArrayList("high", "mid", "low")) {
            for (int index = 0; index < items.size(); index++) {
                JSONObject item = items.getJSONObject(index);
                if (identity.equals(item.getString("volunteerId"))) {
                    item.put("position", inverted.size() + 1);
                    inverted.add(item);
                }
            }
        }
        frozen.getJSONObject("orderedPlan").put("items", inverted);
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    @Test
    void directApplyWithoutFrozenPendingRequiresPrepare() {
        prepare();
        FixProposalApplyReq req = applyRequest();
        activePending = null;

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_requires_pending", ex.getMessage());
    }

    @Test
    void appliesTheFrozenCountTargetFillAndReplaysEightyTwoEntries() {
        useCountTargetFixture();
        prepareCountTarget();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(82, applied.getWorkingPlanState().getItems().size());
        assertEquals(82, applied.getOrderedPlanState().getItems().size());
        assertEquals(82, orderedIds(applied).stream().distinct().count());
        long added = applied.getOrderedPlanState().getItems().stream()
                .filter(item -> "review_fix".equals(item.getSource())).count();
        assertEquals(2, added, "只补入缺口 2 条，合规存量原样保留");
        assertEquals(Integer.valueOf(82), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "count_target 回放不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(82, orderedIds(saved).size());
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void searchFlagOffRejectsFrozenSearchApplyBeforeAnyWrite() {
        useCountTargetFixture();
        prepareCountTarget();
        String baseline = row.getDataValue();
        System.clearProperty(ReviewFixSearchFlags.PROPERTY);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_search_disabled", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void searchStrategyAllowlistRejectsFrozenProposalOutsideAllowlist() {
        useGroupSafetyFixture();
        prepareGroupSafety();
        String baseline = row.getDataValue();
        System.setProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY, "ratio");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_search_disabled", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
        System.clearProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY);
    }

    @Test
    void countTargetTamperedCommandDigestIsRejectedBeforeAnyWrite() {
        useCountTargetFixture();
        prepareCountTarget();
        FixProposalApplyReq req = applyRequest();
        req.setCommandDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void countTargetPlanDriftAfterPrepareIsRejectedAsStale() {
        useCountTargetFixture();
        prepareCountTarget();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void countTargetPostconditionFailureRollsBackWithoutWriting() {
        useCountTargetFixture();
        prepareCountTarget();
        // 把冻结结果缩回 80 条：重放后 count_target 仍然 fail，写前校验必须回滚。
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        trimTo(frozen.getJSONObject("workingPlan").getJSONArray("items"), 80);
        trimTo(frozen.getJSONObject("orderedPlan").getJSONArray("items"), 80);
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    @Test
    void appliesTheFrozenCoverageFillAndReplaysEightyEntries() {
        useCoverageFixture();
        prepareCoverage();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(80, applied.getWorkingPlanState().getItems().size());
        assertEquals(80, applied.getOrderedPlanState().getItems().size());
        assertEquals(80, orderedIds(applied).stream().distinct().count());
        assertTrue(coverageMatched(applied) >= 20, "回放后必须满足浙江覆盖下限");
        long added = applied.getOrderedPlanState().getItems().stream()
                .filter(item -> "review_fix".equals(item.getSource())).count();
        assertTrue(added >= 10, "至少补入 10 条浙江以达成覆盖要求");
        assertEquals(Integer.valueOf(20), applied.getConstraintState().getHardPlanningObjectives()
                        .getCoverageRequirements().get(0).getMinCount(),
                "coverage 回放不修改已确认覆盖要求");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(80, orderedIds(saved).size());
        assertTrue(coverageMatched(saved) >= 20);
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void coverageTamperedCommandDigestIsRejectedBeforeAnyWrite() {
        useCoverageFixture();
        prepareCoverage();
        FixProposalApplyReq req = applyRequest();
        req.setCommandDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void coveragePlanDriftAfterPrepareIsRejectedAsStale() {
        useCoverageFixture();
        prepareCoverage();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void appliesTheFrozenSafetyFillAndReplaysEightyEntriesWithLocalProtect() {
        useSafetyFixture();
        prepareSafety();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(80, applied.getWorkingPlanState().getItems().size());
        assertEquals(80, applied.getOrderedPlanState().getItems().size());
        assertEquals(80, orderedIds(applied).stream().distinct().count());
        assertTrue(localProtectCount(applied) >= 2, "回放后必须满足本省保底下限");
        assertEquals(Integer.valueOf(80), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "safety 回放不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(80, orderedIds(saved).size());
        assertTrue(localProtectCount(saved) >= 2);
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void safetyTamperedCommandDigestIsRejectedBeforeAnyWrite() {
        useSafetyFixture();
        prepareSafety();
        FixProposalApplyReq req = applyRequest();
        req.setCommandDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void safetyPlanDriftAfterPrepareIsRejectedAsStale() {
        useSafetyFixture();
        prepareSafety();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void safetyPostconditionFailureRollsBackWithoutWriting() {
        useSafetyFixture();
        prepareSafety();
        // 把冻结方案里的本省保底条目换成被移出的非浙江条目：摘要仍与 pending/当前方案
        // 一致，但重放后 safety_guard 仍然 fail，写前校验必须回滚。
        JSONObject frozenProposal = (JSONObject) activePending.getDataValue().get("frozenProposal");
        JSONObject solverResult = frozenProposal.getJSONObject("solverResult");
        JSONArray added = solverResult.getJSONArray("addEntityIds");
        JSONArray removed = solverResult.getJSONArray("removeEntityIds");
        assertTrue(added != null && removed != null && added.size() == removed.size());
        Map<String, String> swap = new LinkedHashMap<>();
        for (int index = 0; index < added.size(); index++) {
            swap.put(added.getString(index), removed.getString(index));
        }
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        replaceIds(frozen.getJSONObject("workingPlan").getJSONArray("items"), swap);
        replaceIds(frozen.getJSONObject("orderedPlan").getJSONArray("items"), swap);
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    @Test
    void appliesFrozenGroupSafetyAndReplaysFortyFourUnitsWithTwoLocalProtect() {
        useGroupSafetyFixture();
        prepareGroupSafety();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(44, applied.getWorkingPlanState().getUnits().size());
        assertEquals(44, applied.getOrderedPlanState().getUnits().size());
        assertEquals(88, applied.getWorkingPlanState().getItems().size());
        assertEquals(88, applied.getOrderedPlanState().getItems().size());
        assertEquals(44, orderedUnitIds(applied).stream().distinct().count());
        assertTrue(localProtectUnitCount(applied) >= 2, "回放后必须满足本省保底 2 组");
        for (int index = 0; index < 44; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
        }
        for (int index = 0; index < 88; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        assertEquals(Integer.valueOf(44), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "safety 回放不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(44, saved.getOrderedPlanState().getUnits().size());
        assertEquals(88, saved.getOrderedPlanState().getItems().size());
        assertTrue(localProtectUnitCount(saved) >= 2);
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void groupSafetyTamperedPreviewDigestIsRejectedBeforeAnyWrite() {
        useGroupSafetyFixture();
        prepareGroupSafety();
        FixProposalApplyReq req = applyRequest();
        req.setPreviewDigest("tampered-group-safety");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupSafetyPlanDriftAfterPrepareIsRejectedAsStale() {
        useGroupSafetyFixture();
        prepareGroupSafety();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getUnits().get(0).setUnitId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void appliesFrozenGroupCoverageReplacementAtSameUnitCount() {
        useGroupCoverageFixture();
        prepareGroupCoverage();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(4, applied.getWorkingPlanState().getUnits().size());
        assertEquals(4, applied.getOrderedPlanState().getUnits().size());
        assertEquals(4, applied.getWorkingPlanState().getItems().size());
        assertEquals(4, applied.getOrderedPlanState().getItems().size());
        long local = applied.getOrderedPlanState().getUnits().stream()
                .filter(unit -> "浙江".equals(unit.getProvinceName()))
                .count();
        assertEquals(2, local, "回放后必须补齐浙江覆盖 2 组");
        for (int index = 0; index < 4; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
        }
        assertEquals(Integer.valueOf(4), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "coverage 回放不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(4, saved.getOrderedPlanState().getUnits().size());
        assertEquals(2, saved.getOrderedPlanState().getUnits().stream()
                .filter(unit -> "浙江".equals(unit.getProvinceName())).count());
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void appliesFrozenGroupRiskReplacementAndRemovesRiskyUnit() {
        useGroupRiskFixture();
        prepareGroupRisk();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(4, applied.getWorkingPlanState().getUnits().size());
        assertEquals(4, applied.getOrderedPlanState().getUnits().size());
        assertEquals(4, applied.getWorkingPlanState().getItems().size());
        assertEquals(4, applied.getOrderedPlanState().getItems().size());
        assertEquals(4, orderedUnitIds(applied).stream().distinct().count());
        assertFalse(orderedUnitIds(applied).contains("u001"), "高风险组必须被移出");
        for (int index = 0; index < 4; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        Map<String, Integer> tuitionById = new LinkedHashMap<String, Integer>();
        for (CandidateItemDTO candidate : applied.getCandidatePoolState().getItems()) {
            tuitionById.put(candidate.getVolunteerId(), candidate.getTuitionPerYear());
        }
        for (OrderedItemDTO item : applied.getOrderedPlanState().getItems()) {
            assertTrue(tuitionById.get(item.getVolunteerId()) <= 20000,
                    "回放后不得保留高收费条目");
        }
        assertEquals(Integer.valueOf(4), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "风险替换不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(4, saved.getOrderedPlanState().getUnits().size());
        assertFalse(orderedUnitIds(saved).contains("u001"));
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void groupRiskPlanDriftAfterPrepareIsRejectedAsStale() {
        useGroupRiskFixture();
        prepareGroupRisk();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getUnits().get(0).setUnitId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void appliesFrozenGroupRatioAndReplaysFortyFourUnitsAt22AndElevenEleven() {
        useGroupRatioFixture();
        prepareGroupRatio();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(44, applied.getWorkingPlanState().getUnits().size());
        assertEquals(44, applied.getOrderedPlanState().getUnits().size());
        assertEquals(88, applied.getWorkingPlanState().getItems().size());
        assertEquals(88, applied.getOrderedPlanState().getItems().size());
        assertEquals(44, orderedUnitIds(applied).stream().distinct().count());
        assertEquals(22, orderedUnitTierCount(applied, "sprint"));
        assertEquals(11, orderedUnitTierCount(applied, "stable"));
        assertEquals(11, orderedUnitTierCount(applied, "protect"));
        assertTrue(localProtectUnitCount(applied) >= 2, "回放后必须满足本省保底 2 组");
        for (int index = 0; index < 44; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getUnits().get(index).getPosition());
        }
        for (int index = 0; index < 88; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    applied.getOrderedPlanState().getItems().get(index).getPosition());
        }
        assertEquals(Integer.valueOf(44), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "ratio 回放不修改已确认目标数");
        assertEquals(Integer.valueOf(22), applied.getConstraintState()
                .getHardPlanningObjectives().getTierQuotaGoal().getSprintCount(),
                "ratio 回放不修改已确认配额");
        assertEquals(Integer.valueOf(11), applied.getConstraintState()
                .getHardPlanningObjectives().getTierQuotaGoal().getStableCount());
        assertEquals(Integer.valueOf(11), applied.getConstraintState()
                .getHardPlanningObjectives().getTierQuotaGoal().getProtectCount());
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(44, saved.getOrderedPlanState().getUnits().size());
        assertEquals(88, saved.getOrderedPlanState().getItems().size());
        assertEquals(22, orderedUnitTierCount(saved, "sprint"));
        assertEquals(11, orderedUnitTierCount(saved, "stable"));
        assertEquals(11, orderedUnitTierCount(saved, "protect"));
        assertTrue(localProtectUnitCount(saved) >= 2);
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void groupRatioTamperedPreviewDigestIsRejectedBeforeAnyWrite() {
        useGroupRatioFixture();
        prepareGroupRatio();
        FixProposalApplyReq req = applyRequest();
        req.setPreviewDigest("tampered-group-ratio");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void groupRatioPlanDriftAfterPrepareIsRejectedAsStale() {
        useGroupRatioFixture();
        prepareGroupRatio();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getUnits().get(0).setUnitId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void appliesTheFrozenRatioRebalanceAndReplaysEightyEntries() {
        useRatioFixture();
        prepareRatio();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(80, applied.getWorkingPlanState().getItems().size());
        assertEquals(80, applied.getOrderedPlanState().getItems().size());
        assertEquals(80, orderedIds(applied).stream().distinct().count());
        assertEquals(40, orderedTierCount(applied, "sprint"));
        assertEquals(20, orderedTierCount(applied, "stable"));
        assertEquals(20, orderedTierCount(applied, "protect"));
        assertEquals(Integer.valueOf(80), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "ratio 回放不修改已确认目标数");
        assertEquals(Integer.valueOf(40), applied.getConstraintState()
                .getHardPlanningObjectives().getTierQuotaGoal().getSprintCount(),
                "ratio 回放不修改已确认配额");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(80, orderedIds(saved).size());
        assertEquals(40, orderedTierCount(saved, "sprint"));
        assertEquals(20, orderedTierCount(saved, "stable"));
        assertEquals(20, orderedTierCount(saved, "protect"));
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void ratioTamperedCommandDigestIsRejectedBeforeAnyWrite() {
        useRatioFixture();
        prepareRatio();
        FixProposalApplyReq req = applyRequest();
        req.setCommandDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void ratioPlanDriftAfterPrepareIsRejectedAsStale() {
        useRatioFixture();
        prepareRatio();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void ratioPostconditionFailureRollsBackWithoutWriting() {
        useRatioFixture();
        prepareRatio();
        // 把冻结方案的全部条目改回冲档：摘要仍与 pending/当前方案一致，
        // 但重放后 ratio_distribution 仍然 fail，写前校验必须回滚。
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        forceTier(frozen.getJSONObject("orderedPlan").getJSONArray("items"), "sprint");
        forceTier(frozen.getJSONObject("workingPlan").getJSONArray("items"), "sprint");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    @Test
    void appliesTheFrozenRiskReplacementAndRemovesForcedTarget() {
        useRiskFixture();
        prepareRisk();

        FixProposalApplyRes res = service.applyFixProposal(TENANT, SESSION, applyRequest());

        assertEquals("applied", res.getStatus());
        PlanningStateDTO applied = res.getState();
        assertEquals(Integer.valueOf(8), applied.getVersion(), "只 bump 一次版本");
        assertEquals(80, applied.getWorkingPlanState().getItems().size());
        assertEquals(80, applied.getOrderedPlanState().getItems().size());
        assertEquals(80, orderedIds(applied).stream().distinct().count());
        assertFalse(orderedIds(applied).contains("v001"), "回放后必须移出高收费条目");
        assertTrue(orderedIds(applied).contains("v081"), "回放后必须补入低学费替代");
        assertEquals(Integer.valueOf(80), applied.getConstraintState()
                .getHardPlanningObjectives().getSelectionTargetCount(),
                "risk 回放不修改已确认目标数");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(80, orderedIds(saved).size());
        assertFalse(orderedIds(saved).contains("v001"));
        assertEquals(Integer.valueOf(8), saved.getVersion());
    }

    @Test
    void riskTamperedCommandDigestIsRejectedBeforeAnyWrite() {
        useRiskFixture();
        prepareRisk();
        FixProposalApplyReq req = applyRequest();
        req.setCommandDigest("tampered");
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, req));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_changed", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void riskPlanDriftAfterPrepareIsRejectedAsStale() {
        useRiskFixture();
        prepareRisk();
        PlanningStateDTO drifted = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        drifted.getOrderedPlanState().getItems().get(0).setVolunteerId("changed");
        row.setDataValue(JSON.toJSONString(drifted));
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(409, ex.getStatus());
        assertEquals("review_fix_stale", ex.getMessage());
        assertEquals(baseline, row.getDataValue());
    }

    @Test
    void riskPostconditionFailureRollsBackWithoutWriting() {
        useRiskFixture();
        prepareRisk();
        // 把冻结方案里的低学费替代换回被移出的高收费条目：摘要仍与 pending/当前方案
        // 一致，但重放后 high_tuition 仍然 fail，写前校验必须回滚。
        JSONObject frozenProposal = (JSONObject) activePending.getDataValue().get("frozenProposal");
        JSONObject solverResult = frozenProposal.getJSONObject("solverResult");
        JSONArray added = solverResult.getJSONArray("addEntityIds");
        JSONArray removed = solverResult.getJSONArray("removeEntityIds");
        assertTrue(added != null && added.size() > 0 && removed != null && removed.size() > 0);
        String risky = removed.getString(0);
        JSONObject frozen = (JSONObject) activePending.getDataValue().get("frozenReviewPlan");
        replaceId(frozen.getJSONObject("workingPlan").getJSONArray("items"), added.getString(0), risky);
        replaceId(frozen.getJSONObject("orderedPlan").getJSONArray("items"), added.getString(0), risky);
        String baseline = row.getDataValue();

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.applyFixProposal(TENANT, SESSION, applyRequest()));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, ex.getStatus());
        assertEquals("review_fix_postcondition_failed", ex.getMessage());
        assertEquals(baseline, row.getDataValue(), "后置失败必须回滚，不得留下半套方案");
        PlanningStateDTO saved = JSON.parseObject(row.getDataValue(), PlanningStateDTO.class);
        assertEquals(Integer.valueOf(7), saved.getVersion());
    }

    private static void replaceId(JSONArray items, String from, String to) {
        for (int index = 0; index < items.size(); index++) {
            JSONObject item = items.getJSONObject(index);
            if (from.equals(item.getString("volunteerId"))) {
                item.put("volunteerId", to);
            }
        }
    }

    private void useRiskFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.riskReplaceFixture()));
    }

    private void prepareRisk() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "high_tuition".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "risk fixture 必须产出 RiskReplace 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-risk-apply", "digest-risk-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static void forceTier(JSONArray items, String tier) {
        for (int index = 0; index < items.size(); index++) {
            items.getJSONObject(index).put("tier", tier);
        }
    }

    private void useRatioFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.ratioFixture()));
    }

    private void prepareRatio() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "ratio_distribution".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "ratio fixture 必须产出 Ratio 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-ratio-apply", "digest-ratio-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static long orderedTierCount(PlanningStateDTO state, String tier) {
        return state.getOrderedPlanState().getItems().stream()
                .filter(item -> tier.equals(item.getTier()))
                .count();
    }

    private static void replaceIds(JSONArray items, Map<String, String> swap) {
        for (int index = 0; index < items.size(); index++) {
            JSONObject item = items.getJSONObject(index);
            String replacement = swap.get(item.getString("volunteerId"));
            if (replacement != null) {
                item.put("volunteerId", replacement);
            }
        }
    }

    private void useSafetyFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.safetyFixture()));
    }

    private void useGroupSafetyFixture() {
        row.setDataValue(JSON.toJSONString(
                PlanningStateServiceReviewFixPrepareTest.groupSafetyFixture()));
    }

    private void prepareGroupSafety() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "safety_guard".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group safety fixture 必须产出 Safety 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-safety-apply", "digest-group-safety-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private void useGroupCoverageFixture() {
        row.setDataValue(JSON.toJSONString(
                PlanningStateServiceReviewFixPrepareTest.groupCoverageFixture()));
    }

    private void prepareGroupCoverage() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "coverage:0".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group coverage fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-coverage-apply", "digest-group-coverage-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private void useGroupRiskFixture() {
        row.setDataValue(JSON.toJSONString(
                PlanningStateServiceReviewFixPrepareTest.groupRiskFixture()));
    }

    private void prepareGroupRisk() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "high_tuition".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group risk fixture 必须产出 RiskReplace 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-risk-apply", "digest-group-risk-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private void useGroupRatioFixture() {
        row.setDataValue(JSON.toJSONString(
                PlanningStateServiceReviewFixPrepareTest.groupRatioFixture()));
    }

    private void prepareGroupRatio() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "ratio_distribution".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "group ratio fixture 必须产出 Ratio 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-group-ratio-apply", "digest-group-ratio-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static long orderedUnitTierCount(PlanningStateDTO state, String tier) {
        return state.getOrderedPlanState().getUnits().stream()
                .filter(unit -> tier.equals(unit.getTier()))
                .count();
    }

    private static long localProtectUnitCount(PlanningStateDTO state) {
        return state.getOrderedPlanState().getUnits().stream()
                .filter(unit -> "protect".equals(unit.getTier())
                        && "江西".equals(unit.getProvinceName()))
                .count();
    }

    private void prepareSafety() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "safety_guard".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "safety fixture 必须产出 Safety 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-safety-apply", "digest-safety-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static long localProtectCount(PlanningStateDTO state) {
        Map<String, String> provinceById = new LinkedHashMap<>();
        Map<String, String> tierById = new LinkedHashMap<>();
        for (CandidateItemDTO candidate : state.getCandidatePoolState().getItems()) {
            if (candidate != null) {
                provinceById.put(candidate.getVolunteerId(), candidate.getProvinceName());
                tierById.put(candidate.getVolunteerId(), candidate.getTier());
            }
        }
        return state.getOrderedPlanState().getItems().stream()
                .filter(item -> "浙江".equals(provinceById.get(item.getVolunteerId()))
                        && "protect".equals(tierById.get(item.getVolunteerId())))
                .count();
    }

    private void useCoverageFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.coverageFixture()));
    }

    private void prepareCoverage() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "coverage:0".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "coverage fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-coverage-apply", "digest-coverage-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static long coverageMatched(PlanningStateDTO state) {
        Map<String, String> provinceById = new LinkedHashMap<String, String>();
        for (CandidateItemDTO candidate : state.getCandidatePoolState().getItems()) {
            if (candidate != null) {
                provinceById.put(candidate.getVolunteerId(), candidate.getProvinceName());
            }
        }
        return state.getOrderedPlanState().getItems().stream()
                .map(item -> provinceById.get(item.getVolunteerId()))
                .filter("浙江"::equals)
                .count();
    }

    private void useCountTargetFixture() {
        row.setDataValue(JSON.toJSONString(PlanningStateServiceReviewFixPrepareTest.countTargetFixture()));
    }

    private void prepareCountTarget() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = null;
        for (FixProposalDTO candidate : preview.getProposals()) {
            if (candidate != null && "count_target".equals(candidate.getFindingCode())) {
                proposal = candidate;
                break;
            }
        }
        assertNotNull(proposal, "count_target fixture 必须产出 Search 提案");
        assertEquals("ready", proposal.getStatus());
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-count-apply", "digest-count-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private static void trimTo(JSONArray items, int size) {
        while (items.size() > size) {
            items.remove(items.size() - 1);
        }
        for (int index = 0; index < items.size(); index++) {
            items.getJSONObject(index).put("position", index + 1);
        }
    }

    private void prepare() {
        ReviewFixPreviewDTO preview = service.previewReviewFixProposals(TENANT, SESSION);
        FixProposalDTO proposal = preview.getProposals().get(0);
        ReviewFixPrepareReq req = new ReviewFixPrepareReq();
        req.setProposalId(proposal.getProposalId());
        req.setPreviewDigest(proposal.getPreviewDigest());
        req.setCommandDigest(proposal.getCommandDigest());
        req.setEvaluationVersion(proposal.getEvaluationVersion());
        req.setSourceVersionGuard(preview.getSourceVersion());
        PrepareResultDTO prepared = service.prepareReviewFixProposal(
                TENANT, SESSION, "req-apply", "digest-apply", req);
        assertNotNull(prepared.getPendingId());
        assertNotNull(activePending);
    }

    private FixProposalApplyReq applyRequest() {
        Map<String, Object> data = activePending.getDataValue();
        FixProposalApplyReq req = new FixProposalApplyReq();
        req.setProposalId(String.valueOf(data.get("proposalId")));
        req.setCommandDigest(String.valueOf(data.get("commandDigest")));
        req.setPreviewDigest(String.valueOf(data.get("previewDigest")));
        req.setEvaluationVersion(String.valueOf(data.get("evaluationVersion")));
        req.setSourceVersionGuard(7);
        req.setRegenerateOrderedPlan(true);
        req.setRerunReview(true);
        return req;
    }

    private static java.util.List<String> orderedIds(PlanningStateDTO state) {
        return state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList());
    }

    private static java.util.List<String> orderedUnitIds(PlanningStateDTO state) {
        return state.getOrderedPlanState().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList());
    }

    private ConversationProposalRequestService inMemoryPrepareService() {
        ConversationProposalRequestService prepareService = new ConversationProposalRequestService() {
            @Override
            public ConversationProposalRequestEntity find(Long tenantId, Long chatSessionId, String requestId) {
                return requestTable.get(tenantId + ":" + chatSessionId + ":" + requestId);
            }

            @Override
            protected int supersedeSiblings(Long tenantId, Long chatSessionId, String requestId) {
                return 0;
            }
        };
        ConversationProposalRequestMapper mapper = mock(ConversationProposalRequestMapper.class);
        when(mapper.insert(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity entity = invocation.getArgument(0);
            String key = entity.getTenantId() + ":" + entity.getChatSessionId() + ":" + entity.getRequestId();
            if (requestTable.containsKey(key)) {
                throw new DuplicateKeyException("uk_conversation_proposal_request");
            }
            entity.setId((long) requestIdSeq.incrementAndGet());
            requestTable.put(key, entity);
            return 1;
        });
        when(mapper.updateById(any(ConversationProposalRequestEntity.class))).thenAnswer(invocation -> {
            ConversationProposalRequestEntity entity = invocation.getArgument(0);
            requestTable.put(entity.getTenantId() + ":" + entity.getChatSessionId() + ":" + entity.getRequestId(),
                    entity);
            return 1;
        });
        when(mapper.deleteById(any(java.io.Serializable.class))).thenReturn(1);
        ReflectionTestUtils.setField(prepareService, "requestMapper", mapper);
        return prepareService;
    }
}
