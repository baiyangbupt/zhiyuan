package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * P2 写闭环第一段：`prepareUserGoalProposal` 必须把 **Java 产出的 operationId** 落进
 * pending 的 dataValue（确认时由快照带出来、execute 段读它当幂等键）；
 * 而**没有可确认动作**（requiresConfirmation=false，如 blocked）的预览**不得物化**成 active pending
 * （2026-10-07 review §五-7/11：物化后快照会把 blocked 卡报成"可确认"，用户确认必然失败）。
 *
 * <p>风格与 `ConversationProposalRequestServiceTest` 一致：**替换存储与编译**（那两条路各自有测试），
 * 让真实的服务逻辑跑起来——被 mock 掉的正是"状态怎么走"这件事本身。
 *
 * <p>为什么这条值得单独测：真栈上"operationId 没落进 pending"不是编译期能发现的 ✗
 * （第七轮 E2E 才逼出来），而它一旦缺，链路的 execute 会按 fail-closed 拒绝执行。
 */
public class PlanningStateServicePrepareProposalTest {

    private PlanningStateService service;
    private final List<Map<String, Object>> upsertedValues = new ArrayList<>();
    private final List<PendingConfirmationUpsertReq> upsertedRequests = new ArrayList<>();
    private PendingConfirmationBizService recordingPendingService;

    @BeforeEach
    void setUp() {
        // 存储层：只记下 upsert 的 dataValue，并回一个带 pendingId 的响应。
        recordingPendingService = new PendingConfirmationBizService() {
            @Override
            public PendingConfirmationRes getCurrent(Long tenantId, Long chatSessionId) {
                return null;
            }

            @Override
            public PendingConfirmationRes upsert(Long tenantId, PendingConfirmationUpsertReq req) {
                upsertedValues.add(req.getDataValue());
                upsertedRequests.add(req);
                PendingConfirmationRes res = new PendingConfirmationRes();
                res.setPendingId(req.getPendingId());
                res.setRevision(1L);
                res.setStatus("active");
                return res;
            }
        };
        // 编译那一步（读库、建预览）替换成罐头——它不参与本测试要验的东西。
        FixProposalStateDTO preview = new FixProposalStateDTO();
        preview.setSourceVersion(7);
        FixProposalDTO ready = new FixProposalDTO();
        ready.setProposalId("ugp_test_1");
        ready.setStatus("ready");
        FixProposalDTO draft = new FixProposalDTO();
        draft.setProposalId("ugp_draft");
        draft.setStatus("preview_only");
        preview.setProposals(Lists.newArrayList(draft, ready));
        service = serviceWithPreview(preview);
    }

    @Test
    void prepareLandsTheOperationIdAndTheUserGoalIntoThePending() {
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");

        PrepareResultDTO dto = service.prepareUserGoalProposal(1L, 2L, "req-1", "digest-1", req);

        assertEquals(1, upsertedValues.size(), "一次 prepare 只落一个 pending");
        Map<String, Object> data = upsertedValues.get(0);

        Object operationId = data.get("operationId");
        assertNotNull(operationId, "operationId 必须落库——execute 段拿不到就 fail-closed 拒执行");
        assertEquals(32, String.valueOf(operationId).length(), "无横线的 uuid（与 legacy 同约定）");
        assertEquals(dto.getOperationId(), operationId, "返回给调用方的与落库的必须是同一个");
        assertNotNull(dto.getPendingId());
        assertFalse(String.valueOf(dto.getPendingId()).isEmpty());

        assertEquals("user_goal", data.get("proposalSource"));
        assertEquals(7, data.get("sourceVersion"));
        // 主提案取第一个 ready 的（列表里第一条是 preview_only，不能被选中）。
        assertEquals("ugp_test_1", data.get("proposalId"));
        // apply 那条路要求 user_goal 提案带原始目标（"user_goal proposal requires userGoalRequest"）。
        assertTrue(data.get("userGoalRequest") instanceof Map,
                "userGoalRequest 必须落库：apply 时要用它，缺了会被 40001 拒");
    }

