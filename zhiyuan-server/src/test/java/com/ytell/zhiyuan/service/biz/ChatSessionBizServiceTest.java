package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorRequest;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.vo.ChatSessionVo;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class ChatSessionBizServiceTest {

    private ChatSessionBizService chatSessionBizService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private PlanningStateService planningStateService;
    private VolunteerDataProvider volunteerDataProvider;
    private VolunteerRankClient volunteerRankClient;

    @BeforeEach
    void setUp() {
        chatSessionBizService = new ChatSessionBizService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        planningStateService = Mockito.mock(PlanningStateService.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);
        volunteerRankClient = Mockito.mock(VolunteerRankClient.class);

        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerDataProvider", volunteerDataProvider);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerRankClient", volunteerRankClient);
    }

    @Test
    void shouldSyncPlanningStateWhenSavingUserProfile() {
        ChatSessionExtraDataReq req = new ChatSessionExtraDataReq();
        req.setChatSessionId(6L);
        req.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        req.setDataType(DataType.JSON_OBJECT);

        UserProfileData userProfileData = new UserProfileData();
        userProfileData.getNegative_city_info().setProvince(java.util.Arrays.asList("北京"));
        req.setDataValue(userProfileData);

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(6L, ChatSessionExtraDataConstants.USER_PROFILE_KEY, 0))
                .thenReturn(null);
        when(volunteerDataProvider.getUserScoreDetail(6L)).thenReturn(new CreateSessionReq());

        chatSessionBizService.addOrUpdateSessionExtraData(1L, req);

        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService).syncProfileStateFromLegacy(eq(6L), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    @Test
    void shouldNotSyncPlanningStateWhenSavingNonProfileExtraData() {
        ChatSessionExtraDataReq req = new ChatSessionExtraDataReq();
        req.setChatSessionId(6L);
        req.setDataKey("planEditCache");
        req.setDataType(DataType.JSON_OBJECT);
        req.setDataValue(java.util.Collections.singletonMap("foo", "bar"));

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(6L, "planEditCache", 0))
                .thenReturn(null);

        chatSessionBizService.addOrUpdateSessionExtraData(1L, req);

        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService, never()).syncProfileStateFromLegacy(any(Long.class), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    @Test
    void shouldDefaultPrepareTypeToVolunteerWhenMissing() {
        CreateSessionReq req = new CreateSessionReq();

        chatSessionBizService.normalizeCreateSessionDefaults(req);

        assertNotNull(req.getPrepareType());
        assertEquals("VOLUNTEER", req.getPrepareType().getCode());
        assertEquals("智能填报", req.getPrepareType().getDesc());
    }

    @Test
    void shouldCreateEmptySessionWithoutCollectedInfoWhenDraft() {
        // 空会话：省份/批次/选科/成绩一个都不给，也必须建得出来——
        // 那几项本来就是对话要采集的信息，不是建会话的前提。
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(7L);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);

        ChatSessionSharedService chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        UserBizService userBizService = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "userBizService", userBizService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(true);
        when(userBizService.checkRights(eq(7L), eq(OperateCheckPoint.CreateSession), any()))
                .thenReturn(rights);
        when(chatSessionSharedService.saveSession(any(ChatSession.class))).thenAnswer(invocation -> {
            ChatSession session = invocation.getArgument(0);
            session.setId(900L);
            return session;
        });

        CreateSessionReq req = new CreateSessionReq();
        req.setBotId(1L);
        req.setDraft(Boolean.TRUE);

        ChatSessionVo vo = chatSessionBizService.createChatSession(1L, req);

        assertEquals(900L, vo.getId());
        // 空会话连欢迎语都不发：会话一旦带上占位信息，模型就不会再问缺什么。
        verify(chatSessionExtraDataSharedService, never())
                .save(any(ChatSessionExtraData.class));
        verify(chatSessionSharedService, never()).pageSession(any(), any());
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldStillCheckRightsForEmptySession() {
        // 空会话也是会话：判据不该因为信息空着而放宽。
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(7L);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);

        ChatSessionSharedService chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        UserBizService userBizService = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "userBizService", userBizService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(false);
        rights.setReason("智能填报需要权益");
        when(userBizService.checkRights(eq(7L), eq(OperateCheckPoint.CreateSession), any()))
                .thenReturn(rights);

        CreateSessionReq req = new CreateSessionReq();
        req.setBotId(1L);
        req.setDraft(Boolean.TRUE);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.createChatSession(1L, req));

        assertEquals("智能填报需要权益", exception.getMessage());
        verify(chatSessionSharedService, never()).saveSession(any(ChatSession.class));
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldRejectCreateSessionWhenBatchMissing() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode("VOLUNTEER");
        req.setPrepareType(prepareType);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.createChatSession(1L, req));

        assertEquals("请选择批次后再创建会话", exception.getMessage());
    }

    @Test
    void shouldFillDefaultSexStrategyTypeAndPrepareTypeWhenMissing() {
        CreateSessionReq req = new CreateSessionReq();

        chatSessionBizService.normalizeCreateSessionDefaults(req);

        assertNotNull(req.getSex());
        assertEquals("female", req.getSex().getCode());
        assertEquals("女", req.getSex().getName());
        assertNotNull(req.getPrepareType());
        assertEquals("VOLUNTEER", req.getPrepareType().getCode());
        assertEquals("智能填报", req.getPrepareType().getDesc());
        assertNotNull(req.getStrategyType());
        assertEquals("cautious", req.getStrategyType().getCode());
        assertEquals("稳妥型", req.getStrategyType().getName());
    }

    @Test
    void shouldReturnEmptyMajorRecommendWhenRankUnavailable() {
        when(volunteerRankClient.getRecommendSubMajor(any(RecommendSubMajorRequest.class)))
                .thenThrow(new RuntimeException("rank unavailable"));

        List<RecommendSubMajorResponse.MajorRecommendItem> result = chatSessionBizService.recommendMajor(new CreateSessionReq());

        assertNotNull(result);
        assertEquals(0, result.size());
    }

    @Test
    void shouldLimitMajorRecommendToEightItems() {
        RecommendSubMajorResponse response = new RecommendSubMajorResponse();
        List<RecommendSubMajorResponse.MajorRecommendItem> items = new ArrayList<>();
        for (int i = 0; i < 10; i++) {
            RecommendSubMajorResponse.MajorRecommendItem item = new RecommendSubMajorResponse.MajorRecommendItem();
            item.setMajorId(String.valueOf(i));
            item.setMajor("专业" + i);
            items.add(item);
        }
        response.setReconmandlist(items);
        when(volunteerRankClient.getRecommendSubMajor(any(RecommendSubMajorRequest.class))).thenReturn(response);

        List<RecommendSubMajorResponse.MajorRecommendItem> result = chatSessionBizService.recommendMajor(new CreateSessionReq());

        assertEquals(8, result.size());
        assertEquals("专业0", result.get(0).getMajor());
        assertEquals("专业7", result.get(7).getMajor());
    }
}
