package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.inner.MajorRecommendPreviewReq;
import com.ytell.zhiyuan.model.dto.inner.MajorRecommendPreviewRes;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;

/**
 * 专业方向推荐预览（只读纵切）的合同：
 * **缺画像/缺分数如实回 data:null + 原因**（不造数）、**topN 硬上限 8**、
 * **只读**（除了读画像与打分，不碰别的东西）。
 *
 * <p>为什么要在受控输入下量这几条：真栈能证明"这个会话这一次好使"，但
 * "没有档案时到底回什么""第 9 条为什么不见了"这类边界只有单测看得清。</p>
 */
public class MajorRecommendPreviewServiceTest {

    private ChatSessionBizService chatSessionBizService;
    private MajorRecommendPreviewService service;

    @BeforeEach
    void setUp() {
        chatSessionBizService = Mockito.mock(ChatSessionBizService.class);
        service = new MajorRecommendPreviewService();
        ReflectionTestUtils.setField(service, "chatSessionBizService", chatSessionBizService);
    }

    private MajorRecommendPreviewReq request(Long chatSessionId, Integer topN) {
        MajorRecommendPreviewReq req = new MajorRecommendPreviewReq();
        req.setChatSessionId(chatSessionId);
        req.setTopN(topN);
        return req;
    }

    /** 一份 rank 算法读得动的完整画像（batch/subjectType/sex/subjectList/strengthSubjectList 齐）。 */
    private CreateSessionReq fullProfile() {
        CreateSessionReq profile = new CreateSessionReq();
        profile.setTotalScore(610);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("17");
        batch.setLevel("01");
        profile.setBatch(batch);
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("N");
        subjectType.setDesc("综合");
        profile.setSubjectType(subjectType);
        CreateSessionReq.Sex sex = new CreateSessionReq.Sex();
        sex.setCode("male");
        profile.setSex(sex);
        profile.setSubjectList(Lists.newArrayList(
                new CreateSessionReq.SubjectItem(1, "01", "01", "物理"),
                new CreateSessionReq.SubjectItem(0, "02", "05", "化学")));
        CreateSessionReq.SubjectScore strength = new CreateSessionReq.SubjectScore();
        strength.setSubject("01");
        strength.setSubjectName("物理");
        profile.setStrengthSubjectList(Lists.newArrayList(strength));
        return profile;
    }

    private List<RecommendSubMajorResponse.MajorRecommendItem> items(int count) {
        List<RecommendSubMajorResponse.MajorRecommendItem> list = Lists.newArrayList();
        for (int i = 1; i <= count; i++) {
            RecommendSubMajorResponse.MajorRecommendItem item =
                    new RecommendSubMajorResponse.MajorRecommendItem();
            item.setMajorId("m-" + i);
            item.setMajor("专业方向" + i);
            item.setScore(100.0 - i);
            list.add(item);
        }
        return list;
    }

    private void assertUnavailable(ResponseDTO<MajorRecommendPreviewRes> result, String reason) {
        assertEquals(0, result.getCode(), "业务码 0：'没有这份画像'不是查询失败");
        assertEquals(reason, result.getMsg());
        assertNull(result.getData(), "缺画像/缺分数必须回 data:null——不许造数");
    }

    @Test
    void shouldReturnNullDataWithReasonWhenSessionHasNoProfile() {
        doReturn(null).when(chatSessionBizService).loadSessionScoreDetail(900123L);

        assertUnavailable(service.preview(request(900123L, null)),
                MajorRecommendPreviewService.REASON_PROFILE_MISSING);

        // 没有画像就没得推荐：连打分都不该发生，更不能写任何东西。
        verify(chatSessionBizService).loadSessionScoreDetail(900123L);
        verify(chatSessionBizService, never()).recommendMajor(any(CreateSessionReq.class));
        verifyNoMoreInteractions(chatSessionBizService);
    }