    @Test
    void prepareDoesNotMaterializeBlockedProposalAsActivePending() {
        FixProposalStateDTO blockedPreview = new FixProposalStateDTO();
        blockedPreview.setSourceVersion(7);
        FixProposalDTO blocked = new FixProposalDTO();
        blocked.setProposalId("ugp_blocked_1");
        blocked.setStatus("blocked");
        blocked.setRequiresConfirmation(false);
        blocked.setBlockingReason("priority_target_not_in_plan: 当前方案没有命中优先目标");
        blockedPreview.setProposals(Lists.newArrayList(blocked));
        PlanningStateService blockedService = serviceWithPreview(blockedPreview);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        PrepareResultDTO dto = blockedService.prepareUserGoalProposal(1L, 2L, "req-blocked", "digest-blocked", req);

        assertEquals(0, upsertedValues.size(),
                "blocked 预览（requiresConfirmation=false）没有可确认动作，不得物化 active pending");
        assertNull(dto.getPendingId(), "不物化就没有 pendingId");
        assertNull(dto.getOperationId(), "不物化就没有 operationId");
        assertNotNull(dto.getResult(), "预览本身照常返回，网关照常渲染 blocked 卡");
    }

    @Test
    void prepareAddUnitsFreezesCommandAndUsesPlanActionKind() {
        FixProposalStateDTO preview = new FixProposalStateDTO();
        preview.setSourceVersion(7);
        FixProposalDTO ready = new FixProposalDTO();
        ready.setProposalId("ugp_add");
        ready.setStatus("ready");
        ready.setRequiresConfirmation(true);
        ready.setAffectedVolunteerIds(Lists.newArrayList("v2", "v3"));
        ready.setTargetCountOverride(9);
        ready.setSummary("加入 2 条");
        preview.setProposals(Lists.newArrayList(ready));
        PlanningStateService addService = serviceWithPreview(preview);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("add_units");
        UserGoalFixProposalReq.ExactTargetDTO target = new UserGoalFixProposalReq.ExactTargetDTO();
        target.setSchoolName("湖南师范大学");
        target.setMajorName("汉语言文学");
        req.getExactTargets().add(target);

        PrepareResultDTO dto = addService.prepareUserGoalProposal(1L, 2L, "req-add", "digest-add", req);

        assertNotNull(dto.getPendingId());
        Map<String, Object> data = upsertedValues.get(0);
        assertEquals("plan_action", data.get("kind"));
        assertEquals("add_units", data.get("commandType"));
        assertEquals("add_units", data.get("goalType"));
        assertEquals(Lists.newArrayList("v2", "v3"), data.get("volunteerIds"));
        assertEquals(9, data.get("targetCountOverride"));
        assertEquals(Boolean.TRUE, data.get("rerunReview"));
        assertNotNull(data.get("frozenCommand"));
        assertEquals(64, String.valueOf(data.get("commandDigest")).length());
        PendingConfirmationUpsertReq upsert = upsertedRequests.get(0);
        assertEquals("plan_action", upsert.getKind());
        assertEquals("add_units", upsert.getActionFamily());
        Map frozen = (Map) data.get("frozenCommand");
        assertEquals(dto.getOperationId(), frozen.get("operationId"));
        assertEquals(9, frozen.get("targetCountOverride"));
        assertEquals(Boolean.TRUE, frozen.get("rerunReview"));
        assertEquals(7, frozen.get("sourceVersion"));
    }

