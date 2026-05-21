package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

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

    @BeforeEach
    void setUp() {
        chatSessionBizService = new ChatSessionBizService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        planningStateService = Mockito.mock(PlanningStateService.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);

        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerDataProvider", volunteerDataProvider);
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
    void shouldRejectCreateSessionWhenBatchMissing() {
        CreateSessionReq req = new CreateSessionReq();

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.createChatSession(1L, req));

        assertEquals("请选择批次后再创建会话", exception.getMessage());
    }

    @Test
    void shouldFillDefaultSexAndStrategyTypeWhenMissing() {
        CreateSessionReq req = new CreateSessionReq();

        chatSessionBizService.normalizeCreateSessionDefaults(req);

        assertNotNull(req.getSex());
        assertEquals("female", req.getSex().getCode());
        assertEquals("女", req.getSex().getName());
        assertNotNull(req.getStrategyType());
        assertEquals("cautious", req.getStrategyType().getCode());
        assertEquals("稳妥型", req.getStrategyType().getName());
    }
}
