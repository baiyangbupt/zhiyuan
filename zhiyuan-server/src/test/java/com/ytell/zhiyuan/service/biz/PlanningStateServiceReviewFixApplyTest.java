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
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
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
