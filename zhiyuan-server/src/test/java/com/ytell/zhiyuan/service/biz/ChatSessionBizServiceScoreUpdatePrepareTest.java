package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.ScoreUpdatePreviewDTO;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * score_update 动作族的 prepare：与用户目标提案同一条状态机（幂等/取代），
 * 但落进 pending 的东西不同——**Java 产出的 operationId**（执行段 fail-closed 的
 * 幂等键）、`sourceVersion`（确认时的计划版本守门值）、`scoreUpdateRequest`
 * （执行输入）、`scoreSummary`（卡片展示）。
 *
 * <p>风格照 `PlanningStateServicePrepareProposalTest`：存储与状态机打桩，
 * 让真实的合并/校验/摘要逻辑跑起来——"摘要是不是由 Java 按合并后的成绩算的"
 * 正是这条测试要盯的事（模型文本里的复述不作数）。</p>
 */
public class ChatSessionBizServiceScoreUpdatePrepareTest {

    private ChatSessionBizService service;
    private final List<PendingConfirmationUpsertReq> upserted = new ArrayList<>();
    private PendingConfirmationRes currentPending;
    private ChatSessionExtraDataSharedService extraDataSharedService;
    private GaotuService gaotuService;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        ConversationAccessService conversationAccessService = mock(ConversationAccessService.class);
        when(conversationAccessService.requireSessionUserId(1L, 2L)).thenReturn(7L);
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);

        // 空会话：没有既有的 userScoreDetail 行（补录就是给这种会话写的）。
        extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", extraDataSharedService);
        // 位次补齐（preview 也要走，见 2026-10-07 审查 M3）用替身上游。
        gaotuService = mock(GaotuService.class);
        ReflectionTestUtils.setField(service, "gaotuService", gaotuService);

        PlanningStateService planningStateService = mock(PlanningStateService.class);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(2L);
        state.setVersion(5);
        when(planningStateService.getPlanningState(2L)).thenReturn(state);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);

        UserBizService userBizService = mock(UserBizService.class);
        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(Boolean.TRUE);
        when(userBizService.checkRights(eq(7L), eq(OperateCheckPoint.CreateSession), any()))
                .thenReturn(rights);
        ReflectionTestUtils.setField(service, "userBizService", userBizService);

        ReflectionTestUtils.setField(service, "pendingConfirmationBizService",
                new PendingConfirmationBizService() {
                    @Override
                    public PendingConfirmationRes getCurrent(Long tenantId, Long chatSessionId) {
                        return currentPending;
                    }

                    @Override
                    public PendingConfirmationRes upsert(Long tenantId, PendingConfirmationUpsertReq req) {
                        upserted.add(req);
                        PendingConfirmationRes res = new PendingConfirmationRes();
                        res.setPendingId(req.getPendingId());
                        res.setRevision(1L);
                        res.setStatus("active");
                        return res;
                    }
                });
        // 科类推导（单科类省份补全）另有测试；这里回 null = 推导不出来，保持原有校验行为。
        ReflectionTestUtils.setField(service, "scoreCatalogService", mock(ScoreCatalogService.class));
        // 幂等状态机替换成"直接跑 work"——它的状态机另有测试。
        ReflectionTestUtils.setField(service, "conversationProposalRequestService",
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
    }

    @Test
    void prepareLandsTheOperationIdVersionAndJavaComputedSummary() {
        PrepareResultDTO dto = service.prepareScoreUpdateProposal(1L, 2L, "req-1", "digest-1", scoreRequest());

        assertEquals(1, upserted.size(), "一次 prepare 只落一个 pending");
        PendingConfirmationUpsertReq upsert = upserted.get(0);
        assertEquals("score_update", upsert.getKind());
        assertEquals("update_score_detail", upsert.getActionFamily());
        assertEquals(Long.valueOf(0L), upsert.getExpectedRevision(),
                "没有既有 pending 行时按修订号 0 插入");

        Map<String, Object> data = upsert.getDataValue();
        Object operationId = data.get("operationId");
        assertNotNull(operationId, "operationId 必须落库——execute 段拿不到就 fail-closed 拒执行");
        assertEquals(32, String.valueOf(operationId).length(), "无横线的 uuid（与 legacy 同约定）");
        assertEquals(dto.getOperationId(), operationId, "返回给调用方的与落库的必须是同一个");
        assertEquals("score_update", data.get("proposalSource"));
        assertEquals(5, data.get("sourceVersion"), "确认时的计划版本守门值");
        assertTrue(data.get("scoreUpdateRequest") instanceof Map,
                "执行输入（增量草稿）要能原样透传给确认段");

        Object summaryRaw = data.get("scoreSummary");
        assertTrue(summaryRaw instanceof Map);
        Map<?, ?> summary = (Map<?, ?>) summaryRaw;
        assertEquals("浙江省", summary.get("provinceName"));
        assertEquals(621, summary.get("totalScore"));
        assertEquals(8123, summary.get("totalScorePos"));
        assertEquals("物理", summary.get("subjectType"));
        assertEquals("本科批", summary.get("batchName"));
        assertEquals(3, ((List<?>) summary.get("subjects")).size());

        // prepare 的返回值就是卡片/网关的预览源。
        assertTrue(dto.getResult() instanceof ScoreUpdatePreviewDTO);
        ScoreUpdatePreviewDTO preview = (ScoreUpdatePreviewDTO) dto.getResult();
        assertEquals("ready", preview.getStatus());
        assertEquals(Integer.valueOf(5), preview.getSourceVersion());
        assertEquals(Boolean.TRUE, preview.getRequiresConfirmation());
        assertEquals(621, preview.getSummary().get("totalScore"));
    }

    @Test
    void prepareReplacesAnExistingPendingByRevisionInsteadOfConflicting() {
        currentPending = new PendingConfirmationRes();
        currentPending.setPendingId("old-pending");
        currentPending.setRevision(3L);
        currentPending.setStatus("applied");

        service.prepareScoreUpdateProposal(1L, 2L, "req-2", "digest-2", scoreRequest());

        assertEquals(1, upserted.size());
        assertEquals(Long.valueOf(3L), upserted.get(0).getExpectedRevision(),
                "已有 pending 行时必须按当前修订号 CAS 替换（留在 0 会 40901）");
    }

    @Test
    void prepareFailsFastWith110WhenTheMergedScoreIsIncomplete() {
        CreateSessionReq incomplete = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江省");
        incomplete.setProvince(province);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.prepareScoreUpdateProposal(1L, 2L, "req-3", "digest-3", incomplete));

        assertEquals(110, error.getStatus(),
                "缺项在预览阶段就以 110 拒（与执行同码），而不是等确认后回未生效");
        assertTrue(upserted.isEmpty(), "被拒的草案不许落 pending");
    }

    @Test
    void previewReturnsTheSameSummaryShapeWithoutPersistingPending() {
        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, scoreRequest());

        assertEquals("ready", preview.getStatus());
        assertEquals(Integer.valueOf(5), preview.getSourceVersion());
        assertEquals(621, preview.getSummary().get("totalScore"));
        assertEquals(8123, preview.getSummary().get("totalScorePos"), "用户/表单给过位次就照抄，不查上游");
        assertFalse(upserted.iterator().hasNext(), "preview 不许落 pending");
        Mockito.verify(gaotuService, Mockito.never())
                .getScorePositionRange(Mockito.any(ScorePositionRangeReq.class));
        Mockito.verify(extraDataSharedService, Mockito.never()).save(Mockito.any());
        Mockito.verify(extraDataSharedService, Mockito.never()).updateById(Mockito.any());
    }

    // 2026-10-07 审查 M3：preview 的字段集必须等于执行集——位次要不要补，两边得同一个答案。
    // 修复前 preview 少走 fillTotalScorePosIfMissing：卡片上没有 totalScorePos，确认后落库却有了。
    @Test
    void previewFillsMissingPositionLikeExecutionDoes() {
        ScorePositionRangeRes range = new ScorePositionRangeRes();
        range.setHighestRank(43000);
        range.setLowestRank(43879);
        range.setStudents(880);
        when(gaotuService.getScorePositionRange(Mockito.any(ScorePositionRangeReq.class))).thenReturn(range);

        CreateSessionReq req = scoreRequest();
        req.setTotalScorePos(null);
        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, req);

        assertEquals(43879, preview.getSummary().get("totalScorePos"),
                "预览缺位次也要向上游补齐（lowestRank 保守口径），与执行段同一字段集");

        // 请求形状与执行段/前端一致：年份是钉住的 examYear，不是"查不到就换当年"（审查 M2）。
        ArgumentCaptor<ScorePositionRangeReq> captor = ArgumentCaptor.forClass(ScorePositionRangeReq.class);
        Mockito.verify(gaotuService).getScorePositionRange(captor.capture());
        assertEquals("330000", captor.getValue().getAreaId());
        assertEquals("WL", captor.getValue().getSubject());
        assertEquals("BEN", captor.getValue().getDataLevel());
        assertEquals("2026", captor.getValue().getYear());
        assertEquals("621", captor.getValue().getScore());

        // preview 仍然不落任何东西：pending / 成绩行都不许写。
        assertFalse(upserted.iterator().hasNext(), "preview 不许落 pending");
        Mockito.verify(extraDataSharedService, Mockito.never()).save(Mockito.any());
        Mockito.verify(extraDataSharedService, Mockito.never()).updateById(Mockito.any());
    }

    @Test
    void previewKeepsPositionEmptyWhenUpstreamHasNoData() {
        when(gaotuService.getScorePositionRange(Mockito.any(ScorePositionRangeReq.class))).thenReturn(null);

        CreateSessionReq req = scoreRequest();
        req.setTotalScorePos(null);
        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, req);

        assertFalse(preview.getSummary().containsKey("totalScorePos"),
                "上游没有该省一分一段（data:null）就如实留空，不造数——与执行段同一口径");
    }

    // prepare 与 preview 共用同一条核心：prepare 落 pending 的摘要也含补出来的位次。
    @Test
    void prepareSummaryAlsoCarriesTheFilledPosition() {
        ScorePositionRangeRes range = new ScorePositionRangeRes();
        range.setLowestRank(43879);
        when(gaotuService.getScorePositionRange(Mockito.any(ScorePositionRangeReq.class))).thenReturn(range);

        CreateSessionReq req = scoreRequest();
        req.setTotalScorePos(null);
        service.prepareScoreUpdateProposal(1L, 2L, "req-4", "digest-4", req);

        assertEquals(1, upserted.size());
        Map<?, ?> summary = (Map<?, ?>) upserted.get(0).getDataValue().get("scoreSummary");
        assertEquals(43879, summary.get("totalScorePos"),
                "卡片摘要与执行集一致：补出来的位次要进摘要");
    }

    private CreateSessionReq scoreRequest() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江省");
        req.setProvince(province);
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("WL");
        subjectType.setDesc("物理");
        req.setSubjectType(subjectType);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("3");
        batch.setName("本科批");
        batch.setLevel("BEN");
        batch.setScore(492F);
        req.setBatch(batch);
        req.setTotalScore(621);
        req.setTotalScorePos(8123);
        req.setExamYear(2026);
        // 各科编码必须是**标准码**（08/10/11 语数外）：非标准码现在会在落库前被
        // 110 挡下（见 ChatSessionBizServiceScoreUpdateSubjectCodeTest），这份夹具
        // 走的是"编码齐备"的绿灯路径。
        CreateSessionReq.SubjectScore chinese = new CreateSessionReq.SubjectScore();
        chinese.setSubject("08");
        chinese.setSubjectName("语文");
        chinese.setScore(118);
        CreateSessionReq.SubjectScore math = new CreateSessionReq.SubjectScore();
        math.setSubject("10");
        math.setSubjectName("数学");
        math.setScore(131);
        CreateSessionReq.SubjectScore english = new CreateSessionReq.SubjectScore();
        english.setSubject("11");
        english.setSubjectName("英语");
        english.setScore(126);
        req.setSubjectScoreList(Lists.newArrayList(chinese, math, english));
        return req;
    }
}
