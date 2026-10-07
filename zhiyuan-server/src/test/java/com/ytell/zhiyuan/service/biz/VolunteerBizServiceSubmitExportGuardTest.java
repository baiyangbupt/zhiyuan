package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.manager.ali.AliOSSService;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.File;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * submit/export 对缺 {@code volunteerCount} 的**硬前置拒绝**（2026-10-07 独立审查 H3）。
 *
 * <p>修复前的静默路径：成绩行缺填报数量 → 推荐流水线按 0 配额降级（候选最多 15 个）→
 * submit 照样落 FINAL 文件 + 传 OSS + 把会话置 {@code FINISHED}，export 照样导出 Excel。
 * 本测试要证明三件事：①两条入口都在"生成之前"用 110 拒绝；②拒绝时**没有任何**产物/状态副作用
 * （流水线、OSS、会话状态全没动）；③正常数据（volunteerCount 齐）不会被误伤，仍然跑完整条链。</p>
 */
class VolunteerBizServiceSubmitExportGuardTest {

    private static final Long TENANT_ID = 1L;
    private static final Long SESSION_ID = 900123L;

    private VolunteerBizService service;
    private ChatSessionExtraDataSharedService extraDataSharedService;
    private ChatSessionSharedService chatSessionSharedService;
    private ChatSessionBizService chatSessionBizService;
    private VolunteerFilterChain filterChain;
    private VolunteerSorterAndMerger sorterAndMerger;
    private VolunteerResponseBuilder responseBuilder;
    private AliOSSService aliOSSService;
    private VolunteerFilePathUtil filePathUtil;

    @TempDir
    Path tempDir;

    @BeforeEach
    void setUp() {
        service = new VolunteerBizService();

        // dataProvider 用真对象：volunteerCount → targetSchoolCount 的取数口径要真跑，
        // 只把它依赖的三个 shared/biz 服务做成替身。
        VolunteerDataProvider dataProvider = new VolunteerDataProvider();
        extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        chatSessionSharedService = mock(ChatSessionSharedService.class);
        chatSessionBizService = mock(ChatSessionBizService.class);
        ReflectionTestUtils.setField(dataProvider, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(dataProvider, "chatSessionExtraDataSharedService", extraDataSharedService);
        ReflectionTestUtils.setField(dataProvider, "chatSessionBizService", chatSessionBizService);

        filterChain = mock(VolunteerFilterChain.class);
        sorterAndMerger = mock(VolunteerSorterAndMerger.class);
        responseBuilder = mock(VolunteerResponseBuilder.class);
        aliOSSService = mock(AliOSSService.class);
        filePathUtil = mock(VolunteerFilePathUtil.class);

        ReflectionTestUtils.setField(service, "dataProvider", dataProvider);
        ReflectionTestUtils.setField(service, "filterChain", filterChain);
        ReflectionTestUtils.setField(service, "sorterAndMerger", sorterAndMerger);
        ReflectionTestUtils.setField(service, "responseBuilder", responseBuilder);
        ReflectionTestUtils.setField(service, "aliOSSService", aliOSSService);
        ReflectionTestUtils.setField(service, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", extraDataSharedService);
        ReflectionTestUtils.setField(service, "volunteerFilePathUtil", filePathUtil);
        ReflectionTestUtils.setField(service, "utils", mock(VolunteerUtils.class));
        // 配额换算用真实现：>0 的填报数量在对照用例里要真的能算出冲/稳/保三个配额。
        ReflectionTestUtils.setField(service, "volunteerIntervalService",
                new com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService());
    }

    // ① submit：缺 volunteerCount → 110 拒绝，且不给任何"最终产物"副作用。
    @Test
    void submitIsRejectedWhenVolunteerCountMissing() {
        stubScoreRow(scoreJson(null, null));
        stubVolunteerSource("OTON");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.submitVolunteerList(TENANT_ID, SESSION_ID));
        assertEquals(110, ex.getStatus());
        assertTrue(ex.getMessage().contains("填报数量"), "拒绝信息要指向缺填报数量：" + ex.getMessage());

        // 堵死的正是"静默产出坏产物"：流水线没跑、OSS 没传、会话没被置 FINISHED。
        verify(sorterAndMerger, never()).sortAndSplitByInterval(any(), any(), any(), any(), anyBoolean(), any());
        verify(responseBuilder, never()).buildVolunteerRecommendResponse(any(), any(), any(), any(), any());
        verify(aliOSSService, never()).uploadFile(anyString(), any(File.class));
        verify(chatSessionSharedService, never()).updateById(any());
        verify(extraDataSharedService, never()).saveOrUpdateSessionStatus(anyLong(), any());
    }

    // ② 对照：volunteerCount 齐 → 不误伤，照常跑完整条提交链并置 FINISHED。
    @Test
    void submitProceedsWhenVolunteerCountPresent() {
        stubScoreRow(scoreJson(45, 96));
        stubVolunteerSource("OTON");
        stubPipeline();
        stubArtifactFiles();

        Boolean ok = service.submitVolunteerList(TENANT_ID, SESSION_ID);

        assertEquals(Boolean.TRUE, ok);
        ArgumentCaptor<ChatSession> captor = ArgumentCaptor.forClass(ChatSession.class);
        verify(chatSessionSharedService).updateById(captor.capture());
        assertEquals(SessionStatus.FINISHED, captor.getValue().getSessionStatus());
        verify(sorterAndMerger).sortAndSplitByInterval(any(), any(), any(), eq("OTON"), eq(true), any());
    }

    // ③ export：缺 volunteerCount → 110 拒绝，不生成 Excel 数据。
    @Test
    void exportIsRejectedWhenVolunteerCountMissing() {
        stubScoreRow(scoreJson(null, null));
        stubVolunteerSource("OTON");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> service.exportVolunteerList(TENANT_ID, SESSION_ID));
        assertEquals(110, ex.getStatus());
        assertTrue(ex.getMessage().contains("填报数量"), "拒绝信息要指向缺填报数量：" + ex.getMessage());

        verify(responseBuilder, never()).convertToExcelData(any());
        verify(sorterAndMerger, never()).sortAndSplitByInterval(any(), any(), any(), any(), anyBoolean(), any());
    }