    @Test
    void shouldReturnNullDataWithReasonWhenProfileHasNoScore() {
        CreateSessionReq profile = fullProfile();
        profile.setTotalScore(null);
        doReturn(profile).when(chatSessionBizService).loadSessionScoreDetail(900123L);

        assertUnavailable(service.preview(request(900123L, null)),
                MajorRecommendPreviewService.REASON_SCORE_MISSING);
        verify(chatSessionBizService, never()).recommendMajor(any(CreateSessionReq.class));
    }

    @Test
    void shouldNameTheMissingRankInputsInsteadOfReturningAnEmptyList() {
        // rank 侧对缺字段是 500 → Java 降级空列表：不挡的话"没有推荐"与"调不动"同形。
        CreateSessionReq profile = fullProfile();
        profile.setBatch(null);
        profile.setSex(null);
        profile.setStrengthSubjectList(Collections.emptyList());
        doReturn(profile).when(chatSessionBizService).loadSessionScoreDetail(900123L);

        assertUnavailable(service.preview(request(900123L, null)),
                MajorRecommendPreviewService.REASON_PROFILE_INCOMPLETE_PREFIX
                        + "batchLevel,sex,strengthSubjectList");
        verify(chatSessionBizService, never()).recommendMajor(any(CreateSessionReq.class));
    }

    @Test
    void shouldTrimToRequestedTopNAndEchoTheEffectiveTopN() {
        doReturn(fullProfile()).when(chatSessionBizService).loadSessionScoreDetail(900123L);
        doReturn(items(8)).when(chatSessionBizService).recommendMajor(any(CreateSessionReq.class));

        ResponseDTO<MajorRecommendPreviewRes> result = service.preview(request(900123L, 3));

        assertEquals(0, result.getCode());
        assertEquals("ok", result.getMsg());
        MajorRecommendPreviewRes data = result.getData();
        assertEquals(3, data.getTopN());
        assertEquals(3, data.getItems().size());
        assertEquals("专业方向1", data.getItems().get(0).getMajor());
        assertTrue(data.getLimitations().isEmpty());

        // 只读：读画像 + 打分，别的什么都不碰（写路径不在这条链上）。
        verify(chatSessionBizService).loadSessionScoreDetail(900123L);
        verify(chatSessionBizService).recommendMajor(any(CreateSessionReq.class));
        verifyNoMoreInteractions(chatSessionBizService);
    }

    @Test
    void shouldCapTopNAtEightAndDefaultToEight() {
        doReturn(fullProfile()).when(chatSessionBizService).loadSessionScoreDetail(900123L);
        doReturn(items(8)).when(chatSessionBizService).recommendMajor(any(CreateSessionReq.class));

        MajorRecommendPreviewRes capped = service.preview(request(900123L, 100)).getData();
        assertEquals(MajorRecommendPreviewService.MAX_TOP_N, capped.getTopN(),
                "硬上限 8：超了截断，不报错也不透传");
        assertEquals(8, capped.getItems().size());

        MajorRecommendPreviewRes defaulted = service.preview(request(900123L, null)).getData();
        assertEquals(MajorRecommendPreviewService.MAX_TOP_N, defaulted.getTopN());
    }

    @Test
    void shouldFlagEmptyResultInsteadOfSilentlyReturningNothing() {
        doReturn(fullProfile()).when(chatSessionBizService).loadSessionScoreDetail(900123L);
        doReturn(Collections.emptyList()).when(chatSessionBizService).recommendMajor(any(CreateSessionReq.class));

        MajorRecommendPreviewRes data = service.preview(request(900123L, null)).getData();

        assertTrue(data.getItems().isEmpty());
        assertEquals(Collections.singletonList(MajorRecommendPreviewService.LIMITATION_EMPTY),
                data.getLimitations(), "空结果如实标注，不当成'用户没有可推荐方向'");
    }

    @Test
    void shouldRejectRequestWithoutChatSessionId() {
        BusinessException ex = assertThrows(BusinessException.class, () -> service.preview(request(null, null)));
        assertEquals(110, ex.getStatus());
    }
}