    @Test
    void prepareReplaceUnitsFreezesBothSetsAndReplaceCommandType() {
        FixProposalStateDTO preview = new FixProposalStateDTO();
        preview.setSourceVersion(7);
        FixProposalDTO ready = new FixProposalDTO();
        ready.setProposalId("ugp_replace");
        ready.setStatus("ready");
        ready.setRequiresConfirmation(true);
        ready.setAffectedVolunteerIds(Lists.newArrayList("v-add"));
        ready.setAffectedUnitIds(Lists.newArrayList("u-add"));
        ready.setSummary("换出 1 条，换入 1 条；总数保持 2");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setVolunteerIds(Lists.newArrayList("v-add"));
        action.setRemoveVolunteerIds(Lists.newArrayList("v-remove"));
        action.setRemoveUnitIds(Lists.newArrayList("u-remove"));
        ready.getActions().add(action);
        preview.setProposals(Lists.newArrayList(ready));
        PlanningStateService replaceService = serviceWithPreview(preview);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("add_units");
        req.setAddPolicy("replace");
        UserGoalFixProposalReq.ExactTargetDTO target = new UserGoalFixProposalReq.ExactTargetDTO();
        target.setSchoolName("南华大学");
        target.setMajorName("法学");
        req.getExactTargets().add(target);

        PrepareResultDTO dto = replaceService.prepareUserGoalProposal(
                1L, 2L, "req-replace", "digest-replace", req);

        assertNotNull(dto.getPendingId());
        Map<String, Object> data = upsertedValues.get(0);
        assertEquals("plan_action", data.get("kind"));
        assertEquals("replace_units", data.get("commandType"));
        assertEquals("add_units", data.get("goalType"));
        assertEquals(Lists.newArrayList("v-add"), data.get("volunteerIds"));
        assertEquals(Lists.newArrayList("v-remove"), data.get("removedVolunteerIds"));
        assertEquals(Lists.newArrayList("u-remove"), data.get("removedUnitIds"));
        assertEquals(Lists.newArrayList("u-add"), data.get("addedUnitIds"));
        assertEquals(null, data.get("targetCountOverride"));
        PendingConfirmationUpsertReq upsert = upsertedRequests.get(0);
        assertEquals("plan_action", upsert.getKind());
        assertEquals("replace_units", upsert.getActionFamily());
        Map frozen = (Map) data.get("frozenCommand");
        assertEquals("replace_units", frozen.get("commandType"));
        assertEquals(dto.getOperationId(), frozen.get("operationId"));
        assertEquals(Lists.newArrayList("v-add"), frozen.get("addedVolunteerIds"));
        assertEquals(Lists.newArrayList("v-remove"), frozen.get("removedVolunteerIds"));
        assertEquals(Lists.newArrayList("u-add"), frozen.get("addedUnitIds"));
        assertEquals(Lists.newArrayList("u-remove"), frozen.get("removedUnitIds"));
        assertEquals(null, frozen.get("targetCountOverride"));
        assertEquals(Boolean.TRUE, frozen.get("rerunReview"));
        assertEquals(64, String.valueOf(data.get("commandDigest")).length());
    }

    @Test
    void prepareRemoveUnitsFreezesTheRemoveSet() {
        FixProposalStateDTO preview = new FixProposalStateDTO();
        preview.setSourceVersion(7);
        FixProposalDTO ready = new FixProposalDTO();
        ready.setProposalId("ugp_remove");
        ready.setStatus("ready");
        ready.setRequiresConfirmation(true);
        ready.setAffectedVolunteerIds(Lists.newArrayList("v-old"));
        ready.setAffectedUnitIds(Lists.newArrayList("u-old"));
        ready.setRemovedCount(1);
        ready.setTargetCountOverride(1);
        ready.setSummary("移除 1 条；总数 2→1");
        preview.setProposals(Lists.newArrayList(ready));
        PlanningStateService removeService = serviceWithPreview(preview);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("remove_units");
        req.setSourceVersionGuard(1);
        UserGoalFixProposalReq.ExactTargetDTO target = new UserGoalFixProposalReq.ExactTargetDTO();
        target.setSchoolName("中南大学");
        target.setMajorName("临床医学");
        req.getExactTargets().add(target);

        PrepareResultDTO dto = removeService.prepareUserGoalProposal(
                1L, 2L, "req-remove", "digest-remove", req);

        assertNotNull(dto.getPendingId());
        Map<String, Object> data = upsertedValues.get(0);
        assertEquals("plan_action", data.get("kind"));
        assertEquals("remove_units", data.get("commandType"));
        assertEquals("remove_units", data.get("goalType"));
        assertEquals(Lists.newArrayList("v-old"), data.get("removedVolunteerIds"));
        assertEquals(Lists.newArrayList("u-old"), data.get("removedUnitIds"));
        assertEquals(1, data.get("targetCountOverride"));
        PendingConfirmationUpsertReq upsert = upsertedRequests.get(0);
        assertEquals("plan_action", upsert.getKind());
        assertEquals("remove_units", upsert.getActionFamily());
        Map frozen = (Map) data.get("frozenCommand");
        assertEquals("remove_units", frozen.get("commandType"));
        assertEquals(Lists.newArrayList("v-old"), frozen.get("removedVolunteerIds"));
        assertEquals(Lists.newArrayList("u-old"), frozen.get("removedUnitIds"));
        assertEquals(1, frozen.get("targetCountOverride"));
        assertEquals(Boolean.TRUE, frozen.get("rerunReview"));
        assertEquals(7, frozen.get("sourceVersion"));
    }