    // ④ 对照：volunteerCount 齐 → 正常导出（拿到文件字节与文件名）。
    @Test
    void exportProceedsWhenVolunteerCountPresent() {
        stubScoreRow(scoreJson(45, 96));
        stubVolunteerSource("OTON");
        stubPipeline();
        ChatSession session = new ChatSession();
        session.setId(SESSION_ID);
        session.setSessionStatus(SessionStatus.GOING);
        when(chatSessionSharedService.getById(SESSION_ID)).thenReturn(session);
        when(responseBuilder.convertToExcelData(any()))
                .thenReturn(new VolunteerResponseBuilder.ExcelDataWrapper(Lists.newArrayList(), Lists.newArrayList()));

        VolunteerBizService.ExcelExportResult result = service.exportVolunteerList(TENANT_ID, SESSION_ID);

        assertNotNull(result);
        assertNotNull(result.getExcelData());
        assertTrue(result.getExcelData().length > 0, "导出的 Excel 不应为空");
        assertNotNull(result.getFileName());
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    /** 成绩行：schoolCount=null/majorCount=null 即"老会话/legacy 草稿未补录"的缺字段形状。 */
    private String scoreJson(Integer schoolCount, Integer majorCount) {
        JSONObject score = new JSONObject();
        score.put("totalScore", 610);
        score.put("examYear", 2026);
        JSONObject province = new JSONObject();
        province.put("code", "330000");
        province.put("name", "浙江");
        score.put("province", province);
        JSONObject subjectType = new JSONObject();
        subjectType.put("code", "N");
        subjectType.put("desc", "综合");
        score.put("subjectType", subjectType);
        JSONObject batch = new JSONObject();
        batch.put("code", "B1");
        batch.put("name", "本科批");
        batch.put("level", "01");
        score.put("batch", batch);
        if (schoolCount != null || majorCount != null) {
            JSONObject volunteerCount = new JSONObject();
            volunteerCount.put("schoolCount", schoolCount);
            volunteerCount.put("majorCount", majorCount);
            score.put("volunteerCount", volunteerCount);
        }
        return JSON.toJSONString(score);
    }

    private void stubScoreRow(String scoreJson) {
        ChatSessionExtraData row = new ChatSessionExtraData();
        row.setId(1L);
        row.setChatSessionId(SESSION_ID);
        row.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        row.setDataValue(scoreJson);
        when(extraDataSharedService.getBySessionIdAndDataKey(
                SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY)).thenReturn(row);
    }

    private void stubVolunteerSource(String applyType) {
        VolunteerDataDTO dto = new VolunteerDataDTO();
        ProgramPageDTO.Type type = new ProgramPageDTO.Type();
        type.setCode(applyType);
        type.setDesc(applyType);
        dto.setType(type);
        when(chatSessionBizService.loadChatSessionVolunteerData(SESSION_ID)).thenReturn(dto);
    }

    /** 把推荐流水线的下游全部替身化（本测试关心的是门禁，不是流水线内部）。 */
    private void stubPipeline() {
        when(filterChain.filterVolunteerData(any(), any())).thenReturn(Lists.newArrayList());
        Map<String, List<com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup>> sorted = new HashMap<>();
        sorted.put("冲", Lists.newArrayList());
        sorted.put("稳", Lists.newArrayList());
        sorted.put("保", Lists.newArrayList());
        when(sorterAndMerger.sortAndSplitByInterval(any(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(sorted);
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.setMajorSchoolType(Boolean.FALSE);
        when(responseBuilder.buildVolunteerRecommendResponse(any(), any(), any(), any(), any()))
                .thenReturn(response);
    }

    private void stubArtifactFiles() {
        when(filePathUtil.getLocalFilePath(anyLong(), any(VolunteerFilePathUtil.VolunteerFileType.class)))
                .thenAnswer(invocation -> tempDir
                        .resolve("artifact_" + ((VolunteerFilePathUtil.VolunteerFileType) invocation.getArgument(1)).name())
                        .toString());
        when(filePathUtil.getOssFilePath(anyLong(), any(VolunteerFilePathUtil.VolunteerFileType.class)))
                .thenAnswer(invocation -> "oss/" + ((VolunteerFilePathUtil.VolunteerFileType) invocation.getArgument(1)).name());
        when(aliOSSService.uploadFile(anyString(), any(File.class))).thenReturn("etag");
    }
}