    @Test
    void prepareMoveUnitsFreezesTargetAndPosition() {
        FixProposalStateDTO preview = new FixProposalStateDTO();
        preview.setSourceVersion(7);
        FixProposalDTO ready = new FixProposalDTO();
        ready.setProposalId("ugp_move");
        ready.setStatus("ready");
        ready.setRequiresConfirmation(true);
        ready.setAffectedVolunteerIds(Lists.newArrayList("v-target"));
        ready.setMoveTargetVolunteerId("v-target");
        ready.setMoveFromPosition(3);
        ready.setMoveToPosition(1);
        ready.setSummary("从第 3 位移到第 1 位");
        preview.setProposals(Lists.newArrayList(ready));
        PlanningStateService moveService = serviceWithPreview(preview);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("move_units");
        req.setSourceVersionGuard(1);
        req.setMovePosition("top");
        UserGoalFixProposalReq.ExactTargetDTO target = new UserGoalFixProposalReq.ExactTargetDTO();
        target.setVolunteerId("v-target");
        req.getExactTargets().add(target);

        PrepareResultDTO dto = moveService.prepareUserGoalProposal(
                1L, 2L, "req-move", "digest-move", req);

        assertNotNull(dto.getPendingId());
        Map<String, Object> data = upsertedValues.get(0);
        assertEquals("plan_action", data.get("kind"));
        assertEquals("move_units", data.get("commandType"));
        assertEquals("move_units", data.get("goalType"));
        assertEquals("v-target", data.get("moveTargetVolunteerId"));
        assertEquals(3, data.get("fromPosition"));
        assertEquals(1, data.get("toPosition"));
        PendingConfirmationUpsertReq upsert = upsertedRequests.get(0);
        assertEquals("move_units", upsert.getActionFamily());
        Map frozen = (Map) data.get("frozenCommand");
        assertEquals("move_units", frozen.get("commandType"));
        assertEquals("v-target", frozen.get("targetVolunteerId"));
        assertEquals(1, frozen.get("targetPosition"));
        assertEquals(3, frozen.get("fromPosition"));
        assertEquals(Boolean.TRUE, frozen.get("rerunReview"));
        assertEquals(7, frozen.get("sourceVersion"));
    }

    private PlanningStateService serviceWithPreview(final FixProposalStateDTO preview) {
        PlanningStateService result = new PlanningStateService() {
            @Override
            public FixProposalStateDTO generateUserGoalFixProposals(Long chatSessionId,
                                                                   UserGoalFixProposalReq req) {
                return preview;
            }
        };
        ReflectionTestUtils.setField(result, "pendingConfirmationBizService", recordingPendingService);
        // 幂等状态机替换成"直接跑 work"——它的状态机另有测试（见类注释）。
        ReflectionTestUtils.setField(result, "conversationProposalRequestService",
                new ConversationProposalRequestService() {
                    @Override
                    public PrepareResultDTO prepareOnce(Long tenantId, Long chatSessionId, String requestId,
                                                        String requestDigest, String activePendingStatus,
                                                        PrepareWork work) {
                        ConversationProposalRequestService.PrepareOutcome outcome = work.run();
                        PrepareResultDTO dto = new PrepareResultDTO();
                        dto.setStatus("prepared");
                        dto.setRequestId(requestId);
                        dto.setPendingId(outcome.getPendingId());
                        dto.setOperationId(outcome.getOperationId());
                        dto.setResult(outcome.getResult());
                        return dto;
                    }
                });
        return result;
    }
}
